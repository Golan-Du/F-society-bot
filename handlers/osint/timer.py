import asyncio
import logging
import math

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from .keyboards import (
    get_back_keyboard,
    get_search_type_keyboard,
)
from .states import OsintSearchState


logger = logging.getLogger(__name__)


SEARCH_INPUT_TIMEOUT = 180
SEARCH_TIMER_UPDATE_INTERVAL = 10

search_timer_tasks: dict[int, asyncio.Task] = {}
search_timer_messages: dict[int, Message] = {}
search_timer_deadlines: dict[int, float] = {}

_user_locks: dict[int, asyncio.Lock] = {}


SEARCH_STATES = {
    OsintSearchState.waiting_for_phone.state,
    OsintSearchState.waiting_for_username.state,
    OsintSearchState.waiting_for_telegram_id.state,
}


# =========================
# БЛОКИРОВКИ ПОЛЬЗОВАТЕЛЕЙ
# =========================

def get_user_lock(user_id: int) -> asyncio.Lock:

    lock = _user_locks.get(user_id)

    if lock is None:
        lock = asyncio.Lock()
        _user_locks[user_id] = lock

    return lock


# =========================
# БЕЗОПАСНОЕ РЕДАКТИРОВАНИЕ
# =========================

async def safe_timer_edit(
    message: Message,
    text: str,
    reply_markup=None,
) -> bool:

    try:
        await message.edit_text(
            text=text,
            parse_mode="HTML",
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
            "Ошибка редактирования таймера"
        )

        raise


# =========================
# ОЖИДАНИЕ ЗАВЕРШЕНИЯ ЗАДАЧИ
# =========================

async def wait_timer_task(
    task: asyncio.Task | None,
) -> None:

    if (
        task is None
        or task is asyncio.current_task()
    ):
        return

    try:
        await asyncio.shield(task)

    except asyncio.CancelledError:

        current_task = asyncio.current_task()

        if (
            current_task is not None
            and current_task.cancelling()
        ):
            raise

    except Exception:
        logger.exception(
            "Ошибка ожидания завершения таймера"
        )


# =========================
# УДАЛЕНИЕ СООБЩЕНИЯ
# =========================

async def delete_timer_message(
    message: Message | None,
) -> None:

    if message is None:
        return

    try:
        await message.delete()

    except TelegramBadRequest:
        pass

    except Exception:
        logger.exception(
            "Ошибка удаления сообщения таймера"
        )


# =========================
# ОТМЕНА ТАЙМЕРА
# =========================

async def cancel_search_timer(
    user_id: int,
    delete_message: bool = True,
) -> None:

    lock = get_user_lock(user_id)

    async with lock:

        task = search_timer_tasks.pop(
            user_id,
            None,
        )

        timer_message = search_timer_messages.pop(
            user_id,
            None,
        )

        search_timer_deadlines.pop(
            user_id,
            None,
        )

        if (
            task is not None
            and task is not asyncio.current_task()
            and not task.done()
        ):
            task.cancel()

    await wait_timer_task(task)

    if delete_message:
        await delete_timer_message(timer_message)


# =========================
# ЗАВЕРШЕНИЕ ОЖИДАНИЯ ПОИСКА
# =========================

async def finish_search_timer(
    user_id: int,
    state: FSMContext,
) -> bool:

    lock = get_user_lock(user_id)

    task = None
    timer_message = None

    accepted = False

    async with lock:

        current_state = await state.get_state()

        if current_state not in SEARCH_STATES:
            return False

        task = search_timer_tasks.pop(
            user_id,
            None,
        )

        timer_message = search_timer_messages.pop(
            user_id,
            None,
        )

        deadline = search_timer_deadlines.pop(
            user_id,
            None,
        )

        if (
            task is None
            or task.done()
            or deadline is None
        ):

            if (
                task is not None
                and not task.done()
                and task is not asyncio.current_task()
            ):
                task.cancel()

            await state.clear()

            accepted = False

        else:

            loop = asyncio.get_running_loop()

            accepted = loop.time() < deadline

            if not task.done():
                task.cancel()

            await state.clear()

    await wait_timer_task(task)

    await delete_timer_message(timer_message)

    return accepted


# =========================
# ИНТЕРФЕЙС ТАЙМЕРА
# =========================

def get_timer_interface(
    remaining: int,
    animation_step: int,
) -> str:

    minutes = remaining // 60
    seconds = remaining % 60

    indicators = [
        "● ○ ○ ○",
        "● ● ○ ○",
        "● ● ● ○",
        "● ● ● ●",
    ]

    indicator = indicators[
        animation_step % len(indicators)
    ]

    if remaining <= 20:

        status = (
            "⚠️ <b>Время почти вышло</b>\n\n"
            "Отправьте данные, чтобы продолжить поиск."
        )

    elif remaining <= 120:

        status = (
            "🟡 <b>Ожидание поискового запроса</b>\n\n"
            "Данные ещё не получены."
        )

    else:

        status = (
            "⏳ <b>Ожидание поискового запроса</b>\n\n"
            "Введите данные для начала поиска."
        )

    return (
        f"{status}\n\n"
        f"{indicator}\n\n"
        f"⏱ <b>Осталось:</b> "
        f"{minutes:02d}:{seconds:02d}"
    )


