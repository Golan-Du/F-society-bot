import logging
import time

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    Message,
)

from .keyboards import (
    get_result_keyboard,
    get_search_type_keyboard,
)
from .scan import start_scan
from .states import OsintSearchState
from .timer import (
    cancel_search_timer,
    finish_search_timer,
    start_search_timer,
)
from .validation import (
    validate_phone,
    validate_telegram_id,
    validate_username,
)


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


# =========================
# КНОПКИ ОТМЕНЫ ПОИСКА
# =========================

CANCEL_BUTTONS = {
    "🏠 Главное меню",
    "👤 Профиль",
    "🆘 Поддержка",
}


# =========================
# БЕЗОПАСНЫЙ ОТВЕТ CALLBACK
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
            return False

        logger.exception(
            "Ошибка ответа на callback"
        )

        raise


# =========================
# БЕЗОПАСНОЕ РЕДАКТИРОВАНИЕ
# =========================

async def safe_edit_message(
    callback: CallbackQuery,
    text: str,
    reply_markup=None,
    parse_mode: str = "HTML",
) -> bool:

    if not isinstance(callback.message, Message):
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


# =========================
# ПРОВЕРКА COOLDOWN
# =========================

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
# ЗАВЕРШЕНИЕ ОЖИДАНИЯ ПОИСКА
# =========================

async def complete_search_input(
    message: Message,
    state: FSMContext,
) -> bool:

    user = message.from_user

    if user is None:
        return False

    finished = await finish_search_timer(
        user_id=user.id,
        state=state,
    )

    if not finished:
        await message.answer(
            "⌛ Время ожидания истекло. "
            "Выберите формат поиска заново."
        )

        return False

    return True


# =========================
# ЗАПУСК ВЫБОРА ТИПА ПОИСКА
# =========================

async def begin_search(
    callback: CallbackQuery,
    state: FSMContext,
    search_state,
) -> None:

    if not await check_callback_cooldown(callback):
        return

    await safe_callback_answer(callback)

    if not isinstance(callback.message, Message):
        return

    await start_search_timer(
        message=callback.message,
        state=state,
        user_id=callback.from_user.id,
        search_state=search_state,
    )


# =========================
# OSINT МЕНЮ
# =========================

@router.message(Command("osint"))
async def cmd_osint(
    message: Message,
    state: FSMContext,
) -> None:

    user = message.from_user

    if user is not None:
        await cancel_search_timer(user.id)

    await state.clear()

    await message.answer(
        (
            "🔎 <b>OSINT-сканер</b>\n\n"
            "Выберите формат поиска:"
        ),
        parse_mode="HTML",
        reply_markup=get_search_type_keyboard(),
    )


@router.callback_query(F.data == "osint_scan")
async def cb_osint_scan(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:

    if not await check_callback_cooldown(callback):
        return

    await safe_callback_answer(callback)

    await cancel_search_timer(callback.from_user.id)
    await state.clear()

    await safe_edit_message(
        callback=callback,
        text=(
            "🔎 <b>OSINT-сканер</b>\n\n"
            "Выберите, по какому формату "
            "выполнить поиск:"
        ),
        reply_markup=get_search_type_keyboard(),
    )


# =========================
# ВЫБОР ТИПА ПОИСКА
# =========================

@router.callback_query(F.data == "osint_phone")
async def cb_osint_phone(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:

    await begin_search(
        callback=callback,
        state=state,
        search_state=OsintSearchState.waiting_for_phone,
    )


@router.callback_query(F.data == "osint_username")
async def cb_osint_username(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:

    await begin_search(
        callback=callback,
        state=state,
        search_state=OsintSearchState.waiting_for_username,
    )


@router.callback_query(F.data == "osint_telegram_id")
async def cb_osint_telegram_id(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:

    await begin_search(
        callback=callback,
        state=state,
        search_state=OsintSearchState.waiting_for_telegram_id,
    )


# =========================
# НЕ ТЕКСТ ВО ВРЕМЯ ПОИСКА
# =========================

@router.message(
    StateFilter(
        OsintSearchState.waiting_for_phone,
        OsintSearchState.waiting_for_username,
        OsintSearchState.waiting_for_telegram_id,
    ),
    ~F.text,
)
async def invalid_search_content(
    message: Message,
) -> None:

    await message.answer(
        (
            "⚠️ Неверный формат.\n\n"
            "Отправьте поисковый запрос "
            "обычным текстовым сообщением."
        )
    )


# =========================
# ОТМЕНА ПОИСКА
# =========================

@router.message(
    Command("cancel"),
    StateFilter(
        OsintSearchState.waiting_for_phone,
        OsintSearchState.waiting_for_username,
        OsintSearchState.waiting_for_telegram_id,
    ),
)
async def cancel_search(
    message: Message,
    state: FSMContext,
) -> None:

    user = message.from_user

    if user is not None:
        await cancel_search_timer(user.id)

    await state.clear()

    await message.answer(
        (
            "🚫 <b>Поиск отменён</b>\n\n"
            "Выберите формат нового поиска:"
        ),
        parse_mode="HTML",
        reply_markup=get_search_type_keyboard(),
    )


# =========================
# ОБРАБОТКА НОМЕРА
# =========================

@router.message(
    OsintSearchState.waiting_for_phone,
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(CANCEL_BUTTONS),
)
async def process_phone(
    message: Message,
    state: FSMContext,
) -> None:

    is_valid, result = validate_phone(
        message.text,
    )

    if not is_valid:
        await message.answer(result)
        return

    if not await complete_search_input(message, state):
        return

    await start_scan(
        message=message,
        search_type="📱 Номер",
        search_value=f"+{result}",
    )


# =========================
# ОБРАБОТКА USERNAME
# =========================

@router.message(
    OsintSearchState.waiting_for_username,
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(CANCEL_BUTTONS),
)
async def process_username(
    message: Message,
    state: FSMContext,
) -> None:

    is_valid, result = validate_username(
        message.text,
    )

    if not is_valid:
        await message.answer(result)
        return

    if not await complete_search_input(message, state):
        return

    await start_scan(
        message=message,
        search_type="👤 Username",
        search_value=f"@{result}",
    )


# =========================
# ОБРАБОТКА TELEGRAM ID
# =========================

@router.message(
    OsintSearchState.waiting_for_telegram_id,
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(CANCEL_BUTTONS),
)
async def process_telegram_id(
    message: Message,
    state: FSMContext,
) -> None:

    is_valid, result = validate_telegram_id(
        message.text,
    )

    if not is_valid:
        await message.answer(result)
        return

    if not await complete_search_input(message, state):
        return

    await start_scan(
        message=message,
        search_type="🆔 Telegram ID",
        search_value=result,
    )


# =========================
# ПОВТОРИТЬ ПОИСК
# =========================

@router.callback_query(F.data == "osint_repeat")
async def cb_osint_repeat(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:

    if not await check_callback_cooldown(callback):
        return

    await safe_callback_answer(callback)

    await cancel_search_timer(callback.from_user.id)
    await state.clear()

    await safe_edit_message(
        callback=callback,
        text=(
            "🔎 <b>OSINT-сканер</b>\n\n"
            "Выберите формат нового поиска:"
        ),
        reply_markup=get_search_type_keyboard(),
    )