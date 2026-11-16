import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from database.db import check_user_ban


logger = logging.getLogger(__name__)


# =========================
# РАЗРЕШЁННЫЕ CALLBACK
# =========================

BANNED_ALLOWED_CALLBACKS = frozenset({
    "banned_profile",
    "banned_reason",
    "banned_support",
})


# =========================
# ТЕКСТ ЗАБЛОКИРОВАННОГО МЕНЮ
# =========================

BANNED_MENU_TEXT = (
    "🚫 Ваш аккаунт заблокирован "
    "в системе F-Society.\n\n"
    "⛔ Доступ ко всем функциям бота ограничен."
)


# =========================
# КЛАВИАТУРА ЗАБЛОКИРОВАННОГО МЕНЮ
# =========================

def get_banned_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👤 Мой профиль",
                    callback_data="banned_profile",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📋 Причина блокировки",
                    callback_data="banned_reason",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🆘 Поддержка",
                    callback_data="banned_support",
                ),
            ],
        ],
    )


# =========================
# DATABASE MIDDLEWARE
# =========================

class DatabaseMiddleware(BaseMiddleware):

    async def __call__(
        self,
        handler: Callable[[Any, dict], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: dict,
    ) -> Any:

        user = event.from_user

        if user is None:
            return await handler(event, data)

        try:
            is_banned = await check_user_ban(user.id)

        except Exception:
            logger.exception(
                "Ошибка проверки блокировки. User ID: %s",
                user.id,
            )

            await self.send_alert(
                event,
                "⚠️ Временная ошибка системы. Попробуйте позже.",
            )

            return None

        if not is_banned:
            return await handler(event, data)

        # =========================
        # ЗАБЛОКИРОВАННЫЙ CALLBACK
        # =========================

        if isinstance(event, CallbackQuery):

            callback_data = event.data or ""

            if callback_data in BANNED_ALLOWED_CALLBACKS:
                return await handler(event, data)

            logger.info(
                "Заблокированный пользователь попытался "
                "выполнить запрещённый callback. "
                "User ID: %s | Callback: %s",
                user.id,
                callback_data,
            )

            await self.show_banned_menu(event)

            return None

        # =========================
        # ЗАБЛОКИРОВАННОЕ СООБЩЕНИЕ
        # =========================

        if isinstance(event, Message):

            logger.info(
                "Заблокированный пользователь отправил сообщение. "
                "User ID: %s",
                user.id,
            )

            await self.show_banned_menu(event)

            return None

        return None

    # =========================
    # ПОКАЗ ЗАБЛОКИРОВАННОГО МЕНЮ
    # =========================

    @staticmethod
    async def show_banned_menu(
        event: Message | CallbackQuery,
    ) -> None:

        keyboard = get_banned_keyboard()

        try:
            if isinstance(event, CallbackQuery):

                # Закрываем индикатор загрузки callback.
                await event.answer(
                    "🚫 Доступ ограничен.",
                    show_alert=True,
                    cache_time=0,
                )

                if event.message is None:
                    await event.bot.send_message(
                        chat_id=event.from_user.id,
                        text=BANNED_MENU_TEXT,
                        reply_markup=keyboard,
                    )
                    return

                try:
                    await event.message.edit_text(
                        text=BANNED_MENU_TEXT,
                        reply_markup=keyboard,
                    )

                except TelegramBadRequest as error:
                    error_text = str(error).lower()

                    if "message is not modified" in error_text:
                        return

                    if "message to edit not found" in error_text:
                        await event.bot.send_message(
                            chat_id=event.from_user.id,
                            text=BANNED_MENU_TEXT,
                            reply_markup=keyboard,
                        )
                        return

                    raise

            elif isinstance(event, Message):

                await event.answer(
                    text=BANNED_MENU_TEXT,
                    reply_markup=keyboard,
                )

        except Exception:
            logger.exception(
                "Не удалось показать меню заблокированного "
                "пользователя. User ID: %s",
                event.from_user.id if event.from_user else None,
            )

    # =========================
    # УВЕДОМЛЕНИЕ ОБ ОШИБКЕ
    # =========================

    @staticmethod
    async def send_alert(
        event: Message | CallbackQuery,
        text: str,
    ) -> None:

        try:
            if isinstance(event, CallbackQuery):
                await event.answer(
                    text,
                    show_alert=True,
                    cache_time=0,
                )

            elif isinstance(event, Message):
                await event.answer(text)

        except Exception:
            logger.exception(
                "Не удалось отправить уведомление пользователю.",
            )            