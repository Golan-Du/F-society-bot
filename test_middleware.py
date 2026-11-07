import asyncio
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from aiogram.types import Message, User, Chat

from database import db as database
import middlewares.db_check as middleware_module

# 

import inspect
import middlewares.db_check as middleware_module

print("Загружен файл:")
print(middleware_module.__file__)

print("\nЗагруженный код:")
print(inspect.getsource(middleware_module.DatabaseMiddleware))

#

async def main():
    original_db = database.DB_NAME
    original_check = middleware_module.check_user_ban

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            database.DB_NAME = str(
                Path(temp_dir) / "test_database.db"
            )

            await database.init_db()

            middleware = middleware_module.DatabaseMiddleware()
            handler = AsyncMock(return_value="OK")

            user = User.model_construct(
                id=3001,
                is_bot=False,
                first_name="Test"
            )

            event = Message.model_construct(
                message_id=1,
                date=datetime.now(timezone.utc),
                chat=Chat.model_construct(
                    id=3001,
                    type="private"
                ),
                from_user=user
            )

            print("--- Тест 1: Обычный пользователь ---")

            await database.add_user_to_db(
                3001, "normal_user", "Normal User"
            )

            with patch.object(
                Message, "answer", new_callable=AsyncMock
            ):
                result = await middleware(handler, event, {})

            assert result == "OK"
            handler.assert_awaited_once()

            print("✅ Обычный пользователь проходит")

            print("\n--- Тест 2: Заблокированный пользователь ---")

            async with database.connect_db() as db:
                await db.execute(
                    "UPDATE users SET is_banned = 1 WHERE user_id = 3001"
                )
                await db.commit()

            handler.reset_mock()

            with patch.object(
                Message, "answer", new_callable=AsyncMock
            ) as answer_mock:
                await middleware(handler, event, {})

                answer_mock.assert_awaited_once()

            handler.assert_not_awaited()

            print("✅ Заблокированный пользователь остановлен")

            print("\n--- Тест 3: Ошибка БД ---")

            middleware_module.check_user_ban = AsyncMock(
                side_effect=Exception("Test database error")
            )

            handler.reset_mock()

            with patch.object(
                Message, "answer", new_callable=AsyncMock
            ) as answer_mock:
                await middleware(handler, event, {})

                answer_mock.assert_awaited_once()

            handler.assert_not_awaited()

            print("✅ При ошибке БД пользователь не проходит")

            print("\n🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ")

        finally:
            middleware_module.check_user_ban = original_check
            database.DB_NAME = original_db


if __name__ == "__main__":
    asyncio.run(main())