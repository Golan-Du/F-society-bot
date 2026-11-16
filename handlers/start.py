import logging
import time

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from database.db import add_user_to_db
from admin_config import ADMIN_IDS
from .osint.timer import cancel_search_timer


logger = logging.getLogger(__name__)
router = Router()


# =========================
# COOLDOWN CALLBACK-КНОПОК
# =========================

callback_cooldowns: dict[tuple[int, str], float] = {}

CALLBACK_COOLDOWN = 0.7
CALLBACK_COOLDOWN_CLEANUP_INTERVAL = 128
CALLBACK_COOLDOWN_MAX_AGE = 60.0

_callback_check_counter = 0


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# =========================
# ОЧИСТКА СОСТОЯНИЯ ПОЛЬЗОВАТЕЛЯ
# =========================

async def clear_user_state(
    state: FSMContext,
    user_id: int,
) -> None:
    await cancel_search_timer(user_id)
    await state.clear()


# =========================
# КЛАВИАТУРЫ
# =========================

def get_main_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔎 OSINT-сканер",
                    callback_data="osint_scan",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧠 Кто я?",
                    callback_data="who_am_i",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🛡 VPN & Безопасность",
                    callback_data="vpn_menu",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔔 Уведомления",
                    callback_data="subscriptions_menu",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📄 Правила и Политика",
                    url=(
                        "https://telegra.ph/"
                        "Pravila-ispolzovaniya-01-01"
                    ),
                )
            ],
        ]
    )


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🏠 Главное меню"),
                KeyboardButton(text="👤 Профиль"),
            ],
            [
                KeyboardButton(text="🆘 Поддержка"),
            ],
        ],
        resize_keyboard=True,
    )


def get_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back_to_main",
                )
            ]
        ]
    )


def get_who_am_i_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔍 Начать проверку",
                    callback_data="who_am_i_start",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back_to_main",
                )
            ],
        ]
    )


def get_support_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚠️ Проблема",
                    callback_data="support_problem",
                ),
                InlineKeyboardButton(
                    text="💡 Предложение",
                    callback_data="support_suggestion",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💬 Отзыв",
                    callback_data="support_review",
                ),
                InlineKeyboardButton(
                    text="❓ Вопрос",
                    callback_data="support_question",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back_to_main",
                )
            ],
        ]
    )


# =========================
# БЕЗОПАСНЫЙ CALLBACK ANSWER
# =========================

async def safe_callback_answer(
    callback: CallbackQuery,
    text: str | None = None,
) -> bool:
    try:
        await callback.answer(text=text)
        return True

    except TelegramBadRequest as error:
        error_text = str(error).lower()

        if (
            "query is too old" in error_text
            or "query id is invalid" in error_text
            or "response timeout expired" in error_text
        ):
            logger.warning(
                "Пропущен устаревший callback: %s",
                callback.data,
            )
            return False

        logger.exception(
            "Ошибка ответа на callback"
        )
        return False


# =========================
# БЕЗОПАСНОЕ РЕДАКТИРОВАНИЕ
# =========================

async def safe_edit_message(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    parse_mode: str = "HTML",
) -> bool:
    if callback.message is None:
        return False

    try:
        await callback.message.edit_text(
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )

        return True

    except TelegramBadRequest as error:
        error_text = str(error).lower()

        if "message is not modified" in error_text:
            return True

        if "message to edit not found" in error_text:
            return False

        logger.exception(
            "Ошибка редактирования сообщения"
        )
        raise


# =========================
# ОЧИСТКА COOLDOWN
# =========================

def cleanup_callback_cooldowns(
    current_time: float,
) -> None:
    expired_keys = [
        key
        for key, last_time in callback_cooldowns.items()
        if current_time - last_time > CALLBACK_COOLDOWN_MAX_AGE
    ]

    for key in expired_keys:
        callback_cooldowns.pop(key, None)


