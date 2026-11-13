import asyncio
import time
import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from database.db import (
    FREE_SEARCHES_LIMIT,
    get_user_profile,
)


logger = logging.getLogger(__name__)
router = Router()

# =========================
# COOLDOWN CALLBACK-КНОПОК
# =========================

callback_cooldowns: dict[tuple[int, str], float] = {}
CALLBACK_COOLDOWN = 0.7

processing_profiles = set()

bot_username_cache = None
bot_username_lock = asyncio.Lock()


# =========================
# БЕЗОПАСНЫЕ ДАННЫЕ
# =========================

def get_safe_number(
    value,
    default: int = 0,
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
    default: str = "Неизвестно",
) -> str:
    if value is None:
        return default

    value = str(value).strip()

    if not value:
        return default

    return escape(value)


def get_ban_status(
    is_banned,
) -> str:
    if bool(is_banned):
        return "🚫 Заблокирован"

    return "✅ Активен"


# =========================
# КЛАВИАТУРЫ ПРОФИЛЯ
# =========================

def get_profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💰 Баланс и покупки",
                    callback_data="profile_balance",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔎 Поиски",
                    callback_data="profile_searches",
                ),
                InlineKeyboardButton(
                    text="🛡 VPN",
                    callback_data="profile_vpn",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👥 Рефералы",
                    callback_data="profile_referrals",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Главное меню",
                    callback_data="back_to_main",
                ),
            ],
        ],
    )


def get_profile_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ К профилю",
                    callback_data="profile_main",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Главное меню",
                    callback_data="back_to_main",
                ),
            ],
        ],
    )


# =========================
# ЗАЩИТА ОТ ПОВТОРНОЙ ЗАГРУЗКИ
# =========================

async def start_profile_processing(
    message: Message,
) -> bool:
    user_id = message.from_user.id

    if user_id in processing_profiles:
        await message.answer(
            "⏳ Подождите, профиль ещё загружается...",
        )
        return False

    processing_profiles.add(user_id)
    return True


def finish_profile_processing(
    message: Message,
) -> None:
    processing_profiles.discard(
        message.from_user.id,
    )


# =========================
# ДАННЫЕ БОТА
# =========================

async def get_bot_username(
    bot: Bot,
) -> str:
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
                "Не удалось получить username бота",
            )

        bot_username_cache = bot_username
        return bot_username_cache


# =========================
# ПОЛУЧЕНИЕ ДАННЫХ ПРОФИЛЯ
# =========================

async def get_profile_data(
    user_id: int,
) -> dict | None:
    user_data = await get_user_profile(user_id)

    if user_data is None:
        return None

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
        is_banned,
    ) = user_data

    return {
        "balance": get_safe_number(balance),
        "free_searches": get_safe_number(free_searches),
        "joined_date": get_safe_text(joined_date),
        "invited_count": get_safe_number(invited_count),
        "cases_opened": get_safe_number(cases_opened),
        "items_bought": get_safe_number(items_bought),
        "items_spent_total": get_safe_number(
            items_spent_total,
        ),
        "vpn_days_left": get_safe_number(vpn_days_left),
        "vpn_days_bought": get_safe_number(
            vpn_days_bought,
        ),
        "ban_status": get_ban_status(is_banned),
    }


# =========================
# ТЕКСТ ГЛАВНОГО ПРОФИЛЯ
# =========================

def build_profile_main_text(
    user_id: int,
    profile: dict,
) -> str:
    return (
        "👤 <b>Твой профиль F-Society</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"📌 Статус: <b>{profile['ban_status']}</b>\n\n"
        f"💰 Баланс: <b>{profile['balance']} руб.</b>\n"
        f"🔎 Поиски: "
        f"<b>{profile['free_searches']}/"
        f"{FREE_SEARCHES_LIMIT}</b>\n"
        f"🛡 VPN: "
        f"<b>{profile['vpn_days_left']} дн.</b>\n"
        f"👥 Приглашено: "
        f"<b>{profile['invited_count']}</b>\n\n"
        "Выберите раздел ниже:"
    )


# =========================
# ОТКРЫТИЕ ГЛАВНОГО ПРОФИЛЯ
# =========================

