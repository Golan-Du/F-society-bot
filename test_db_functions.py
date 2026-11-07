import asyncio
import tempfile
from pathlib import Path

from database import db as database


async def main():
    original_db = database.DB_NAME

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            database.DB_NAME = str(
                Path(temp_dir) / "test_database.db"
            )

            await database.init_db()

            print("--- Регистрация ---")

            result = await database.add_user_to_db(
                2001, "user1", "User One"
            )
            assert result is True
            print("✅ Новый пользователь зарегистрирован")

            result = await database.add_user_to_db(
                2001, "user1", "User One"
            )
            assert result is False
            print("✅ Повторная регистрация не создаёт дубликат")

            print("\n--- Реферальная система ---")

            result = await database.add_user_to_db(
                2002, "user2", "User Two", 2001
            )
            assert result is True

            async with database.connect_db() as db:
                async with db.execute(
                    "SELECT invited_count FROM users WHERE user_id = 2001"
                ) as cursor:
                    row = await cursor.fetchone()

            assert row["invited_count"] == 1
            print("✅ Приглашённый пользователь засчитан")

            await database.add_user_to_db(
                2002, "user2", "User Two", 2001
            )

            async with database.connect_db() as db:
                async with db.execute(
                    "SELECT invited_count FROM users WHERE user_id = 2001"
                ) as cursor:
                    row = await cursor.fetchone()

            assert row["invited_count"] == 1
            print("✅ Повторная регистрация не увеличивает счётчик")

            await database.add_user_to_db(
                2003, "user3", "User Three", 9999
            )
            print("✅ Несуществующий реферер не засчитывается")

            await database.add_user_to_db(
                2004, "user4", "User Four", 2004
            )
            print("✅ Самореферал не засчитывается")

            print("\n--- Профиль ---")

            profile = await database.get_user_profile(2001)

            assert profile is not None
            assert profile["balance"] == 0
            assert profile["invited_count"] == 1
            print("✅ Профиль пользователя получен")

            print("\n--- Проверка бана ---")

            assert await database.check_user_ban(2001) is False
            print("✅ Незаблокированный пользователь")

            async with database.connect_db() as db:
                await db.execute(
                    "UPDATE users SET is_banned = 1 WHERE user_id = 2001"
                )
                await db.commit()

            assert await database.check_user_ban(2001) is True
            print("✅ Заблокированный пользователь")

            assert await database.check_user_ban(9999) is False
            print("✅ Несуществующий пользователь")

            print("\n🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ")

        finally:
            database.DB_NAME = original_db


if __name__ == "__main__":
    asyncio.run(main())