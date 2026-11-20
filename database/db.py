import aiosqlite

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


DB_NAME = str(
    Path(__file__).resolve().parent.parent
    / "f_society.db"
)

DB_TIMEOUT = 10
FREE_SEARCHES_LIMIT = 2

MSK = timezone(
    timedelta(hours=3)
)


def get_current_timestamp() -> str:
    return datetime.now(MSK).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


@asynccontextmanager
async def connect_db():
    db = await aiosqlite.connect(
        DB_NAME,
        timeout=DB_TIMEOUT
    )

    try:
        db.row_factory = aiosqlite.Row

        await db.execute(
            "PRAGMA busy_timeout = 10000"
        )

        await db.execute(
            "PRAGMA foreign_keys = ON"
        )

        yield db

    finally:
        await db.close()


async def init_db() -> None:
    async with connect_db() as db:
        await db.execute(
            "PRAGMA journal_mode = WAL"
        )

        await db.execute(f"""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,

                balance INTEGER NOT NULL DEFAULT 0
                    CHECK (balance >= 0),

                free_searches INTEGER NOT NULL
                    DEFAULT {FREE_SEARCHES_LIMIT}
                    CHECK (free_searches >= 0),

                joined_date TEXT NOT NULL,
                referrer_id INTEGER DEFAULT NULL,

                invited_count INTEGER NOT NULL DEFAULT 0
                    CHECK (invited_count >= 0),

                cases_opened INTEGER NOT NULL DEFAULT 0
                    CHECK (cases_opened >= 0),

                items_bought INTEGER NOT NULL DEFAULT 0
                    CHECK (items_bought >= 0),

                items_spent_total INTEGER NOT NULL DEFAULT 0
                    CHECK (items_spent_total >= 0),

                vpn_days_left INTEGER NOT NULL DEFAULT 7
                    CHECK (vpn_days_left >= 0),

                vpn_days_bought INTEGER NOT NULL DEFAULT 0
                    CHECK (vpn_days_bought >= 0),

                is_banned INTEGER NOT NULL DEFAULT 0
                    CHECK (is_banned IN (0, 1)),

                CHECK (
                    referrer_id IS NULL
                    OR referrer_id != user_id
                ),

                FOREIGN KEY (referrer_id)
                    REFERENCES users(user_id)
                    ON DELETE SET NULL
            )
        """)

        # Миграция существующей таблицы users.
        async with db.execute(
            "PRAGMA table_info(users)"
        ) as cursor:
            user_columns = await cursor.fetchall()

        existing_columns = {
            column["name"]
            for column in user_columns
        }

        if "ban_reason" not in existing_columns:
            await db.execute("""
                ALTER TABLE users
                ADD COLUMN ban_reason TEXT
            """)

        if "ban_date" not in existing_columns:
            await db.execute("""
                ALTER TABLE users
                ADD COLUMN ban_date TEXT
            """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_users_referrer
            ON users(referrer_id)
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_users_banned
            ON users(is_banned)
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_bans (
                ban_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,

                ban_reason TEXT,
                banned_at TEXT NOT NULL,
                banned_by INTEGER,

                unban_reason TEXT,
                unbanned_at TEXT,
                unbanned_by INTEGER,

                FOREIGN KEY (user_id)
                    REFERENCES users(user_id)
                    ON DELETE CASCADE
            )
        """)

        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_user_bans_active
            ON user_bans(user_id)
            WHERE unbanned_at IS NULL
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_user_bans_user
            ON user_bans(user_id, banned_at DESC)
        """)

        # Перенос текущих блокировок в историю.
        # Старые данные об администраторе неизвестны,
        # поэтому banned_by остаётся NULL.
        await db.execute(
            """
            INSERT INTO user_bans (
                user_id,
                ban_reason,
                banned_at,
                banned_by
            )
            SELECT
                users.user_id,
                users.ban_reason,
                COALESCE(users.ban_date, ?),
                NULL
            FROM users
            WHERE users.is_banned = 1
              AND NOT EXISTS (
                  SELECT 1
                  FROM user_bans
                  WHERE user_bans.user_id = users.user_id
                    AND user_bans.unbanned_at IS NULL
              )
            """,
            (get_current_timestamp(),)
        )

        await db.execute("""
            CREATE TABLE IF NOT EXISTS
            user_subscriptions (
                user_id INTEGER NOT NULL,
                notification_type TEXT NOT NULL,

                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK (is_active IN (0, 1)),

                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,

                PRIMARY KEY (
                    user_id,
                    notification_type
                ),

                FOREIGN KEY (user_id)
                    REFERENCES users(user_id)
                    ON DELETE CASCADE
            )
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_subscriptions_active
            ON user_subscriptions (
                notification_type,
                is_active
            )
        """)

        # Основная таблица обращений поддержки.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER NOT NULL,

                category TEXT NOT NULL
                    CHECK (
                        category IN (
                            'problem',
                            'suggestion',
                            'feedback',
                            'question'
                        )
                    ),

                status TEXT NOT NULL DEFAULT 'open'
                    CHECK (
                        status IN (
                            'open',
                            'in_progress',
                            'closed'
                        )
                    ),

                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                closed_at TEXT,

                assigned_admin_id INTEGER,

                FOREIGN KEY (user_id)
                    REFERENCES users(user_id)
                    ON DELETE CASCADE
            )
        """)

        # Удаление старого ограничения:
        # теперь пользователь может создавать несколько
        # активных тикетов одной категории после cooldown.
        await db.execute("""
            DROP INDEX IF EXISTS idx_support_tickets_active
        """)

        # Поиск истории обращений пользователя.
        await db.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_support_tickets_user_history
            ON support_tickets(
                user_id,
                category,
                created_at DESC
            )
        """)

        # Сообщения внутри обращений.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS support_ticket_messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,

                ticket_id INTEGER NOT NULL,

                sender_id INTEGER NOT NULL,

                sender_type TEXT NOT NULL
                    CHECK (
                        sender_type IN ('user', 'admin')
                    ),

                message_text TEXT NOT NULL
                    CHECK (
                        length(trim(message_text)) > 0
                    ),

                created_at TEXT NOT NULL,

                FOREIGN KEY (ticket_id)
                    REFERENCES support_tickets(ticket_id)
                    ON DELETE CASCADE
            )
        """)

        # Быстрое получение переписки тикета.
        await db.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_support_messages_ticket
            ON support_ticket_messages(
                ticket_id,
                created_at
            )
        """)

        # Состояние уведомлений администраторов о тикетах.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS support_admin_notifications (
                admin_id INTEGER PRIMARY KEY,
                message_id INTEGER,
                is_active INTEGER NOT NULL DEFAULT 0
                    CHECK (is_active IN (0, 1))
            )
        """)

        # Запросы на передачу тикетов между администраторами.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS support_ticket_transfer_requests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,

                ticket_id INTEGER NOT NULL,

                from_admin_id INTEGER NOT NULL,
                to_admin_id INTEGER NOT NULL,

                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (
                        status IN (
                            'pending',
                            'accepted',
                            'rejected',
                            'cancelled'
                        )
                    ),

                created_at TEXT NOT NULL,
                responded_at TEXT,

                FOREIGN KEY (ticket_id)
                    REFERENCES support_tickets(ticket_id)
                    ON DELETE CASCADE
            )
        """)

        # Один активный запрос передачи на тикет.
        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_ticket_transfer_pending
            ON support_ticket_transfer_requests(ticket_id)
            WHERE status = 'pending'
        """)

        await db.commit()


async def add_user_to_db(
    user_id: int,
    username: str,
    full_name: str,
    referrer_id: int | None = None
) -> bool:

    async with connect_db() as db:
        await db.execute("BEGIN IMMEDIATE")

        try:
            joined_date = get_current_timestamp()
            valid_referrer_id = None

            if (
                referrer_id is not None
                and referrer_id != user_id
            ):
                async with db.execute(
                    """
                    SELECT user_id
                    FROM users
                    WHERE user_id = ?
                    """,
                    (referrer_id,)
                ) as cursor:
                    referrer = await cursor.fetchone()

                if referrer is not None:
                    valid_referrer_id = referrer_id

            cursor = await db.execute(
                """
                INSERT OR IGNORE INTO users (
                    user_id,
                    username,
                    full_name,
                    balance,
                    free_searches,
                    joined_date,
                    referrer_id,
                    invited_count,
                    cases_opened,
                    items_bought,
                    items_spent_total,
                    vpn_days_left,
                    vpn_days_bought,
                    is_banned
                )
                VALUES (
                    ?, ?, ?, 0, ?, ?, ?, 0,
                    0, 0, 0, 7, 0, 0
                )
                """,
                (
                    user_id,
                    username,
                    full_name,
                    FREE_SEARCHES_LIMIT,
                    joined_date,
                    valid_referrer_id
                )
            )

            is_new_user = cursor.rowcount == 1

            if (
                is_new_user
                and valid_referrer_id is not None
            ):
                await db.execute(
                    """
                    UPDATE users
                    SET invited_count = invited_count + 1
                    WHERE user_id = ?
                    """,
                    (valid_referrer_id,)
                )

            if not is_new_user:
                await db.execute(
                    """
                    UPDATE users
                    SET username = ?, full_name = ?
                    WHERE user_id = ?
                    """,
                    (
                        username,
                        full_name,
                        user_id
                    )
                )

            await db.commit()
            return is_new_user

        except Exception:
            await db.rollback()
            raise


async def get_user_profile(
    user_id: int
):
    async with connect_db() as db:
        async with db.execute(
            """
            SELECT
                balance,
                free_searches,
                joined_date,
                invited_count,
                cases_opened,
                items_bought,
                items_spent_total,
                vpn_days_left,
                vpn_days_bought,
                is_banned
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        ) as cursor:
            return await cursor.fetchone()


