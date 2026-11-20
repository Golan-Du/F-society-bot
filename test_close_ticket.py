import asyncio
import tempfile
from pathlib import Path
from contextlib import asynccontextmanager

import aiosqlite

import repositories.support_repository as support_repo


TEST_ADMIN_ID = next(iter(support_repo.ADMIN_IDS))
TEST_USER_ID = 999999999


async def main():
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test_support.db"

        @asynccontextmanager
        async def test_connect_db():
            db = await aiosqlite.connect(db_path)
            db.row_factory = aiosqlite.Row

            try:
                await db.execute("PRAGMA foreign_keys = ON")
                yield db
            finally:
                await db.close()

        support_repo.connect_db = test_connect_db

        async with test_connect_db() as db:
            await db.executescript("""
                CREATE TABLE users (
                    user_id INTEGER PRIMARY KEY
                );

                CREATE TABLE support_tickets (
                    ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    closed_at TEXT,
                    assigned_admin_id INTEGER,
                    FOREIGN KEY (user_id)
                        REFERENCES users(user_id)
                );

                INSERT INTO users (user_id)
                VALUES (999999999);

                INSERT INTO support_tickets (
                    user_id, status, created_at,
                    updated_at, assigned_admin_id
                )
                VALUES (
                    999999999, 'open',
                    '2026-11-17 10:00:00',
                    '2026-11-17 10:00:00',
                    6326978216
                );

                INSERT INTO support_tickets (
                    user_id, status, created_at,
                    updated_at, assigned_admin_id
                )
                VALUES (
                    999999999, 'open',
                    '2026-11-18 00:00:00',
                    '2026-11-18 00:00:00',
                    6326978216
                );
            """)
            await db.commit()

        ticket_id = 1
        second_ticket_id = 2

        result = await support_repo.close_ticket(
            ticket_id,
            TEST_ADMIN_ID,
        )
        print("Закрытие:", result)

        async with test_connect_db() as db:
            async with db.execute(
                """
                SELECT status, closed_at
                FROM support_tickets
                WHERE ticket_id = ?
                """,
                (ticket_id,),
            ) as cursor:
                ticket = await cursor.fetchone()

        print("Статус:", ticket["status"])
        print("Дата закрытия:", ticket["closed_at"])

        result_again = await support_repo.close_ticket(
            ticket_id,
            TEST_ADMIN_ID,
        )
        print("Повторное закрытие:", result_again)

        missing = await support_repo.close_ticket(
            999999,
            TEST_ADMIN_ID,
        )
        print("Несуществующий тикет:", missing)

        wrong_admin = next(
            admin_id
            for admin_id in support_repo.ADMIN_IDS
            if admin_id != TEST_ADMIN_ID
        )

        not_assigned = await support_repo.close_ticket(
            second_ticket_id,
            wrong_admin,
        )
        print("Чужое назначение:", not_assigned)

        forbidden = await support_repo.close_ticket(
            second_ticket_id,
            123,
        )
        print("Без прав:", forbidden)


asyncio.run(main())