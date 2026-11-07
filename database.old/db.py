import aiosqlite
from datetime import datetime, timezone
from contextlib import asynccontextmanager


DB_NAME = "f_society.db"
DB_TIMEOUT = 10


@asynccontextmanager
async def connect_db():
    db = await aiosqlite.connect(
        DB_NAME,
        timeout=DB_TIMEOUT
    )

    try:
        db.row_factory = aiosqlite.Row

        await db.execute("PRAGMA busy_timeout = 10000")
        await db.execute("PRAGMA foreign_keys = ON")

        yield db

    finally:
        await db.close()


async def init_db():
    async with connect_db() as db:
        await db.execute("PRAGMA journal_mode = WAL")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                balance INTEGER NOT NULL DEFAULT 0,
                free_searches INTEGER NOT NULL DEFAULT 2,
                joined_date TEXT,
                referrer_id INTEGER DEFAULT NULL,
                invited_count INTEGER NOT NULL DEFAULT 0,
                cases_opened INTEGER NOT NULL DEFAULT 0,
                items_bought INTEGER NOT NULL DEFAULT 0,
                items_spent_total INTEGER NOT NULL DEFAULT 0,
                vpn_days_left INTEGER NOT NULL DEFAULT 7,
                vpn_days_bought INTEGER NOT NULL DEFAULT 0,
                is_banned INTEGER NOT NULL DEFAULT 0
            )
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_referrer
            ON users(referrer_id)
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_subscriptions (
                user_id INTEGER NOT NULL,
                notification_type TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, notification_type),
                FOREIGN KEY (user_id)
                    REFERENCES users(user_id)
                    ON DELETE CASCADE
            )
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_subscriptions_active
            ON user_subscriptions(notification_type, is_active)
        """)

        await db.commit()


async def add_user_to_db(
    user_id: int,
    username: str,
    full_name: str,
    referrer_id: int = None
):
    async with connect_db() as db:
        await db.execute("BEGIN IMMEDIATE")

        try:
            joined_date = datetime.now(timezone.utc).strftime(
                "%Y-%m-%d %H:%M"
            )

            # Проверяем реферальный ID
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
                VALUES (?, ?, ?, 0, 2, ?, ?, 0, 0, 0, 0, 7, 0, 0)
                """,
                (
                    user_id,
                    username,
                    full_name,
                    joined_date,
                    valid_referrer_id
                )
            )

            is_new_user = cursor.rowcount == 1

            if is_new_user and valid_referrer_id is not None:
                await db.execute(
                    """
                    UPDATE users
                    SET invited_count = invited_count + 1
                    WHERE user_id = ?
                    """,
                    (valid_referrer_id,)
                )

            await db.commit()
            return is_new_user

        except Exception:
            await db.rollback()
            raise


async def get_user_profile(user_id: int):
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
            result = await cursor.fetchone()
            return result


async def check_user_ban(user_id: int) -> bool:
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
            