async def show_profile(
    message: Message,
    user_id: int,
) -> None:
    profile = await get_profile_data(user_id)

    if profile is None:
        await message.answer(
            "⚠️ Профиль не найден. "
            "Пропишите /start",
        )
        return

    profile_text = build_profile_main_text(
        user_id,
        profile,
    )

    await message.answer(
        profile_text,
        parse_mode="HTML",
        reply_markup=get_profile_keyboard(),
    )


# =========================
# ОТКРЫТИЕ ПРОФИЛЯ
# =========================

@router.message(Command("profile"))
@router.message(F.text == "👤 Профиль")
async def reply_profile(
    message: Message,
) -> None:
    if not await start_profile_processing(message):
        return

    user_id = message.from_user.id

    try:
        await show_profile(
            message,
            user_id,
        )

    except Exception:
        logger.exception(
            "Ошибка получения профиля пользователя %s",
            user_id,
        )

        await message.answer(
            "⚠️ Ошибка загрузки профиля с сервера.",
        )

    finally:
        finish_profile_processing(message)


# =========================
# БЕЗОПАСНЫЙ CALLBACK ANSWER
# =========================

async def safe_callback_answer(
    callback: CallbackQuery,
    text: str | None = None,
    show_alert: bool = False,
) -> bool:
    try:
        await callback.answer(
            text=text,
            show_alert=show_alert,
        )

        return True

    except TelegramBadRequest as error:
        error_text = str(error).lower()

        ignored_errors = (
            "query is too old",
            "query id is invalid",
            "response timeout expired",
        )

        if any(
            ignored_error in error_text
            for ignored_error in ignored_errors
        ):
            logger.warning(
                "Пропущен устаревший callback: %s",
                callback.data,
            )
            return False

        logger.exception(
            "Ошибка ответа на callback",
        )
        return False


# =========================
# БЕЗОПАСНОЕ РЕДАКТИРОВАНИЕ
# =========================

