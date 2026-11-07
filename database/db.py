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

        await db.commit()


async def add_user_to_db(
    user_id: int,
    username: str,
    full_name: str,
    referrer_id: int | None = None
) -> bool:

    async with connect_db() as db:
        await db.execute(
            "BEGIN IMMEDIATE"
        )

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
                    SET invited_count =
                        invited_count + 1
                    WHERE user_id = ?
                    """,
                    (valid_referrer_id,)
                )

            if not is_new_user:
                await db.execute(
                    """
                    UPDATE users
                    SET
                        username = ?,
                        full_name = ?
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

            return bool(
                result["is_banned"]
            )


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
    is_banned: bool
) -> bool:

    async with connect_db() as db:
        cursor = await db.execute(
            """
            UPDATE users
            SET is_banned = ?
            WHERE user_id = ?
            """,
            (
                int(is_banned),
                user_id
            )
        )

        await db.commit()

        return cursor.rowcount == 1   
                             