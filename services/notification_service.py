import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

from repositories.subscription_repository import (
    get_subscribers,
    unsubscribe_user,
)

logger = logging.getLogger(__name__)


async def send_notification(
    bot: Bot,
    notification_type: str,
    text: str,
) -> dict:
    subscribers = await get_subscribers(
        notification_type
    )

    sent = 0
    failed = 0

    for user_id in subscribers:
        delivered = False

        for attempt in range(3):
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=text,
                )

                delivered = True
                break

            except TelegramRetryAfter as error:
                if attempt == 2:
                    logger.warning(
                        "Превышено число повторов "
                        "отправки пользователю %s",
                        user_id,
                    )
                    break

                wait_time = error.retry_after + 0.1

                logger.warning(
                    "Telegram ограничил отправку. "
                    "Ожидание %.2f сек. User: %s",
                    wait_time,
                    user_id,
                )

                await asyncio.sleep(wait_time)

            except TelegramForbiddenError:
                logger.warning(
                    "Пользователь %s заблокировал бота. "
                    "Отключаем подписку %s.",
                    user_id,
                    notification_type,
                )

                try:
                    await unsubscribe_user(
                        user_id,
                        notification_type,
                    )
                except Exception:
                    logger.exception(
                        "Не удалось отключить подписку "
                        "пользователя %s",
                        user_id,
                    )

                break

            except TelegramAPIError:
                logger.exception(
                    "Ошибка Telegram API "
                    "для пользователя %s",
                    user_id,
                )
                break

            except Exception:
                logger.exception(
                    "Неожиданная ошибка отправки "
                    "пользователю %s",
                    user_id,
                )
                break

        if delivered:
            sent += 1
            await asyncio.sleep(0.05)
        else:
            failed += 1

    return {
        "total": len(subscribers),
        "sent": sent,
        "failed": failed,
    }