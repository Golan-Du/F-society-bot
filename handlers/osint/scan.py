import asyncio
import html
import logging
import random

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from database.db import check_user_ban

from .keyboards import get_result_keyboard


logger = logging.getLogger(__name__)


# =========================
# АКТИВНЫЕ СКАНИРОВАНИЯ
# =========================

active_scan_tasks: dict[int, asyncio.Task] = {}
_scan_locks: dict[int, asyncio.Lock] = {}


def get_scan_lock(user_id: int) -> asyncio.Lock:
    if user_id not in _scan_locks:
        _scan_locks[user_id] = asyncio.Lock()

    return _scan_locks[user_id]


async def is_user_banned(user_id: int) -> bool:
    """
    Проверяет блокировку.
    При ошибке БД запрещает отправку результата.
    """

    try:
        return await check_user_ban(user_id)

    except Exception:
        logger.exception(
            "Не удалось проверить блокировку перед отправкой OSINT. "
            "user_id=%s",
            user_id,
        )
        return True


async def cancel_active_scan(user_id: int) -> bool:
    """Отменяет активное сканирование пользователя."""

    lock = get_scan_lock(user_id)

    async with lock:
        task = active_scan_tasks.get(user_id)

        if task is None:
            return False

        if task.done():
            active_scan_tasks.pop(user_id, None)
            return False

        task.cancel()

        await asyncio.gather(
            task,
            return_exceptions=True,
        )

        if active_scan_tasks.get(user_id) is task:
            active_scan_tasks.pop(user_id, None)

        logger.info(
            "OSINT-сканирование отменено. user_id=%s",
            user_id,
        )

        return True


async def start_scan(
    message: Message,
    search_type: str,
    search_value: str,
) -> None:
    """Запускает сканирование как отдельную управляемую задачу."""

    user = message.from_user

    if user is None:
        return

    user_id = user.id
    lock = get_scan_lock(user_id)

    async with lock:
        previous_task = active_scan_tasks.get(user_id)

        if previous_task is not None and not previous_task.done():
            previous_task.cancel()

            await asyncio.gather(
                previous_task,
                return_exceptions=True,
            )

        if active_scan_tasks.get(user_id) is previous_task:
            active_scan_tasks.pop(user_id, None)

        task = asyncio.create_task(
            run_scan(
                message=message,
                search_type=search_type,
                search_value=search_value,
            )
        )

        active_scan_tasks[user_id] = task


# =========================
# БЕЗОПАСНОЕ РЕДАКТИРОВАНИЕ
# =========================

async def safe_edit_message(
    message: Message,
    text: str,
    reply_markup=None,
) -> bool:

    try:
        await message.edit_text(
            text,
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
            "Ошибка редактирования сообщения OSINT"
        )

        raise


# =========================
# ФОРМИРОВАНИЕ РЕЗУЛЬТАТА
# =========================

def get_search_result_text(
    search_type: str,
    search_value: str,
    record_found: bool,
) -> str:

    if record_found:
        status = "🟢 Данные обнаружены"
        sources = random.randint(1, 5)
        matches = random.randint(1, 3)

        details = (
            "📥 Найденные данные временно "
            "имитируются."
        )

    else:
        status = "🟡 Данные не обнаружены"
        sources = random.randint(3, 8)
        matches = 0

        details = (
            "🌐 Открытые источники проверены.\n"
            "Совпадений пока не найдено."
        )

    return (
        "🔎 <b>OSINT-сканер</b>\n\n"
        f"{html.escape(search_type)}: "
        f"<code>{html.escape(search_value)}</code>\n\n"
        "📊 <b>Результат анализа</b>\n\n"
        f"🗂 <b>Статус:</b> {status}\n"
        f"🔍 <b>Проверено источников:</b> {sources}\n"
        f"🧩 <b>Совпадений:</b> {matches}\n\n"
        "━━━━━━━━━━━━\n"
        f"{details}\n\n"
        "⚙️ <i>Реальные источники будут "
        "подключены позже.</i>"
    )


# =========================
# ВЫПОЛНЕНИЕ ПОИСКА
# =========================

async def run_scan(
    message: Message,
    search_type: str,
    search_value: str,
) -> None:

    user = message.from_user

    if user is None:
        return

    user_id = user.id

    safe_search_type = html.escape(search_type)
    safe_search_value = html.escape(search_value)

    progress_message = None

    def get_progress_text(status: str) -> str:
        return (
            "🔎 <b>OSINT-сканер</b>\n\n"
            f"{safe_search_type}: "
            f"<code>{safe_search_value}</code>\n\n"
            f"{status}"
        )

    async def update_progress(
        status: str,
        delay: float,
    ) -> bool:

        await asyncio.sleep(delay)

        return await safe_edit_message(
            progress_message,
            get_progress_text(status),
        )

    try:
        # Не запускаем поиск для уже заблокированного пользователя.
        if await is_user_banned(user_id):
            return

        progress_message = await message.answer(
            (
                "🔎 <b>OSINT-сканер</b>\n\n"
                f"{safe_search_type}: "
                f"<code>{safe_search_value}</code>\n\n"
                "📡 Подключение к источникам •"
            ),
            parse_mode="HTML",
        )

        updated = await update_progress(
            "🗄 Проверка базы данных ••",
            0.8,
        )

        if not updated:
            return

        await asyncio.sleep(1.2)

        record_found = random.choice([True, False])

        if record_found:
            updated = await safe_edit_message(
                progress_message,
                get_progress_text(
                    "📥 Получение данных •••"
                ),
            )

            if not updated:
                return

            await asyncio.sleep(1.5)

        else:
            updated = await safe_edit_message(
                progress_message,
                get_progress_text(
                    "🌐 Поиск по открытым источникам •••"
                ),
            )

            if not updated:
                return

            await asyncio.sleep(2.0)

        updated = await safe_edit_message(
            progress_message,
            get_progress_text(
                "🧩 Анализ совпадений ••••"
            ),
        )

        if not updated:
            return

        await asyncio.sleep(1.0)

        # Повторная проверка непосредственно перед результатом.
        if await is_user_banned(user_id):
            return

        await safe_edit_message(
            progress_message,
            get_search_result_text(
                search_type=search_type,
                search_value=search_value,
                record_found=record_found,
            ),
            reply_markup=get_result_keyboard(),
        )

    except asyncio.CancelledError:
        logger.info(
            "OSINT-поиск отменён. user_id=%s",
            user_id,
        )
        raise

    except Exception:
        logger.exception(
            "Ошибка выполнения OSINT-поиска. user_id=%s",
            user_id,
        )

        if progress_message is not None:
            try:
                # При блокировке или ошибке проверки
                # не отправляем пользователю сообщение об ошибке.
                if await is_user_banned(user_id):
                    return

                await safe_edit_message(
                    progress_message,
                    (
                        "⚠️ Во время обработки запроса "
                        "произошла ошибка."
                    ),
                    reply_markup=get_result_keyboard(),
                )

            except Exception:
                logger.exception(
                    "Не удалось отправить сообщение об ошибке OSINT. "
                    "user_id=%s",
                    user_id,
                )

    finally:
        current_task = asyncio.current_task()

        if active_scan_tasks.get(user_id) is current_task:
            active_scan_tasks.pop(user_id, None)