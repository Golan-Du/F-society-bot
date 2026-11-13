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


SEARCH_STATES = {
    OsintSearchState.waiting_for_phone.state,
    OsintSearchState.waiting_for_username.state,
    OsintSearchState.waiting_for_telegram_id.state,
}


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


async def cancel_search_timer(
    user_id: int,
    delete_message: bool = True,
) -> None:

    task = search_timer_tasks.pop(
        user_id,
        None,
    )

    current_task = asyncio.current_task()

    if (
        task is not None
        and task is not current_task
        and not task.done()
    ):
        task.cancel()

        try:
            await task

        except asyncio.CancelledError:
            pass

        except Exception:
            logger.exception(
                "Ошибка остановки таймера"
            )

    timer_message = search_timer_messages.pop(
        user_id,
        None,
    )

    if timer_message is None or not delete_message:
        return

    try:
        await timer_message.delete()

    except TelegramBadRequest:
        pass

    except Exception:
        logger.exception(
            "Ошибка удаления сообщения таймера"
        )


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

    await cancel_search_timer(user_id)

    timer_message = await message.answer(
        get_timer_interface(
            remaining=SEARCH_INPUT_TIMEOUT,
            animation_step=0,
        ),
        parse_mode="HTML",
        reply_markup=get_back_keyboard(),
    )

    search_timer_messages[user_id] = timer_message

    async def timer() -> None:

        loop = asyncio.get_running_loop()

        deadline = loop.time() + SEARCH_INPUT_TIMEOUT
        animation_step = 0

        try:
            while True:

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
                    math.ceil(deadline - loop.time()),
                )

                if remaining <= 0:
                    await state.clear()

                    if (
                        search_timer_messages.get(user_id)
                        is timer_message
                    ):
                        search_timer_messages.pop(
                            user_id,
                            None,
                        )

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

                animation_step += 1

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
                    math.ceil(deadline - loop.time()),
                )

                if remaining <= 0:
                    continue

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
            current_task = asyncio.current_task()

            if (
                search_timer_tasks.get(user_id)
                is current_task
            ):
                search_timer_tasks.pop(
                    user_id,
                    None,
                )

    task = asyncio.create_task(timer())

    search_timer_tasks[user_id] = task