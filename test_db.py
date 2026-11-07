import asyncio
import tempfile
from pathlib import Path

from database import db as database


async def expect_rejection(name, query, params=()):
    try:
        async with database.connect_db() as db:
            await db.execute(query, params)

        print(f"❌ ПРОВАЛ: {name} — запрос прошёл")

    except Exception as error:
        if "constraint" in str(error).lower():
            print(f"✅ ПРОЙДЕНО: {name}")
        else:
            print(f"⚠️ ОШИБКА: {name} — {error}")


async def main():
    original_db = database.DB_NAME

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            database.DB_NAME = str(
                Path(temp_dir) / "test_database.db"
            )

            print("Создаём тестовую базу...")

            await database.init_db()

            print("\n--- Проверка ограничений ---")

            async with database.connect_db() as db:
                await db.execute(
                    """
                    INSERT INTO users (user_id, username)
                    VALUES (1001, 'test_user')
                    """
                )
                await db.commit()

            print("✅ Тестовый пользователь создан")

            await expect_rejection(
                "Отрицательный баланс",
                """
                UPDATE users
                SET balance = -100
                WHERE user_id = 1001
                """
            )

            await expect_rejection(
                "Некорректный is_banned",
                """
                UPDATE users
                SET is_banned = 2
                WHERE user_id = 1001
                """
            )

            await expect_rejection(
                "Самореферал",
                """
                UPDATE users
                SET referrer_id = 1001
                WHERE user_id = 1001
                """
            )

            await expect_rejection(
                "Несуществующий реферер",
                """
                INSERT INTO users (user_id, referrer_id)
                VALUES (1002, 999999)
                """
            )

            await expect_rejection(
                "Отрицательные бесплатные поиски",
                """
                UPDATE users
                SET free_searches = -1
                WHERE user_id = 1001
                """
            )

            await expect_rejection(
                "Некорректный статус подписки",
                """
                INSERT INTO user_subscriptions (
                    user_id,
                    notification_type,
                    is_active,
                    created_at,
                    updated_at
                )
                VALUES (1001, 'test', 5, 'now', 'now')
                """
            )

            print("\n--- Проверка завершена ---")

        finally:
            database.DB_NAME = original_db


if __name__ == "__main__":
    asyncio.run(main())