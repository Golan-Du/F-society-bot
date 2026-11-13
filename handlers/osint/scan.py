import asyncio
import html
import logging
import random

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from .keyboards import get_result_keyboard


logger = logging.getLogger(__name__)


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

        if (
            "message is not modified" in error_text
            or "message to edit not found" in error_text
        ):
            return False

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
# ЗАПУСК ПОИСКА
# =========================

async def run_scan(
    message: Message,
    search_type: str,
    search_value: str,
) -> None:

    safe_search_type = html.escape(search_type)
    safe_search_value = html.escape(search_value)

    progress_message = None

    def get_progress_text(
        status: str,
    ) -> str:
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

        record_found = random.choice(
            [True, False]
        )

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
        logger.debug(
            "OSINT-поиск отменён. user_id=%s",
            message.from_user.id if message.from_user else None,
        )
        raise

    except Exception:
        logger.exception(
            "Ошибка выполнения OSINT-поиска"
        )

        if progress_message is not None:
            try:
                await safe_edit_message(
                    progress_message,
                    (
                        "⚠️ Во время обработки запроса "
                        "произошла ошибка."
                    ),
                    reply_markup=get_result_keyboard(),
                )

            except TelegramBadRequest:
                logger.exception(
                    "Не удалось отправить сообщение об ошибке"
                )