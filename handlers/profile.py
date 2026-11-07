import asyncio
import logging
from html import escape

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from database.db import (
    get_user_profile,
    FREE_SEARCHES_LIMIT
)


logger = logging.getLogger(__name__)
router = Router()

processing_profiles = set()

bot_username_cache = None
bot_username_lock = asyncio.Lock()


def get_safe_number(
    value,
    default: int = 0
) -> int:
    try:
        number = int(value)

        if number < 0:
            return default

        return number

    except (TypeError, ValueError):
        return default


def get_safe_text(
    value,
    default: str = "Неизвестно"
) -> str:
    if value is None:
        return default

    value = str(value).strip()

    if not value:
        return default

    return escape(value)


def get_ban_status(
    is_banned
) -> str:
    if bool(is_banned):
        return "🚫 Заблокирован"

    return "✅ Активен"


def get_profile_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏠 Главное меню",
                    callback_data="back_to_main"
                )
            ]
        ]
    )


async def start_profile_processing(
    message: Message
) -> bool:
    user_id = message.from_user.id

    if user_id in processing_profiles:
        await message.answer(
            "⏳ Подождите, профиль ещё загружается..."
        )
        return False

    processing_profiles.add(user_id)
    return True


def finish_profile_processing(
    message: Message
):
    processing_profiles.discard(
        message.from_user.id
    )


async def get_bot_username(bot: Bot) -> str:
    global bot_username_cache

    if bot_username_cache is not None:
        return bot_username_cache

    async with bot_username_lock:
        if bot_username_cache is not None:
            return bot_username_cache

        bot_info = await bot.get_me()
        bot_username = bot_info.username

        if not bot_username:
            raise RuntimeError(
                "Не удалось получить username бота"
            )

        bot_username_cache = bot_username
        return bot_username_cache


@router.message(Command("profile"))
@router.message(F.text == "👤 Профиль")
async def reply_profile(
    message: Message,
    bot: Bot
):
    if not await start_profile_processing(message):
        return

    user_id = message.from_user.id

    try:
        user_data = await get_user_profile(user_id)

        if user_data is None:
            await message.answer(
                "⚠️ Профиль не найден. Пропишите /start"
            )
            return

        (
            balance,
            free_searches,
            joined_date,
            invited_count,
            cases_opened,
            items_bought,
            items_spent_total,
            vpn_days_left,
            vpn_days_bought,
            is_banned
        ) = user_data

        balance = get_safe_number(balance)
        free_searches = get_safe_number(free_searches)
        invited_count = get_safe_number(invited_count)
        cases_opened = get_safe_number(cases_opened)
        items_bought = get_safe_number(items_bought)
        items_spent_total = get_safe_number(items_spent_total)
        vpn_days_left = get_safe_number(vpn_days_left)
        vpn_days_bought = get_safe_number(vpn_days_bought)

        joined_date = get_safe_text(joined_date)
        ban_status = get_ban_status(is_banned)

        bot_username = await get_bot_username(bot)

        referral_link = (
            f"https://t.me/{bot_username}?start={user_id}"
        )

        profile_text = (
            f"👤 <b>Твой профиль F-Society:</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"📌 Статус: <b>{ban_status}</b>\n"
            f"💰 Баланс: <b>{balance} руб.</b>\n"
            f"🔍 Бесплатные поиски: "
            f"<b>{free_searches}/{FREE_SEARCHES_LIMIT}</b>\n"
            f"📅 В системе с: "
            f"<i>{joined_date}</i>\n\n"
            f"🛡 <b>VPN Статус:</b>\n"
            f"• Осталось дней: <b>{vpn_days_left} дн.</b>\n"
            f"• Куплено дней VPN: "
            f"<b>{vpn_days_bought} дн.</b>\n\n"
            f"📦 <b>Активность & Экономика:</b>\n"
            f"• Открыто кейсов: <b>{cases_opened}</b>\n"
            f"• Куплено вещей: <b>{items_bought} шт.</b> "
            f"(на {items_spent_total} руб.)\n\n"
            f"👥 <b>Реферальная система:</b>\n"
            f"• Приглашено друзей: "
            f"<b>{invited_count}</b>\n"
            f"🔗 Твоя ссылка:\n"
            f"<code>{escape(referral_link)}</code>"
        )

        await message.answer(
            profile_text,
            parse_mode="HTML",
            reply_markup=get_profile_keyboard()
        )

    except Exception:
        logger.exception(
            "Ошибка получения профиля пользователя %s",
            user_id
        )

        await message.answer(
            "⚠️ Ошибка загрузки профиля с сервера."
        )

    finally:
        finish_profile_processing(message)
        