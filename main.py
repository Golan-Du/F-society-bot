import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from handlers import get_combined_router
from database.db import init_db
from middlewares.db_check import DatabaseMiddleware


BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)

logger = logging.getLogger(__name__)


async def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "Не задан BOT_TOKEN. Добавьте его в Railway Variables "
            "или в переменные окружения локального запуска."
        )

    bot = Bot(token=BOT_TOKEN)

    try:
        storage = MemoryStorage()
        dp = Dispatcher(storage=storage)

        dp.message.middleware(DatabaseMiddleware())
        dp.callback_query.middleware(DatabaseMiddleware())

        await init_db()
        logger.info("База данных успешно инициализирована.")

        dp.include_router(get_combined_router())

        logger.info("F-Society OSINT Bot запускается...")

        await dp.start_polling(bot)

    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        logger.info("Бот остановлен.")        