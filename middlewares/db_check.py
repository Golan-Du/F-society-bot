import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

from database.db import check_user_ban


logger = logging.getLogger(__name__)


class DatabaseMiddleware(BaseMiddleware):

    async def __call__(
        self,
        handler: Callable[[Any, dict], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: dict
    ) -> Any:

        user = event.from_user

        if user is None:
            return await handler(event, data)

        # Проверка блокировки пользователя
        try:
            is_banned = await check_user_ban(user.id)

        except Exception:
            logger.exception(
                "Ошибка проверки блокировки. User ID: %s",
                user.id
            )

            await self.send_alert(
                event,
                "⚠️ Временная ошибка системы. Попробуйте позже."
            )

            return None

        # Остановка заблокированного пользователя
        if is_banned:
            logger.info(
                "Заблокированный пользователь попытался выполнить действие. User ID: %s",
                user.id
            )

            await self.send_alert(
                event,
                "⚠️ Ваш аккаунт заблокирован в системе F-Society."
            )

            return None

        # Передача события дальше
        return await handler(event, data)

    @staticmethod
    async def send_alert(
        event: Message | CallbackQuery,
        text: str
    ) -> None:

        try:
            if isinstance(event, CallbackQuery):
                await event.answer(
                    text,
                    show_alert=True,
                    cache_time=0
                )

            elif isinstance(event, Message):
                await event.answer(text)

        except Exception:
            logger.exception(
                "Не удалось отправить уведомление пользователю."
            )