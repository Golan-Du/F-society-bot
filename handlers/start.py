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


logger = logging.getLogger(__name__)
router = Router()


# =========================
# COOLDOWN CALLBACK-КНОПОК
# =========================

callback_cooldowns: dict[tuple[int, str], float] = {}
CALLBACK_COOLDOWN = 0.7


# =========================
# АДМИНИСТРАТОРЫ
# =========================

ADMIN_IDS = {
    6495550812,
    6326978216,
}


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


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
            "Ошибка редактирования сообщения"
        )
        raise


# =========================
# COOLDOWN
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
# VPN
# =========================

async def show_vpn_menu(
    message: Message,
) -> None:
    await message.answer(
        (
            "🛡 <b>VPN & Безопасность</b>\n\n"
            "Раздел управления VPN находится "
            "в разработке.\n\n"
            "Позже здесь появятся доступные локации, "
            "управление подпиской и подключением."
        ),
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

    await state.clear()

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
        "🚀 <b>Добро пожаловать в F-Society</b>\n\n"
        "OSINT & VPN ecosystem\n\n"
        "🎁 На старте предусмотрено "
        "7 дней бесплатного VPN.\n\n"
        "🔎 Работа с открытыми источниками\n"
        "⚡ Быстрый поиск и сбор данных\n"
        "🛡 Защита цифрового следа"
    )

    await message.answer(
        welcome_text,
        parse_mode="HTML",
        reply_markup=get_main_inline_keyboard(),
    )

    await message.answer(
        "👇 Нижнее меню для быстрого доступа:",
        reply_markup=get_main_reply_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(
    message: Message,
) -> None:
    help_text = (
        "📚 <b>F-Society — справка</b>\n\n"
        "<b>Основные команды:</b>\n"
        "/start — запуск бота и главное меню\n"
        "/help — эта справка\n"
        "/profile — просмотр профиля\n"
        "/osint — открыть OSINT-раздел\n"
        "/vpn — открыть VPN-раздел\n\n"
        "<b>Уведомления:</b>\n"
        "/subscribe — управление подписками\n"
        "/subscribe_vpn — подписаться на VPN\n"
        "/unsubscribe_vpn — отписаться\n"
        "/subscribe_osint — подписаться на OSINT\n"
        "/unsubscribe_osint — отписаться\n\n"
        "<b>Другое:</b>\n"
        "/cancel — отменить текущее действие\n\n"
        "<b>Разделы бота:</b>\n"
        "🔎 OSINT — поиск и анализ открытых источников.\n"
        "🛡 VPN — управление сервисом VPN.\n"
        "👤 Профиль — информация об аккаунте.\n"
        "🔔 Уведомления — подписки на новости сервисов.\n"
        "🆘 Поддержка — помощь пользователям."
    )

    user = message.from_user

    if user is not None and is_admin(user.id):
        help_text += (
            "\n\n<b>🔐 Админ-команды:</b>\n"
            "/subscribers — статистика подписчиков\n"
            "/broadcast — отправить рассылку\n"
            "/banned — список заблокированных\n"
            "/ban USER_ID — заблокировать пользователя\n"
            "/unban USER_ID — разблокировать пользователя"
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
    await state.clear()

    await message.answer(
        "❌ Действие отменено.",
        reply_markup=get_main_inline_keyboard(),
    )


@router.message(Command("vpn"))
async def cmd_vpn(
    message: Message,
    state: FSMContext,
) -> None:
    await state.clear()

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

    await state.clear()

    await safe_edit_message(
        callback,
        (
            "🚀 <b>Главное меню F-Society</b>\n\n"
            "Выберите нужный раздел:"
        ),
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

    await state.clear()

    await safe_edit_message(
        callback,
        (
            "🚀 <b>Главное меню F-Society</b>\n\n"
            "Выберите нужный раздел:"
        ),
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
        (
            "🛡 <b>VPN & Безопасность</b>\n\n"
            "Раздел управления VPN находится "
            "в разработке."
        ),
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
    await state.clear()

    await message.answer(
        "🏠 Вы вернулись в главное меню.",
        reply_markup=get_main_inline_keyboard(),
    )


@router.message(F.text == "🆘 Поддержка")
async def reply_support(
    message: Message,
    state: FSMContext,
) -> None:
    await state.clear()

    await message.answer(
        (
            "🛠 <b>Поддержка F-Society</b>\n\n"
            "Выберите, с чем вы хотите обратиться:"
        ),
        parse_mode="HTML",
        reply_markup=get_support_keyboard(),
    )