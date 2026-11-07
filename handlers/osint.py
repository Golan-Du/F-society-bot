import logging
import time

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from database.db import add_user_to_db


logger = logging.getLogger(__name__)
router = Router()


callback_cooldowns: dict[int, float] = {}

CALLBACK_COOLDOWN = 0.7

ADMIN_IDS = {
    6495550812,
    6326978216,
}


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


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


async def safe_edit_message(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    parse_mode: str = "HTML",
) -> None:
    if callback.message is None:
        return

    try:
        await callback.message.edit_text(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )

    except TelegramBadRequest as error:
        if "message is not modified" in str(error).lower():
            return

        raise


async def check_callback_cooldown(
    callback: CallbackQuery,
) -> bool:
    user_id = callback.from_user.id
    current_time = time.monotonic()

    last_time = callback_cooldowns.get(user_id)

    if (
        last_time is not None
        and current_time - last_time < CALLBACK_COOLDOWN
    ):
        await callback.answer()
        return False

    callback_cooldowns[user_id] = current_time

    return True


async def show_vpn_menu(
    message: Message,
) -> None:
    await message.answer(
        "🛡 <b>VPN & Безопасность</b>\n\n"
        "Раздел управления VPN находится "
        "в разработке.\n\n"
        "Позже здесь появятся доступные локации, "
        "управление подпиской и подключением.",
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
        "/unsubscribe_vpn — отписаться от VPN\n"
        "/subscribe_osint — подписаться на OSINT\n"
        "/unsubscribe_osint — отписаться от OSINT\n\n"

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


@router.message(Command("osint"))
async def cmd_osint(
    message: Message,
    state: FSMContext,
) -> None:
    await state.clear()

    await message.answer(
        "🔎 <b>OSINT-сканер</b>\n\n"
        "Раздел автоматического поиска "
        "сейчас находится в разработке.\n\n"
        "Позже здесь появится поиск и анализ "
        "данных из разрешённых открытых источников.",
        parse_mode="HTML",
        reply_markup=get_back_keyboard(),
    )


@router.message(Command("vpn"))
async def cmd_vpn(
    message: Message,
    state: FSMContext,
) -> None:
    await state.clear()
    await show_vpn_menu(message)


# =========================
# ГЛАВНОЕ МЕНЮ
# =========================

@router.callback_query(
    F.data == "back_to_main",
)
async def cb_back_to_main(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    if not await check_callback_cooldown(callback):
        return

    await callback.answer()
    await state.clear()

    await safe_edit_message(
        callback,
        (
            "🚀 <b>Главное меню F-Society</b>\n\n"
            "Выберите нужный раздел:"
        ),
        get_main_inline_keyboard(),
    )


@router.callback_query(
    F.data == "back_step",
)
async def cb_back_step(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    if not await check_callback_cooldown(callback):
        return

    await callback.answer("Возврат назад")
    await state.clear()

    await safe_edit_message(
        callback,
        (
            "🚀 <b>Главное меню F-Society</b>\n\n"
            "Выберите нужный раздел:"
        ),
        get_main_inline_keyboard(),
    )


@router.message(
    F.text == "🏠 Главное меню",
)
async def reply_main_menu(
    message: Message,
    state: FSMContext,
) -> None:
    await state.clear()

    await message.answer(
        "🏠 Вы вернулись в главное меню.",
        reply_markup=get_main_inline_keyboard(),
    )


@router.message(
    F.text == "🆘 Поддержка",
)
async def reply_support(
    message: Message,
) -> None:
    await message.answer(
        "🛠 <b>Поддержка F-Society</b>\n\n"
        "Система тикетов пока находится "
        "в разработке.",
        parse_mode="HTML",
    )


# =========================
# КТО Я
# =========================

@router.callback_query(
    F.data == "who_am_i",
)
async def cb_who_am_i(
    callback: CallbackQuery,
) -> None:
    if not await check_callback_cooldown(callback):
        return

    await callback.answer()

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


@router.callback_query(
    F.data == "who_am_i_start",
)
async def cb_who_am_i_start(
    callback: CallbackQuery,
) -> None:
    if not await check_callback_cooldown(callback):
        return

    await callback.answer()

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


# =========================
# VPN
# =========================

@router.callback_query(
    F.data == "vpn_menu",
)
async def cb_vpn(
    callback: CallbackQuery,
) -> None:
    if not await check_callback_cooldown(callback):
        return

    await callback.answer()

    await safe_edit_message(
        callback,
        (
            "🛡 <b>VPN & Безопасность</b>\n\n"
            "Раздел управления VPN находится "
            "в разработке."
        ),
        get_back_keyboard(),
    )


# =========================
# УВЕДОМЛЕНИЯ
# =========================

@router.callback_query(
    F.data == "subscriptions_menu",
)
async def cb_subscriptions(
    callback: CallbackQuery,
) -> None:
    if not await check_callback_cooldown(callback):
        return

    await callback.answer()

    await callback.message.answer(
        "🔔 <b>Уведомления F-Society</b>\n\n"
        "Доступные подписки:\n\n"
        "🛡 VPN:\n"
        "/subscribe_vpn — подписаться\n"
        "/unsubscribe_vpn — отписаться\n\n"
        "🔎 OSINT:\n"
        "/subscribe_osint — подписаться\n"
        "/unsubscribe_osint — отписаться",
        parse_mode="HTML",
    )


# =========================
# ВРЕМЕННАЯ КОМАНДА ФАЙЛА
# =========================

@router.message(Command("file"))
async def send_file(
    message: Message,
) -> None:
    try:
        file = FSInputFile(
            "files/example.txt",
        )

        await message.answer_document(file)

    except Exception:
        logger.exception(
            "Ошибка отправки файла",
        )

        await message.answer(
            "⚠️ Файл примера временно недоступен."
        )
        