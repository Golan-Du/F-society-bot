import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from handlers import get_combined_router
from database.db import init_db
from middlewares.db_check import DatabaseMiddleware


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)

logger = logging.getLogger(__name__)


async def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "Не указан BOT_TOKEN в файле config.py"
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

        logger.info("F-Society OSINT Bot запущен!")

        await dp.start_polling(bot)

    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        logger.info("Бот остановлен.")
        