async def safe_edit_profile_message(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup,
) -> bool:
    if callback.message is None:
        return False

    try:
        await callback.message.edit_text(
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

        return True

    except TelegramBadRequest as error:
        error_text = str(error).lower()

        ignored_errors = (
            "message is not modified",
            "message to edit not found",
        )

        if any(
            ignored_error in error_text
            for ignored_error in ignored_errors
        ):
            return False

        logger.exception(
            "Ошибка редактирования сообщения",
        )
        raise


# =========================
# ПРОВЕРКА COOLDOWN
# =========================

async def check_callback_cooldown(
    callback: CallbackQuery,
) -> bool:
    user_id = callback.from_user.id
    callback_data = callback.data or ""

    current_time = time.monotonic()

    cooldown_key = (
        user_id,
        callback_data,
    )

    last_time = callback_cooldowns.get(
        cooldown_key,
    )

    if (
        last_time is not None
        and current_time - last_time < CALLBACK_COOLDOWN
    ):
        await safe_callback_answer(callback)
        return False

    callback_cooldowns[cooldown_key] = current_time
    return True


# =========================
# ВОЗВРАТ К ГЛАВНОМУ ПРОФИЛЮ
# =========================

@router.callback_query(F.data == "profile_main")
async def callback_profile_main(
    callback: CallbackQuery,
) -> None:
    if not await check_callback_cooldown(callback):
        return

    if not await safe_callback_answer(callback):
        return

    user_id = callback.from_user.id

    try:
        profile = await get_profile_data(user_id)

        if profile is None:
            await safe_edit_profile_message(
                callback,
                "⚠️ Профиль не найден. Пропишите /start",
                get_profile_back_keyboard(),
            )
            return

        profile_text = build_profile_main_text(
            user_id,
            profile,
        )

        await safe_edit_profile_message(
            callback,
            profile_text,
            get_profile_keyboard(),
        )

    except Exception:
        logger.exception(
            "Ошибка возврата к профилю %s",
            user_id,
        )


# =========================
# БАЛАНС И ПОКУПКИ
# =========================

@router.callback_query(F.data == "profile_balance")
async def callback_profile_balance(
    callback: CallbackQuery,
) -> None:
    if not await check_callback_cooldown(callback):
        return

    if not await safe_callback_answer(callback):
        return

    user_id = callback.from_user.id

    try:
        profile = await get_profile_data(user_id)

        if profile is None:
            return

        text = (
            "💰 <b>Баланс и покупки</b>\n\n"
            f"💳 Текущий баланс: "
            f"<b>{profile['balance']} руб.</b>\n\n"
            f"📦 Куплено вещей: "
            f"<b>{profile['items_bought']} шт.</b>\n"
            f"💸 Потрачено всего: "
            f"<b>{profile['items_spent_total']} руб.</b>\n"
            f"🎁 Открыто кейсов: "
            f"<b>{profile['cases_opened']}</b>"
        )

        await safe_edit_profile_message(
            callback,
            text,
            get_profile_back_keyboard(),
        )

    except Exception:
        logger.exception(
            "Ошибка загрузки баланса пользователя %s",
            user_id,
        )


# =========================
# ПОИСКИ
# =========================

@router.callback_query(F.data == "profile_searches")
async def callback_profile_searches(
    callback: CallbackQuery,
) -> None:
    if not await check_callback_cooldown(callback):
        return

    if not await safe_callback_answer(callback):
        return

    user_id = callback.from_user.id

    try:
        profile = await get_profile_data(user_id)

        if profile is None:
            return

        text = (
            "🔎 <b>Поиски</b>\n\n"
            "🎁 Бесплатные поиски:\n"
            f"<b>{profile['free_searches']}/"
            f"{FREE_SEARCHES_LIMIT}</b>\n\n"
            "Используйте доступные попытки "
            "для работы с открытыми источниками."
        )

        await safe_edit_profile_message(
            callback,
            text,
            get_profile_back_keyboard(),
        )

    except Exception:
        logger.exception(
            "Ошибка загрузки поисков пользователя %s",
            user_id,
        )


# =========================
# VPN
# =========================

@router.callback_query(F.data == "profile_vpn")
async def callback_profile_vpn(
    callback: CallbackQuery,
) -> None:
    if not await check_callback_cooldown(callback):
        return

    if not await safe_callback_answer(callback):
        return

    user_id = callback.from_user.id

    try:
        profile = await get_profile_data(user_id)

        if profile is None:
            return

        text = (
            "🛡 <b>VPN & Безопасность</b>\n\n"
            f"📅 Осталось VPN: "
            f"<b>{profile['vpn_days_left']} дн.</b>\n"
            f"➕ Куплено дней: "
            f"<b>{profile['vpn_days_bought']} дн.</b>\n\n"
            "Управление VPN будет доступно "
            "в этом разделе."
        )

        await safe_edit_profile_message(
            callback,
            text,
            get_profile_back_keyboard(),
        )

    except Exception:
        logger.exception(
            "Ошибка загрузки VPN пользователя %s",
            user_id,
        )


# =========================
# РЕФЕРАЛЫ
# =========================

@router.callback_query(F.data == "profile_referrals")
async def callback_profile_referrals(
    callback: CallbackQuery,
    bot: Bot,
) -> None:
    if not await check_callback_cooldown(callback):
        return

    if not await safe_callback_answer(callback):
        return

    user_id = callback.from_user.id

    try:
        profile = await get_profile_data(user_id)

        if profile is None:
            return

        bot_username = await get_bot_username(bot)

        referral_link = (
            f"https://t.me/{bot_username}?start={user_id}"
        )

        text = (
            "👥 <b>Реферальная система</b>\n\n"
            f"🎯 Приглашено друзей: "
            f"<b>{profile['invited_count']}</b>\n\n"
            "🔗 <b>Ваша реферальная ссылка:</b>\n"
            f"<code>{escape(referral_link)}</code>\n\n"
            "Приглашайте друзей и получайте "
            "награды за активность."
        )

        await safe_edit_profile_message(
            callback,
            text,
            get_profile_back_keyboard(),
        )

    except Exception:
        logger.exception(
            "Ошибка загрузки рефералов пользователя %s",
            user_id,
        )