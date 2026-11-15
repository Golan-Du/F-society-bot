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


def get_user_lock(user_id: int) -> asyncio.Lock:
    lock = _user_locks.get(user_id)

    if lock is None:
        lock = asyncio.Lock()
        _user_locks[user_id] = lock

    return lock


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

        if (
            "message is not modified" in error_text
            or "message to edit not found" in error_text
        ):
            return False

        logger.exception(
            "Ошибка редактирования таймера"
        )
        raise


async def wait_timer_task(
    task: asyncio.Task | None,
) -> None:

    if (
        task is None
        or task is asyncio.current_task()
    ):
        return

    try:
        await task

    except asyncio.CancelledError:
        pass

    except Exception:
        logger.exception(
            "Ошибка ожидания завершения таймера"
        )


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


async def finish_search_timer(
    user_id: int,
    state: FSMContext,
) -> bool:
    """
    Завершает ожидание поискового запроса.

    Возвращает False, если:
    - время истекло;
    - задача таймера отсутствует;
    - задача уже завершилась;
    - пользователь больше не находится в состоянии поиска.
    """

    lock = get_user_lock(user_id)

    task = None
    timer_message = None
    accepted = False

    async with lock:
        current_state = await state.get_state()

        if current_state not in SEARCH_STATES:
            return False

        task = search_timer_tasks.get(user_id)

        deadline = search_timer_deadlines.get(user_id)

        if (
            task is None
            or task.done()
            or deadline is None
        ):
            return False

        loop = asyncio.get_running_loop()

        if loop.time() >= deadline:
            accepted = False

        else:
            accepted = True

        search_timer_tasks.pop(
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

        if not task.done():
            task.cancel()

        await state.clear()

    await wait_timer_task(task)

    await delete_timer_message(timer_message)

    return accepted


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


async def start_search_timer(
    message: Message,
    state: FSMContext,
    user_id: int,
) -> None:

    lock = get_user_lock(user_id)

    old_task = None
    old_message = None

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

    await wait_timer_task(old_task)
    await delete_timer_message(old_message)

    async with lock:
        current_state = await state.get_state()

        if current_state not in SEARCH_STATES:
            return

        timer_message = await message.answer(
            get_timer_interface(
                remaining=SEARCH_INPUT_TIMEOUT,
                animation_step=0,
            ),
            parse_mode="HTML",
            reply_markup=get_back_keyboard(),
        )

        loop = asyncio.get_running_loop()

        deadline = (
            loop.time() + SEARCH_INPUT_TIMEOUT
        )

        search_timer_messages[user_id] = timer_message
        search_timer_deadlines[user_id] = deadline

        async def timer() -> None:

            animation_step = 0
            timed_out = False

            try:
                while True:
                    remaining = max(
                        0,
                        math.ceil(
                            deadline - loop.time()
                        ),
                    )

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

                            timed_out = True

                            await safe_timer_edit(
                                timer_message,
                                (
                                    "⌛ <b>Время ожидания истекло</b>\n\n"
                                    "Поисковый запрос не был получен.\n\n"
                                    "Выберите формат поиска заново."
                                ),
                                get_search_type_keyboard(),
                            )

                        return

                    await asyncio.sleep(
                        min(
                            SEARCH_TIMER_UPDATE_INTERVAL,
                            remaining,
                        )
                    )

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
                            return

            except asyncio.CancelledError:
                raise

            except Exception:
                logger.exception(
                    "Ошибка таймера ожидания поиска"
                )

            finally:
                async with lock:
                    is_current_task = (
                        search_timer_tasks.get(user_id)
                        is asyncio.current_task()
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

                    is_current_message = (
                        search_timer_messages.get(user_id)
                        is timer_message
                    )

                    if is_current_message:
                        search_timer_messages.pop(
                            user_id,
                            None,
                        )

                if not timed_out and is_current_message:
                    await delete_timer_message(timer_message)

        task = asyncio.create_task(timer())

        search_timer_tasks[user_id] = task