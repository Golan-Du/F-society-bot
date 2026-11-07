import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError
)

from repositories.subscription_repository import (
    get_subscribers
)


logger = logging.getLogger(__name__)


async def send_notification(
    bot: Bot,
    notification_type: str,
    text: str
) -> dict:

    subscribers = await get_subscribers(
        notification_type
    )

    sent = 0
    failed = 0

    for user_id in subscribers:
        try:
            await bot.send_message(
                chat_id=user_id,
                text=text
            )

            sent += 1

            await asyncio.sleep(0.05)

        except TelegramForbiddenError:
            logger.warning(
                "Пользователь %s заблокировал бота.",
                user_id
            )

            failed += 1

        except TelegramAPIError:
            logger.exception(
                "Ошибка Telegram API для %s",
                user_id
            )

            failed += 1

        except Exception:
            logger.exception(
                "Неожиданная ошибка для %s",
                user_id
            )

            failed += 1

    return {
        "total": len(subscribers),
        "sent": sent,
        "failed": failed
    }
        