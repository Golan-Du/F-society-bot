import logging
from datetime import datetime
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)


logger = logging.getLogger(__name__)


def format_timestamp(timestamp: str) -> str:
    try:
        parsed = datetime.strptime(
            timestamp,
            "%Y-%m-%d %H:%M:%S",
        )

        return parsed.strftime(
            "%d.%m.%Y %H:%M:%S"
        ) + " МСК"

    except (ValueError, TypeError):
        return escape(str(timestamp))


def get_banned_notification_keyboard() -> InlineKeyboardMarkup:
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
        ]
    )


async def send_ban_notification(
    bot: Bot,
    event: dict,
) -> bool:
    status = event.get("status")
    user_id = event.get("user_id")
    reason = event.get("reason")
    timestamp = event.get("timestamp")

    safe_reason = (
        escape(str(reason))
        if reason
        else "Не указана"
    )

    safe_timestamp = format_timestamp(timestamp)

    keyboard = None

    if status == "banned":
        text = (
            "🚫 <b>ЗАБЛОКИРОВАННЫЙ АККАУНТ</b>\n"
            "F-Society | OSINT &amp; VPN\n"
            "━━━━━━━━━━━━━━\n\n"
            "Доступ к функциям экосистемы ограничен.\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"📋 Причина: {safe_reason}\n"
            f"🕒 Дата: {safe_timestamp}\n\n"
            "Если считаете блокировку ошибочной, "
            "обратитесь в поддержку."
        )

        keyboard = get_banned_notification_keyboard()

    elif status == "unbanned":
        text = (
            "✅ <b>ВАШ АККАУНТ РАЗБЛОКИРОВАН</b>\n"
            "━━━━━━━━━━━━━━\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"📋 Причина разблокировки: {safe_reason}\n"
            f"🕒 Дата: {safe_timestamp}\n\n"
            "Доступ к функциям F-Society восстановлен."
        )

    else:
        logger.error(
            "Неизвестный тип уведомления о блокировке: %s",
            status,
        )
        return False

    try:
        await bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

        logger.info(
            "Уведомление %s отправлено пользователю %s",
            status,
            user_id,
        )

        return True

    except TelegramAPIError:
        logger.exception(
            "Telegram не доставил уведомление %s пользователю %s",
            status,
            user_id,
        )
        return False

    except Exception:
        logger.exception(
            "Неожиданная ошибка уведомления пользователя %s",
            user_id,
        )
        return False