async def check_callback_cooldown(
    callback: CallbackQuery,
) -> bool:
    global _callback_check_counter

    user_id = callback.from_user.id
    callback_data = callback.data or ""

    current_time = time.monotonic()

    _callback_check_counter += 1

    if (
        _callback_check_counter
        >= CALLBACK_COOLDOWN_CLEANUP_INTERVAL
    ):
        cleanup_callback_cooldowns(current_time)
        _callback_check_counter = 0

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
# ТЕКСТЫ РАЗДЕЛОВ
# =========================

def get_main_menu_text() -> str:
    return (
        "🕶 <b>F-Society</b>\n"
        "<i>OSINT & VPN ecosystem</i>\n"
        "━━━━━━━━━━━━\n\n"
        "Выберите нужный раздел:"
    )


def get_vpn_menu_text() -> str:
    return (
        "🛡 <b>VPN & Безопасность</b>\n\n"
        "Раздел готовится к запуску.\n\n"
        "Здесь появятся управление подпиской,\n"
        "выбор локации и подключение к VPN.\n\n"
        "━━━━━━━━━━━━\n"
        "🔒 F-Society Security"
    )


# =========================
# VPN
# =========================

async def show_vpn_menu(
    message: Message,
) -> None:
    await message.answer(
        get_vpn_menu_text(),
        parse_mode="HTML",
        reply_markup=get_back_keyboard(),
    )


# =========================
# ОСНОВНЫЕ КОМАНДЫ
# =========================