async def check_user_ban(
    user_id: int
) -> bool:

    async with connect_db() as db:
        async with db.execute(
            """
            SELECT is_banned
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        ) as cursor:
            result = await cursor.fetchone()

            if result is None:
                return False

            return bool(result["is_banned"])


async def get_user_ban_info(
    user_id: int,
):
    async with connect_db() as db:
        async with db.execute(
            """
            SELECT
                is_banned,
                ban_reason,
                ban_date
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        ) as cursor:
            return await cursor.fetchone()


async def get_banned_users():
    async with connect_db() as db:
        async with db.execute(
            """
            SELECT
                user_id,
                username,
                full_name,
                joined_date
            FROM users
            WHERE is_banned = 1
            ORDER BY joined_date DESC
            """
        ) as cursor:
            return await cursor.fetchall()


async def set_user_ban(
    user_id: int,
    is_banned: bool,
    ban_reason: str | None = None,
    admin_id: int | None = None,
    unban_reason: str | None = None,
) -> dict:

    reason = ban_reason.strip() if ban_reason else None
    removal_reason = (
        unban_reason.strip()
        if unban_reason
        else None
    )

    if reason is not None and len(reason) > 1000:
        raise ValueError(
            "Причина блокировки не должна "
            "превышать 1000 символов."
        )

    if removal_reason is not None and len(removal_reason) > 1000:
        raise ValueError(
            "Причина разблокировки не должна "
            "превышать 1000 символов."
        )

    async with connect_db() as db:
        await db.execute("BEGIN IMMEDIATE")

        try:
            async with db.execute(
                """
                SELECT
                    is_banned,
                    ban_reason,
                    ban_date
                FROM users
                WHERE user_id = ?
                """,
                (user_id,)
            ) as cursor:
                user = await cursor.fetchone()

            if user is None:
                await db.commit()
                return {"status": "not_found"}

            currently_banned = bool(user["is_banned"])

            if is_banned and currently_banned:
                await db.commit()
                return {"status": "already_banned"}

            if not is_banned and not currently_banned:
                await db.commit()
                return {"status": "already_unbanned"}

            timestamp = get_current_timestamp()

            if is_banned:
                await db.execute(
                    """
                    UPDATE users
                    SET
                        is_banned = 1,
                        ban_reason = ?,
                        ban_date = ?
                    WHERE user_id = ?
                    """,
                    (
                        reason,
                        timestamp,
                        user_id
                    )
                )

                async with db.execute(
                    """
                    INSERT INTO user_bans (
                        user_id,
                        ban_reason,
                        banned_at,
                        banned_by
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        reason,
                        timestamp,
                        admin_id
                    )
                ) as cursor:
                    ban_id = cursor.lastrowid

                event = {
                    "status": "banned",
                    "ban_id": ban_id,
                    "user_id": user_id,
                    "reason": reason,
                    "timestamp": timestamp,
                    "admin_id": admin_id,
                }

            else:
                async with db.execute(
                    """
                    SELECT ban_id
                    FROM user_bans
                    WHERE user_id = ?
                      AND unbanned_at IS NULL
                    ORDER BY banned_at DESC
                    LIMIT 1
                    """,
                    (user_id,)
                ) as cursor:
                    active_ban = await cursor.fetchone()

                if active_ban is None:
                    async with db.execute(
                        """
                        INSERT INTO user_bans (
                            user_id,
                            ban_reason,
                            banned_at,
                            banned_by
                        )
                        VALUES (?, ?, ?, NULL)
                        """,
                        (
                            user_id,
                            user["ban_reason"],
                            user["ban_date"] or timestamp
                        )
                    ) as cursor:
                        ban_id = cursor.lastrowid
                else:
                    ban_id = active_ban["ban_id"]

                await db.execute(
                    """
                    UPDATE users
                    SET
                        is_banned = 0,
                        ban_reason = NULL,
                        ban_date = NULL
                    WHERE user_id = ?
                    """,
                    (user_id,)
                )

                await db.execute(
                    """
                    UPDATE user_bans
                    SET
                        unban_reason = ?,
                        unbanned_at = ?,
                        unbanned_by = ?
                    WHERE ban_id = ?
                    """,
                    (
                        removal_reason,
                        timestamp,
                        admin_id,
                        ban_id
                    )
                )

                event = {
                    "status": "unbanned",
                    "ban_id": ban_id,
                    "user_id": user_id,
                    "reason": removal_reason,
                    "timestamp": timestamp,
                    "admin_id": admin_id,
                }

            await db.commit()
            return event

        except Exception:
            await db.rollback()
            raise


async def get_user_ban_history(user_id: int):
    async with connect_db() as db:
        async with db.execute(
            """
            SELECT
                ban_id,
                user_id,
                ban_reason,
                banned_at,
                banned_by,
                unban_reason,
                unbanned_at,
                unbanned_by
            FROM user_bans
            WHERE user_id = ?
            ORDER BY banned_at DESC, ban_id DESC
            """,
            (user_id,)
        ) as cursor:
            return await cursor.fetchall()