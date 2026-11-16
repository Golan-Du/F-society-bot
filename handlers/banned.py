import asyncio
import html
import logging
import time

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from database.db import (
    check_user_ban,
    get_user_profile,
    get_user_ban_info,
)


logger = logging.getLogger(__name__)

router = Router(name="banned")


# =========================
# НАСТРОЙКИ ЗАЩИТЫ CALLBACK
# =========================

CALLBACK_COOLDOWN = 0.7
CALLBACK_CLEANUP_INTERVAL = 128
CALLBACK_MAX_AGE = 60

callback_cooldowns: dict[tuple[int, str], float] = {}
processing_users: set[int] = set()
user_locks: dict[int, asyncio.Lock] = {}

callback_counter = 0


# =========================
# ТЕКСТЫ
# =========================

BANNED_PROFILE_TEXT = (
    "🚫 <b>ЗАБЛОКИРОВАННЫЙ АККАУНТ</b>\n"
    "F-Society | OSINT &amp; VPN\n"
    "━━━━━━━━━━━━━━\n\n"
    "Доступ к функциям экосистемы ограничен.\n\n"
    "💰 <b>БАЛАНС</b>\n"
    "{balance} руб.\n\n"
    "🔎 <b>БЕСПЛАТНЫЕ ПОИСКИ</b>\n"
    "{free_searches}\n\n"
    "🛡 <b>VPN-ДОСТУП</b>\n"
    "{vpn_days_left} дн.\n\n"
    "👥 <b>РЕФЕРАЛЫ</b>\n"
    "{invited_count} приглашено\n"
    "━━━━━━━━━━━━━━\n\n"
    "⛔ OSINT-функции, VPN и покупки недоступны.\n\n"
    "⚠️ Оставшиеся средства, бонусы, реферальные "
    "начисления и неиспользованный VPN-доступ могут "
    "быть затронуты блокировкой согласно правилам "
    "F-Society.\n\n"
    "Если вы считаете блокировку ошибочной, "
    "обратитесь в поддержку."
)


BANNED_REASON_TEXT = (
    "📋 <b>ПРИЧИНА БЛОКИРОВКИ</b>\n"
    "━━━━━━━━━━━━━━\n\n"
    "🚫 Ваш аккаунт заблокирован.\n\n"
    "<b>Причина:</b>\n"
    "{reason}\n\n"
    "<b>Дата блокировки:</b>\n"
    "{ban_date}\n\n"
    "Если вы считаете блокировку ошибочной, "
    "обратитесь в поддержку."
)


BANNED_SUPPORT_TEXT = (
    "🆘 <b>ПОДДЕРЖКА F-SOCIETY</b>\n"
    "━━━━━━━━━━━━━━\n\n"
    "Если вы считаете блокировку ошибочной, "
    "вы можете обратиться к администрации "
    "для рассмотрения ситуации.\n\n"
    "При обращении укажите свой Telegram ID "
    "и подробно опишите проблему.\n\n"
    "🆔 Ваш ID: <code>{user_id}</code>"
)


# =========================
# КЛАВИАТУРЫ
# =========================

def get_banned_profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
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


def get_banned_reason_keyboard() -> InlineKeyboardMarkup:
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
                    text="🆘 Поддержка",
                    callback_data="banned_support",
                ),
            ],
        ]
    )


def get_banned_support_keyboard() -> InlineKeyboardMarkup:
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
                    text="Написать администрации",
                    url="https://t.me/YA_BANAN_67",
                ),
            ],
        ]
    )


# =========================
# ЗАЩИТА CALLBACK
# =========================

def check_callback_cooldown(
    callback: CallbackQuery,
) -> bool:

    global callback_counter

    user_id = callback.from_user.id
    callback_data = callback.data or ""

    current_time = time.monotonic()
    key = (user_id, callback_data)

    last_time = callback_cooldowns.get(key)

    if last_time is not None:
        if current_time - last_time < CALLBACK_COOLDOWN:
            return False

    callback_cooldowns[key] = current_time

    callback_counter += 1

    if callback_counter >= CALLBACK_CLEANUP_INTERVAL:
        expired_keys = [
            cooldown_key
            for cooldown_key, timestamp in callback_cooldowns.items()
            if current_time - timestamp > CALLBACK_MAX_AGE
        ]

        for cooldown_key in expired_keys:
            callback_cooldowns.pop(cooldown_key, None)

        callback_counter = 0

    return True