@router.message(Command("start"))
async def cmd_start(
    message: Message,
    state: FSMContext,
) -> None:
    user = message.from_user

    if user is None:
        return

    await clear_user_state(
        state,
        user.id,
    )

    referrer_id = None

    parts = (
        message.text.split(maxsplit=1)
        if message.text
        else []
    )

    if len(parts) == 2:
        referral_arg = parts[1].strip()

        if referral_arg.isdecimal():
            candidate_id = int(referral_arg)

            if (
                candidate_id > 0
                and candidate_id != user.id
            ):
                referrer_id = candidate_id

    try:
        await add_user_to_db(
            user_id=user.id,
            username=user.username or "No username",
            full_name=user.full_name,
            referrer_id=referrer_id,
        )

    except Exception:
        logger.exception(
            "Ошибка регистрации пользователя %s",
            user.id,
        )

        await message.answer(
            "⚠️ Не удалось зарегистрировать аккаунт. "
            "Попробуйте позже."
        )
        return

    welcome_text = (
        "🕶 <b>F-Society</b>\n"
        "<i>OSINT & VPN ecosystem</i>\n"
        "━━━━━━━━━━━━\n\n"
        "Инструменты для работы с открытыми "
        "источниками и цифровой безопасности.\n\n"
        "🎁 <b>Стартовый бонус:</b> "
        "7 дней бесплатного VPN.\n\n"
        "🔎 OSINT — анализ открытых источников\n"
        "🛡 VPN — защита цифрового соединения"
    )

    await message.answer(
        welcome_text,
        parse_mode="HTML",
        reply_markup=get_main_inline_keyboard(),
    )

    await message.answer(
        "👇 Выберите действие:",
        reply_markup=get_main_reply_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(
    message: Message,
) -> None:
    help_text = (
        "📚 <b>F-Society — справка</b>\n"
        "━━━━━━━━━━━━\n\n"

        "<b>Основные команды</b>\n"
        "/start — главное меню\n"
        "/help — справка\n"
        "/profile — мой профиль\n"
        "/osint — OSINT-сканер\n"
        "/vpn — VPN-раздел\n\n"

        "<b>Уведомления</b>\n"
        "/subscribe — управление подписками\n"
        "/subscribe_vpn — подписка на VPN\n"
        "/unsubscribe_vpn — отписка от VPN\n"
        "/subscribe_osint — подписка на OSINT\n"
        "/unsubscribe_osint — отписка от OSINT\n\n"

        "<b>Другое</b>\n"
        "/cancel — отменить действие\n\n"

        "<b>Разделы F-Society</b>\n"
        "🔎 OSINT — поиск и анализ открытых источников.\n"
        "🛡 VPN — управление VPN-сервисом.\n"
        "👤 Профиль — информация об аккаунте.\n"
        "🔔 Уведомления — новости сервисов.\n"
        "🆘 Поддержка — помощь пользователям."
    )

    user = message.from_user

    if user is not None and is_admin(user.id):
        help_text += (
            "\n\n━━━━━━━━━━━━\n"
            "<b>🔐 Администрирование</b>\n"
            "/subscribers — статистика подписчиков\n"
            "/broadcast — отправка рассылки\n"
            "/banned — список заблокированных\n"
            "/ban USER_ID — блокировка пользователя\n"
            "/unban USER_ID — разблокировка пользователя"
        )

    await message.answer(
        help_text,
        parse_mode="HTML",
        reply_markup=get_main_inline_keyboard(),
    )


@router.message(Command("cancel"))
async def cancel_form(
    message: Message,
    state: FSMContext,
) -> None:
    user = message.from_user

    if user is None:
        return

    await clear_user_state(
        state,
        user.id,
    )

    await message.answer(
        "❌ Действие отменено.",
        reply_markup=get_main_inline_keyboard(),
    )


@router.message(Command("vpn"))
async def cmd_vpn(
    message: Message,
    state: FSMContext,
) -> None:
    user = message.from_user

    if user is None:
        return

    await clear_user_state(
        state,
        user.id,
    )

    await show_vpn_menu(message)


# =========================
# КНОПКИ ГЛАВНОГО МЕНЮ
# =========================

@router.callback_query(F.data == "back_to_main")
async def cb_back_to_main(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    if not await check_callback_cooldown(callback):
        return

    if not await safe_callback_answer(callback):
        return

    await clear_user_state(
        state,
        callback.from_user.id,
    )

    await safe_edit_message(
        callback,
        get_main_menu_text(),
        get_main_inline_keyboard(),
    )


@router.callback_query(F.data == "back_step")
async def cb_back_step(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    if not await check_callback_cooldown(callback):
        return

    if not await safe_callback_answer(
        callback,
        "Возврат назад",
    ):
        return

    await clear_user_state(
        state,
        callback.from_user.id,
    )

    await safe_edit_message(
        callback,
        get_main_menu_text(),
        get_main_inline_keyboard(),
    )


@router.callback_query(F.data == "who_am_i")
async def cb_who_am_i(
    callback: CallbackQuery,
) -> None:
    if not await check_callback_cooldown(callback):
        return

    if not await safe_callback_answer(callback):
        return

    who_am_i_text = (
        "🧠 <b>Кто я? — проверка цифрового следа</b>\n\n"
        "Проверьте, какая публичная информация "
        "о вас может быть доступна "
        "в открытых источниках.\n\n"
        "🔎 <b>Что проверяет аудит:</b>\n"
        "• публичные упоминания и профили;\n"
        "• возможные связанные аккаунты;\n"
        "• открытые источники цифрового следа.\n\n"
        "ℹ️ Используйте раздел только для проверки "
        "собственных данных и законных задач."
    )

    await safe_edit_message(
        callback,
        who_am_i_text,
        get_who_am_i_keyboard(),
    )


@router.callback_query(F.data == "who_am_i_start")
async def cb_who_am_i_start(
    callback: CallbackQuery,
) -> None:
    if not await check_callback_cooldown(callback):
        return

    if not await safe_callback_answer(callback):
        return

    await safe_edit_message(
        callback,
        (
            "🔍 <b>Проверка цифрового следа</b>\n\n"
            "Модуль автоматического аудита "
            "пока находится в разработке.\n\n"
            "После подключения движка здесь появится "
            "проверка публичных источников."
        ),
        get_who_am_i_keyboard(),
    )


@router.callback_query(F.data == "vpn_menu")
async def cb_vpn(
    callback: CallbackQuery,
) -> None:
    if not await check_callback_cooldown(callback):
        return

    if not await safe_callback_answer(callback):
        return

    await safe_edit_message(
        callback,
        get_vpn_menu_text(),
        get_back_keyboard(),
    )


@router.callback_query(F.data == "subscriptions_menu")
async def cb_subscriptions(
    callback: CallbackQuery,
) -> None:
    if not await check_callback_cooldown(callback):
        return

    if not await safe_callback_answer(callback):
        return

    await safe_edit_message(
        callback,
        (
            "🔔 <b>Уведомления F-Society</b>\n\n"
            "Доступные подписки:\n\n"
            "🛡 <b>VPN:</b>\n"
            "/subscribe_vpn — подписаться\n"
            "/unsubscribe_vpn — отписаться\n\n"
            "🔎 <b>OSINT:</b>\n"
            "/subscribe_osint — подписаться\n"
            "/unsubscribe_osint — отписаться"
        ),
        get_back_keyboard(),
    )


# =========================
# ПОДДЕРЖКА
# =========================

@router.callback_query(F.data == "support_problem")
async def cb_support_problem(
    callback: CallbackQuery,
) -> None:
    if not await check_callback_cooldown(callback):
        return

    if not await safe_callback_answer(callback):
        return

    await safe_edit_message(
        callback,
        (
            "⚠️ <b>Сообщить о проблеме</b>\n\n"
            "Система тикетов пока находится "
            "в разработке.\n\n"
            "Пока вы можете обратиться напрямую:\n\n"
            "👉 @YA_BANAN_67"
        ),
        get_support_keyboard(),
    )


@router.callback_query(F.data == "support_suggestion")
async def cb_support_suggestion(
    callback: CallbackQuery,
) -> None:
    if not await check_callback_cooldown(callback):
        return

    if not await safe_callback_answer(callback):
        return

    await safe_edit_message(
        callback,
        (
            "💡 <b>Предложение или улучшение</b>\n\n"
            "Мы всегда открыты к новым идеям.\n\n"
            "Система тикетов пока находится "
            "в разработке.\n\n"
            "Пока вы можете написать напрямую:\n\n"
            "👉 @YA_BANAN_67"
        ),
        get_support_keyboard(),
    )


@router.callback_query(F.data == "support_review")
async def cb_support_review(
    callback: CallbackQuery,
) -> None:
    if not await check_callback_cooldown(callback):
        return

    if not await safe_callback_answer(callback):
        return

    await safe_edit_message(
        callback,
        (
            "💬 <b>Отзыв о F-Society</b>\n\n"
            "Ваше мнение помогает улучшать проект.\n\n"
            "Система тикетов пока находится "
            "в разработке.\n\n"
            "Пока вы можете оставить отзыв напрямую:\n\n"
            "👉 @YA_BANAN_67"
        ),
        get_support_keyboard(),
    )


@router.callback_query(F.data == "support_question")
async def cb_support_question(
    callback: CallbackQuery,
) -> None:
    if not await check_callback_cooldown(callback):
        return

    if not await safe_callback_answer(callback):
        return

    await safe_edit_message(
        callback,
        (
            "❓ <b>Вопрос</b>\n\n"
            "Если у вас есть вопрос по работе F-Society, "
            "мы постараемся помочь.\n\n"
            "Система тикетов пока находится "
            "в разработке.\n\n"
            "Пока вы можете написать напрямую:\n\n"
            "👉 @YA_BANAN_67"
        ),
        get_support_keyboard(),
    )


# =========================
# REPLY-КНОПКИ
# =========================

@router.message(F.text == "🏠 Главное меню")
async def reply_main_menu(
    message: Message,
    state: FSMContext,
) -> None:
    user = message.from_user

    if user is None:
        return

    await clear_user_state(
        state,
        user.id,
    )

    await message.answer(
        get_main_menu_text(),
        parse_mode="HTML",
        reply_markup=get_main_inline_keyboard(),
    )


@router.message(F.text == "🆘 Поддержка")
async def reply_support(
    message: Message,
    state: FSMContext,
) -> None:
    user = message.from_user

    if user is None:
        return

    await clear_user_state(
        state,
        user.id,
    )

    await message.answer(
        (
            "🛠 <b>Поддержка F-Society</b>\n\n"
            "Выберите, с чем вы хотите обратиться:"
        ),
        parse_mode="HTML",
        reply_markup=get_support_keyboard(),
    )