# =========================
# ЗАПУСК ТАЙМЕРА
# =========================

async def start_search_timer(
    message: Message,
    state: FSMContext,
    user_id: int,
    search_state,
) -> None:

    if search_state.state not in SEARCH_STATES:
        raise ValueError(
            f"Недопустимое состояние поиска: {search_state.state}"
        )

    lock = get_user_lock(user_id)

    old_task = None
    old_message = None

    try:

        async with lock:

            old_task = search_timer_tasks.pop(
                user_id,
                None,
            )

            old_message = search_timer_messages.pop(
                user_id,
                None,
            )

            search_timer_deadlines.pop(
                user_id,
                None,
            )

            if (
                old_task is not None
                and old_task is not asyncio.current_task()
                and not old_task.done()
            ):
                old_task.cancel()

            await state.set_state(search_state)

            try:

                timer_message = await message.answer(
                    get_timer_interface(
                        remaining=SEARCH_INPUT_TIMEOUT,
                        animation_step=0,
                    ),
                    parse_mode="HTML",
                    reply_markup=get_back_keyboard(),
                )

            except (Exception, asyncio.CancelledError):

                try:
                    current_state = await state.get_state()

                    if current_state == search_state.state:
                        await state.clear()

                except Exception:
                    logger.exception(
                        "Ошибка очистки FSM после запуска таймера"
                    )

                raise

            loop = asyncio.get_running_loop()

            deadline = (
                loop.time() + SEARCH_INPUT_TIMEOUT
            )

            search_timer_messages[user_id] = timer_message

            search_timer_deadlines[user_id] = deadline

            # =========================
            # ЗАДАЧА ТАЙМЕРА
            # =========================

            async def timer() -> None:

                animation_step = 0

                timed_out = False
                failed = False

                try:

                    while True:

                        remaining = max(
                            0,
                            math.ceil(
                                deadline - loop.time()
                            ),
                        )

                        # =========================
                        # ВРЕМЯ ИСТЕКЛО
                        # =========================

                        if remaining <= 0:

                            async with lock:

                                if (
                                    search_timer_tasks.get(user_id)
                                    is not asyncio.current_task()
                                ):
                                    return

                                current_state = await state.get_state()

                                if current_state not in SEARCH_STATES:
                                    return

                                await state.clear()

                                updated = await safe_timer_edit(
                                    timer_message,
                                    (
                                        "⌛ <b>Время ожидания истекло</b>\n\n"
                                        "Поисковый запрос не был получен.\n\n"
                                        "Выберите формат поиска заново."
                                    ),
                                    get_search_type_keyboard(),
                                )

                                if updated:
                                    timed_out = True
                                else:
                                    failed = True

                            return

                        # =========================
                        # ОЖИДАНИЕ ОБНОВЛЕНИЯ
                        # =========================

                        await asyncio.sleep(
                            min(
                                SEARCH_TIMER_UPDATE_INTERVAL,
                                remaining,
                            )
                        )

                        # =========================
                        # ОБНОВЛЕНИЕ ТАЙМЕРА
                        # =========================

                        async with lock:

                            if (
                                search_timer_tasks.get(user_id)
                                is not asyncio.current_task()
                            ):
                                return

                            current_state = await state.get_state()

                            if current_state not in SEARCH_STATES:
                                return

                            remaining = max(
                                0,
                                math.ceil(
                                    deadline - loop.time()
                                ),
                            )

                            if remaining <= 0:
                                continue

                            animation_step += 1

                            updated = await safe_timer_edit(
                                timer_message,
                                get_timer_interface(
                                    remaining=remaining,
                                    animation_step=animation_step,
                                ),
                                get_back_keyboard(),
                            )

                            if not updated:
                                failed = True
                                return

                except asyncio.CancelledError:
                    raise

                except Exception:

                    failed = True

                    logger.exception(
                        "Ошибка таймера ожидания поиска"
                    )

                finally:

                    async with lock:

                        is_current_task = (
                            search_timer_tasks.get(user_id)
                            is asyncio.current_task()
                        )

                        is_current_message = (
                            search_timer_messages.get(user_id)
                            is timer_message
                        )

                        if is_current_task:

                            search_timer_tasks.pop(
                                user_id,
                                None,
                            )

                            search_timer_deadlines.pop(
                                user_id,
                                None,
                            )

                            if failed:

                                try:

                                    current_state = await state.get_state()

                                    if current_state in SEARCH_STATES:
                                        await state.clear()

                                except Exception:

                                    logger.exception(
                                        "Ошибка очистки FSM после сбоя таймера"
                                    )

                        if is_current_message:

                            search_timer_messages.pop(
                                user_id,
                                None,
                            )

                    if (
                        is_current_message
                        and not timed_out
                    ):
                        await delete_timer_message(
                            timer_message
                        )

            task = asyncio.create_task(timer())

            search_timer_tasks[user_id] = task

    finally:

        # Старые ресурсы очищаются даже при ошибке
        # отправки нового сообщения или запуска таймера.

        await wait_timer_task(old_task)

        await delete_timer_message(old_message)