def get_user_lock(user_id: int) -> asyncio.Lock:
    lock = user_locks.get(user_id)

    if lock is None:
        lock = asyncio.Lock()
        user_locks[user_id] = lock

    return lock


# =========================
# БЕЗОПАСНЫЙ CALLBACK ANSWER
# =========================

async def safe_callback_answer(
    callback: CallbackQuery,
    text: str | None = None,
    show_alert: bool = False,
) -> None:

    try:
        await callback.answer(
            text=text,
            show_alert=show_alert,
            cache_time=0,
        )

    except TelegramBadRequest as error:
        logger.debug(
            "Callback уже обработан или устарел. "
            "User ID: %s | Error: %s",
            callback.from_user.id,
            error,
        )

    except Exception:
        logger.exception(
            "Ошибка ответа на callback. User ID: %s",
            callback.from_user.id,
        )


# =========================
# БЕЗОПАСНОЕ РЕДАКТИРОВАНИЕ
# =========================

async def safe_edit_banned_message(
    callback: CallbackQuery,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> None:

    if callback.message is None:
        await callback.bot.send_message(
            chat_id=callback.from_user.id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return

    try:
        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    except TelegramBadRequest as error:
        error_text = str(error).lower()

        if "message is not modified" in error_text:
            return

        if "message to edit not found" in error_text:
            await callback.bot.send_message(
                chat_id=callback.from_user.id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            return

        raise


# =========================
# ПРОВЕРКА АКТУАЛЬНОСТИ БАНА
# =========================

async def verify_banned_user(
    callback: CallbackQuery,
) -> bool:

    try:
        is_banned = await check_user_ban(
            callback.from_user.id
        )

    except Exception:
        logger.exception(
            "Не удалось проверить блокировку. User ID: %s",
            callback.from_user.id,
        )

        await safe_callback_answer(
            callback,
            "⚠️ Ошибка проверки аккаунта. Попробуйте позже.",
            show_alert=True,
        )

        return False

    if not is_banned:
        await safe_callback_answer(
            callback,
            "ℹ️ Ваш аккаунт больше не заблокирован.",
            show_alert=True,
        )

        return False

    return True


# =========================
# ПОЛУЧЕНИЕ ПРОФИЛЯ
# =========================

async def get_banned_profile_data(user_id: int) -> dict | None:

    profile = await get_user_profile(user_id)

    if not profile:
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
    ) = profile

    return {
        "balance": balance,
        "free_searches": free_searches,
        "invited_count": invited_count,
        "vpn_days_left": vpn_days_left,
    }


# =========================
# ОБЩАЯ ОБРАБОТКА CALLBACK
# =========================

async def process_banned_callback(
    callback: CallbackQuery,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> None:

    user_id = callback.from_user.id

    if not check_callback_cooldown(callback):
        await safe_callback_answer(
            callback,
            "⏳ Не так быстро.",
        )
        return

    lock = get_user_lock(user_id)

    if user_id in processing_users:
        await safe_callback_answer(
            callback,
            "⏳ Предыдущий запрос ещё обрабатывается.",
        )
        return

    async with lock:

        if user_id in processing_users:
            await safe_callback_answer(
                callback,
                "⏳ Предыдущий запрос ещё обрабатывается.",
            )
            return

        processing_users.add(user_id)

        try:
            await safe_callback_answer(callback)

            if not await verify_banned_user(callback):
                return

            await safe_edit_banned_message(
                callback,
                text,
                keyboard,
            )

        except Exception:
            logger.exception(
                "Ошибка обработки banned callback. "
                "User ID: %s | Callback: %s",
                user_id,
                callback.data,
            )

            await safe_callback_answer(
                callback,
                "⚠️ Не удалось выполнить действие. Попробуйте позже.",
                show_alert=True,
            )

        finally:
            processing_users.discard(user_id)


# =========================
# 👤 ПРОФИЛЬ ЗАБЛОКИРОВАННОГО
# =========================

@router.callback_query(
    lambda callback: callback.data == "banned_profile"
)
async def banned_profile(
    callback: CallbackQuery,
) -> None:

    user_id = callback.from_user.id

    if not check_callback_cooldown(callback):
        await safe_callback_answer(
            callback,
            "⏳ Не так быстро.",
        )
        return

    lock = get_user_lock(user_id)

    if user_id in processing_users:
        await safe_callback_answer(
            callback,
            "⏳ Предыдущий запрос ещё обрабатывается.",
        )
        return

    async with lock:

        if user_id in processing_users:
            await safe_callback_answer(
                callback,
                "⏳ Предыдущий запрос ещё обрабатывается.",
            )
            return

        processing_users.add(user_id)

        try:
            await safe_callback_answer(callback)

            if not await verify_banned_user(callback):
                return

            profile = await get_banned_profile_data(user_id)

            if profile is None:
                await safe_callback_answer(
                    callback,
                    "⚠️ Профиль не найден.",
                    show_alert=True,
                )
                return

            text = BANNED_PROFILE_TEXT.format(
                balance=html.escape(str(profile["balance"])),
                free_searches=html.escape(
                    str(profile["free_searches"])
                ),
                vpn_days_left=html.escape(
                    str(profile["vpn_days_left"])
                ),
                invited_count=html.escape(
                    str(profile["invited_count"])
                ),
            )

            await safe_edit_banned_message(
                callback,
                text,
                get_banned_profile_keyboard(),
            )

        except Exception:
            logger.exception(
                "Ошибка открытия заблокированного профиля. "
                "User ID: %s",
                user_id,
            )

            await safe_callback_answer(
                callback,
                "⚠️ Не удалось загрузить профиль.",
                show_alert=True,
            )

        finally:
            processing_users.discard(user_id)


# =========================
# 📋 ПРИЧИНА БЛОКИРОВКИ
# =========================

@router.callback_query(
    lambda callback: callback.data == "banned_reason"
)
async def banned_reason(
    callback: CallbackQuery,
) -> None:

    user_id = callback.from_user.id

    if not check_callback_cooldown(callback):
        await safe_callback_answer(
            callback,
            "⏳ Не так быстро.",
        )
        return

    lock = get_user_lock(user_id)

    if user_id in processing_users:
        await safe_callback_answer(
            callback,
            "⏳ Предыдущий запрос ещё обрабатывается.",
        )
        return

    async with lock:

        if user_id in processing_users:
            await safe_callback_answer(
                callback,
                "⏳ Предыдущий запрос ещё обрабатывается.",
            )
            return

        processing_users.add(user_id)

        try:
            await safe_callback_answer(callback)

            if not await verify_banned_user(callback):
                return

            ban_info = await get_user_ban_info(user_id)

            if not ban_info:
                await safe_callback_answer(
                    callback,
                    "⚠️ Информация о блокировке не найдена.",
                    show_alert=True,
                )
                return

            is_banned, reason, ban_date = ban_info

            if not is_banned:
                await safe_callback_answer(
                    callback,
                    "ℹ️ Ваш аккаунт больше не заблокирован.",
                    show_alert=True,
                )
                return

            reason = (
                html.escape(str(reason))
                if reason
                else "Причина блокировки не указана. "
                     "Обратитесь в поддержку."
            )

            ban_date = (
                html.escape(str(ban_date))
                if ban_date
                else "Не указана"
            )

            text = BANNED_REASON_TEXT.format(
                reason=reason,
                ban_date=ban_date,
            )

            await safe_edit_banned_message(
                callback,
                text,
                get_banned_reason_keyboard(),
            )

        except Exception:
            logger.exception(
                "Ошибка получения причины блокировки. "
                "User ID: %s",
                user_id,
            )

            await safe_callback_answer(
                callback,
                "⚠️ Не удалось получить информацию.",
                show_alert=True,
            )

        finally:
            processing_users.discard(user_id)


# =========================
# 🆘 ПОДДЕРЖКА
# =========================

@router.callback_query(
    lambda callback: callback.data == "banned_support"
)
async def banned_support(
    callback: CallbackQuery,
) -> None:

    user_id = callback.from_user.id

    text = BANNED_SUPPORT_TEXT.format(
        user_id=user_id,
    )

    await process_banned_callback(
        callback,
        text,
        get_banned_support_keyboard(),
    )