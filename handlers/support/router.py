import asyncio
import logging
import time

from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from admin_config import ADMIN_IDS, CREATOR_ID

from repositories.support_repository import (
    create_support_ticket,
    get_ticket_statistics,
    get_admin_notification,
    save_admin_notification,
    deactivate_admin_notifications,
    get_all_open_tickets,
    get_admin_open_tickets,
    get_admin_closed_tickets,
    get_unassigned_tickets,
    get_closed_tickets,
    get_support_ticket,
    get_ticket_messages,
    assign_ticket_admin,
    add_ticket_message,
    update_ticket_status,
    close_ticket,
    request_ticket_transfer,
    respond_ticket_transfer,
    force_reassign_ticket,
    get_pending_ticket_transfers,
    get_ticket_transfer_request,
)

from .states import SupportState


logger = logging.getLogger(__name__)
router = Router()


# =========================
# COOLDOWN CALLBACK-КНОПОК
# =========================

callback_cooldowns: dict[tuple[int, str], float] = {}

CALLBACK_COOLDOWN = 0.7
CALLBACK_COOLDOWN_MAX_AGE = 60.0


def cleanup_callback_cooldowns(current_time: float) -> None:
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
    user_id = callback.from_user.id
    callback_data = callback.data or ""
    current_time = time.monotonic()

    cleanup_callback_cooldowns(current_time)

    cooldown_key = (user_id, callback_data)
    last_time = callback_cooldowns.get(cooldown_key)

    if (
        last_time is not None
        and current_time - last_time < CALLBACK_COOLDOWN
    ):
        await callback.answer()
        return False

    callback_cooldowns[cooldown_key] = current_time
    return True


# =========================
# УВЕДОМЛЕНИЯ АДМИНИСТРАТОРАМ
# =========================

def get_ticket_notification_text(count: int) -> str:
    last_two = count % 100
    last_digit = count % 10

    if 11 <= last_two <= 14:
        word = "тикетов"
        verb = "Появилось"
    elif last_digit == 1:
        word = "тикет"
        verb = "Появился"
    elif 2 <= last_digit <= 4:
        word = "тикета"
        verb = "Появилось"
    else:
        word = "тикетов"
        verb = "Появилось"

    return (
        f"🔔 <b>{verb} {count} {word} без назначенного администратора.</b>\n\n"
        "Ответьте на них через команду /tickets."
    )


notification_lock = asyncio.Lock()


async def notify_admins_about_tickets(bot) -> None:
    if not ADMIN_IDS:
        logger.error("ADMIN_IDS пуст: уведомления не отправлены.")
        return

    async with notification_lock:
        try:
            statistics = await get_ticket_statistics(
                next(iter(ADMIN_IDS))
            )
            count = statistics["unassigned"]

        except Exception:
            logger.exception(
                "Не удалось получить статистику тикетов."
            )
            return

        if count <= 0:
            try:
                await deactivate_admin_notifications()
            except Exception:
                logger.exception(
                    "Не удалось деактивировать уведомления."
                )
            return

        notification = get_ticket_notification_text(count)

        for admin_id in ADMIN_IDS:
            try:
                saved = await get_admin_notification(admin_id)

                if (
                    saved is not None
                    and saved["is_active"]
                    and saved["message_id"] is not None
                ):
                    try:
                        await bot.edit_message_text(
                            chat_id=admin_id,
                            message_id=saved["message_id"],
                            text=notification,
                            parse_mode="HTML",
                        )
                        continue

                    except TelegramBadRequest as error:
                        error_text = str(error).lower()

                        if "message is not modified" in error_text:
                            continue

                        if not any(
                            phrase in error_text
                            for phrase in (
                                "message to edit not found",
                                "message can't be edited",
                                "message identifier is not specified",
                            )
                        ):
                            raise

                        logger.warning(
                            "Старое уведомление администратора %s "
                            "недоступно. Создаём новое.",
                            admin_id,
                        )

                sent_message = await bot.send_message(
                    chat_id=admin_id,
                    text=notification,
                    parse_mode="HTML",
                )

                await save_admin_notification(
                    admin_id=admin_id,
                    message_id=sent_message.message_id,
                )

            except Exception:
                logger.exception(
                    "Ошибка обновления уведомления администратора %s",
                    admin_id,
                )


# =========================
# АДМИНСКОЕ МЕНЮ ТИКЕТОВ
# =========================

def get_tickets_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📥 Открытые без владельца",
                    callback_data="tickets:unassigned",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📂 Все открытые",
                    callback_data="tickets:open",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📁 Закрытые",
                    callback_data="tickets:closed",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗂 История ваших закрытых",
                    callback_data="tickets:my_closed",
                )
            ],
            [
                InlineKeyboardButton(
                    text="👤 Ваши открытые",
                    callback_data="tickets:my_open",
                )
            ],
        ]
    )


def get_ticket_card_keyboard(
    ticket_id: int,
    assigned_admin_id: int | None = None,
    status: str = "open",
    current_admin_id: int | None = None,
) -> InlineKeyboardMarkup:

    buttons = []

    if status != "closed":
        if assigned_admin_id is None:
            buttons.append([
                InlineKeyboardButton(
                    text="👤 Назначить себе",
                    callback_data=f"ticket:assign:{ticket_id}",
                )
            ])

        elif assigned_admin_id == current_admin_id:
            buttons.append([
                InlineKeyboardButton(
                    text="💬 Ответить",
                    callback_data=f"ticket:reply:{ticket_id}",
                )
            ])

            buttons.append([
                InlineKeyboardButton(
                    text="🔒 Закрыть тикет",
                    callback_data=f"ticket:close:{ticket_id}",
                )
            ])

        else:
            buttons.append([
                InlineKeyboardButton(
                    text="🔁 Запросить передачу",
                    callback_data=f"ticket:transfer_request:{ticket_id}",
                )
            ])

            if current_admin_id == CREATOR_ID:
                buttons.append([
                    InlineKeyboardButton(
                        text="⚡ Забрать тикет себе",
                        callback_data=f"ticket:force_transfer:{ticket_id}",
                    )
                ])

    buttons.append([
        InlineKeyboardButton(
            text="🔄 Обновить карточку",
            callback_data=f"ticket:view:{ticket_id}",
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("tickets"))
async def admin_tickets_menu(message: Message) -> None:
    user = message.from_user

    if user is None or user.id not in ADMIN_IDS:
        return

    await message.answer(
        "🎫 <b>Панель управления тикетами</b>\n\n"
        "Выберите категорию тикетов:",
        reply_markup=get_tickets_keyboard(),
        parse_mode="HTML",
    )


# =========================
# ОТКРЫТЫЕ БЕЗ ВЛАДЕЛЬЦА
# =========================

@router.callback_query(F.data == "tickets:unassigned")
async def show_unassigned_tickets(
    callback: CallbackQuery,
) -> None:

    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(
            "Недостаточно прав.",
            show_alert=True,
        )
        return

    if not await check_callback_cooldown(callback):
        return

    await callback.answer()

    if not isinstance(callback.message, Message):
        return

    try:
        tickets = await get_unassigned_tickets(
            callback.from_user.id
        )

    except Exception:
        logger.exception(
            "Ошибка получения неназначенных тикетов."
        )

        await callback.message.answer(
            "⚠️ Не удалось загрузить тикеты."
        )
        return

    if not tickets:
        await callback.message.answer(
            "📭 Нет открытых тикетов без назначенного администратора."
        )
        return

    await callback.message.answer(
        f"📥 <b>Открытые без владельца: {len(tickets)}</b>",
        parse_mode="HTML",
    )

    for ticket in tickets:
        text = (
            f"🎫 <b>Тикет #{ticket['ticket_id']}</b>\n"
            f"Категория: {escape(str(ticket['category']))}\n"
            f"Пользователь: <code>{ticket['user_id']}</code>\n"
            f"Статус: {escape(str(ticket['status']))}\n"
            f"Создан: {escape(str(ticket['created_at']))}"
        )

        await callback.message.answer(
            text,
            reply_markup=get_ticket_card_keyboard(
                ticket_id=ticket["ticket_id"],
                assigned_admin_id=ticket["assigned_admin_id"],
                status=ticket["status"],
                current_admin_id=callback.from_user.id,
            ),
            parse_mode="HTML",
        )


# =========================
# СПИСКИ ТИКЕТОВ
# =========================

TICKET_LIST_HANDLERS = {
    "tickets:open": (
        get_all_open_tickets,
        "📂 Все открытые тикеты",
    ),
    "tickets:closed": (
        get_closed_tickets,
        "📁 Закрытые тикеты",
    ),
    "tickets:my_closed": (
        get_admin_closed_tickets,
        "🗂 История ваших закрытых тикетов",
    ),
    "tickets:my_open": (
        get_admin_open_tickets,
        "👤 Ваши открытые тикеты",
    ),
}


@router.callback_query(
    F.data.in_(TICKET_LIST_HANDLERS)
)
async def show_ticket_list(
    callback: CallbackQuery,
) -> None:

    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(
            "Недостаточно прав.",
            show_alert=True,
        )
        return

    if not await check_callback_cooldown(callback):
        return

    await callback.answer()

    if not isinstance(callback.message, Message):
        return

    handler, title = TICKET_LIST_HANDLERS[callback.data]

    try:
        tickets = await handler(
            callback.from_user.id
        )

    except Exception:
        logger.exception(
            "Ошибка загрузки списка тикетов: %s",
            callback.data,
        )

        await callback.message.answer(
            "⚠️ Не удалось загрузить тикеты."
        )
        return

    if not tickets:
        await callback.message.answer(
            f"{title}\n\n📭 Тикетов в этой категории нет."
        )
        return

    await callback.message.answer(
        f"<b>{title}: {len(tickets)}</b>",
        parse_mode="HTML",
    )

    for ticket in tickets:
        assigned_admin = ticket["assigned_admin_id"]

        admin_text = (
            str(assigned_admin)
            if assigned_admin is not None
            else "Не назначен"
        )

        text = (
            f"🎫 <b>Тикет #{ticket['ticket_id']}</b>\n"
            f"Категория: {escape(str(ticket['category']))}\n"
            f"Пользователь: <code>{ticket['user_id']}</code>\n"
            f"Статус: {escape(str(ticket['status']))}\n"
            f"Администратор: <code>{escape(admin_text)}</code>\n"
            f"Создан: {escape(str(ticket['created_at']))}"
        )

        await callback.message.answer(
            text,
            reply_markup=get_ticket_card_keyboard(
                ticket_id=ticket["ticket_id"],
                assigned_admin_id=ticket["assigned_admin_id"],
                status=ticket["status"],
                current_admin_id=callback.from_user.id,
            ),
            parse_mode="HTML",
        )


# =========================
# КАРТОЧКА ТИКЕТА
# =========================

def build_ticket_card_text(
    ticket,
    messages: list,
) -> list[str]:

    status_names = {
        "open": "Открыт",
        "in_progress": "В работе",
        "closed": "Закрыт",
    }

    category_names = {
        "problem": "Проблема",
        "suggestion": "Предложение",
        "feedback": "Отзыв",
        "question": "Вопрос",
    }

    assigned_admin = ticket["assigned_admin_id"]

    admin_text = (
        str(assigned_admin)
        if assigned_admin is not None
        else "Не назначен"
    )

    header = (
        f"🎫 <b>Тикет #{ticket['ticket_id']}</b>\n\n"
        f"Категория: "
        f"{escape(category_names.get(ticket['category'], str(ticket['category'])))}\n"
        f"Пользователь: <code>{ticket['user_id']}</code>\n"
        f"Статус: "
        f"{escape(status_names.get(ticket['status'], str(ticket['status'])))}\n"
        f"Администратор: <code>{escape(admin_text)}</code>\n"
        f"Создан: {escape(str(ticket['created_at']))}\n\n"
        "<b>История переписки:</b>"
    )

    chunks = [header]

    if not messages:
        chunks.append("Сообщений пока нет.")
        return chunks

    current_chunk = ""

    for item in messages:
        sender_type = item["sender_type"]

        if sender_type == "user":
            sender = "👤 Пользователь"
        elif sender_type == "admin":
            sender = "🛡 Администратор"
        else:
            sender = escape(str(sender_type))

        message_text = escape(str(item["message_text"]))
        created_at = escape(str(item["created_at"]))

        block = (
            f"\n\n{sender}\n"
            f"<i>{created_at}</i>\n"
            f"{message_text}"
        )

        if len(block) > 3500:
            block = block[:3500]

        if (
            current_chunk
            and len(current_chunk) + len(block) > 3500
        ):
            chunks.append(current_chunk)
            current_chunk = ""

        current_chunk += block

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


@router.callback_query(F.data.startswith("ticket:view:"))
async def show_ticket_card(
    callback: CallbackQuery,
) -> None:

    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(
            "Недостаточно прав.",
            show_alert=True,
        )
        return

    if not await check_callback_cooldown(callback):
        return

    try:
        ticket_id = int(callback.data.split(":")[2])

        if ticket_id < 1:
            raise ValueError

    except (ValueError, IndexError):
        await callback.answer(
            "Некорректный номер тикета.",
            show_alert=True,
        )
        return

    await callback.answer()

    if not isinstance(callback.message, Message):
        return

    try:
        ticket = await get_support_ticket(ticket_id)

        if ticket is None:
            await callback.message.answer(
                "⚠️ Тикет не найден."
            )
            return

        messages = await get_ticket_messages(ticket_id)

        chunks = build_ticket_card_text(
            ticket,
            messages,
        )

    except Exception:
        logger.exception(
            "Ошибка открытия тикета #%s",
            ticket_id,
        )

        await callback.message.answer(
            "⚠️ Не удалось загрузить карточку тикета."
        )
        return

    for index, chunk in enumerate(chunks):
        await callback.message.answer(
            chunk,
            parse_mode="HTML",
            reply_markup=(
                get_ticket_card_keyboard(
                    ticket_id=ticket_id,
                    assigned_admin_id=ticket["assigned_admin_id"],
                    status=ticket["status"],
                    current_admin_id=callback.from_user.id,
                )
                if index == len(chunks) - 1
                else None
            ),
        )
        
        
@router.callback_query(F.data.startswith("ticket:assign:"))
async def assign_ticket_to_self(
    callback: CallbackQuery,
) -> None:

    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(
            "Недостаточно прав.",
            show_alert=True,
        )
        return

    if not await check_callback_cooldown(callback):
        return

    try:
        ticket_id = int(callback.data.split(":")[2])

        if ticket_id < 1:
            raise ValueError

    except (ValueError, IndexError):
        await callback.answer(
            "Некорректный номер тикета.",
            show_alert=True,
        )
        return

    try:
        result = await assign_ticket_admin(
            ticket_id=ticket_id,
            admin_id=callback.from_user.id,
        )

        if result == "ticket_not_found":
            await callback.answer(
                "Тикет не найден.",
                show_alert=True,
            )
            return

        if result == "closed_ticket":
            await callback.answer(
                "Тикет уже закрыт.",
                show_alert=True,
            )
            return

        if result == "already_assigned":
            await callback.answer(
                "Тикет уже назначен другому администратору.",
                show_alert=True,
            )
            return

        if result == "permission_denied":
            await callback.answer(
                "Недостаточно прав.",
                show_alert=True,
            )
            return

        if result != "assigned":
            await callback.answer(
                "Не удалось назначить тикет.",
                show_alert=True,
            )
            return

        await callback.answer(
            "Тикет назначен вам."
        )

        if isinstance(callback.message, Message):
            await callback.message.answer(
                f"✅ Вы назначены ответственным за тикет #{ticket_id}."
            )

            ticket = await get_support_ticket(ticket_id)

            if ticket is not None:
                messages = await get_ticket_messages(ticket_id)

                chunks = build_ticket_card_text(
                    ticket,
                    messages,
                )

                for index, chunk in enumerate(chunks):
                    await callback.message.answer(
                        chunk,
                        parse_mode="HTML",
                        reply_markup=(
                            get_ticket_card_keyboard(
                                ticket_id=ticket_id,
                                assigned_admin_id=ticket["assigned_admin_id"],
                                status=ticket["status"],
                                current_admin_id=callback.from_user.id,
                            )
                            if index == len(chunks) - 1
                            else None
                        ),
                    )

    except Exception:
        logger.exception(
            "Ошибка назначения тикета #%s",
            ticket_id,
        )

        await callback.answer(
            "Внутренняя ошибка.",
            show_alert=True,
        )
        
        
# =========================
# ПЕРЕДАЧА ТИКЕТОВ
# =========================

def get_transfer_decision_keyboard(
    request_id: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Принять",
                    callback_data=f"ticket:transfer_accept:{request_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"ticket:transfer_reject:{request_id}",
                ),
            ]
        ]
    )


async def send_ticket_card(
    message: Message,
    ticket_id: int,
    current_admin_id: int,
) -> None:

    ticket = await get_support_ticket(ticket_id)

    if ticket is None:
        await message.answer("⚠️ Тикет не найден.")
        return

    messages = await get_ticket_messages(ticket_id)

    chunks = build_ticket_card_text(
        ticket,
        messages,
    )

    for index, chunk in enumerate(chunks):
        await message.answer(
            chunk,
            parse_mode="HTML",
            reply_markup=(
                get_ticket_card_keyboard(
                    ticket_id=ticket_id,
                    assigned_admin_id=ticket["assigned_admin_id"],
                    status=ticket["status"],
                    current_admin_id=current_admin_id,
                )
                if index == len(chunks) - 1
                else None
            ),
        )


@router.callback_query(
    F.data.startswith("ticket:transfer_request:")
)
async def create_ticket_transfer_request(
    callback: CallbackQuery,
) -> None:

    admin_id = callback.from_user.id

    if admin_id not in ADMIN_IDS:
        await callback.answer(
            "Недостаточно прав.",
            show_alert=True,
        )
        return

    if not await check_callback_cooldown(callback):
        return

    try:
        ticket_id = int(callback.data.split(":")[2])

        if ticket_id < 1:
            raise ValueError

    except (ValueError, IndexError):
        await callback.answer(
            "Некорректный номер тикета.",
            show_alert=True,
        )
        return

    try:
        result, request_id = await request_ticket_transfer(
            ticket_id=ticket_id,
            admin_id=admin_id,
        )

    except Exception:
        logger.exception(
            "Ошибка запроса передачи тикета #%s",
            ticket_id,
        )
        await callback.answer(
            "Внутренняя ошибка.",
            show_alert=True,
        )
        return

    messages = {
        "ticket_not_found": "Тикет не найден.",
        "closed_ticket": "Тикет уже закрыт.",
        "not_assigned": "У тикета нет владельца.",
        "already_owner": "Вы уже владелец тикета.",
        "transfer_pending": "Запрос передачи уже существует.",
        "permission_denied": "Недостаточно прав.",
    }

    if result in messages:
        await callback.answer(
            messages[result],
            show_alert=True,
        )
        return

    if result != "requested":
        await callback.answer(
            "Не удалось создать запрос.",
            show_alert=True,
        )
        return

    await callback.answer(
        "Запрос отправлен владельцу."
    )

    ticket = await get_support_ticket(ticket_id)

    if ticket is None:
        return

    owner_id = ticket["assigned_admin_id"]

    if owner_id is None:
        return

    try:
        await callback.bot.send_message(
            chat_id=owner_id,
            text=(
                f"🔁 <b>Запрос передачи тикета #{ticket_id}</b>\n\n"
                f"Администратор <code>{admin_id}</code> "
                "хочет получить этот тикет.\n\n"
                "Вы можете принять или отклонить запрос."
            ),
            parse_mode="HTML",
            reply_markup=get_transfer_decision_keyboard(
                request_id
            ),
        )

        if isinstance(callback.message, Message):
            await callback.message.answer(
                f"📨 Запрос передачи тикета #{ticket_id} "
                "отправлен его владельцу."
            )

    except Exception:
        logger.exception(
            "Не удалось отправить запрос передачи владельцу тикета #%s",
            ticket_id,
        )

        await callback.bot.send_message(
            chat_id=admin_id,
            text=(
                f"⚠️ Запрос #{request_id} сохранён, "
                "но уведомление владельцу отправить не удалось."
            ),
        )


@router.callback_query(
    F.data.startswith("ticket:transfer_accept:")
)
async def accept_ticket_transfer(
    callback: CallbackQuery,
) -> None:

    admin_id = callback.from_user.id

    if admin_id not in ADMIN_IDS:
        await callback.answer(
            "Недостаточно прав.",
            show_alert=True,
        )
        return

    if not await check_callback_cooldown(callback):
        return

    try:
        request_id = int(callback.data.split(":")[2])

        if request_id < 1:
            raise ValueError

    except (ValueError, IndexError):
        await callback.answer(
            "Некорректный запрос.",
            show_alert=True,
        )
        return

    try:
        result = await respond_ticket_transfer(
            request_id=request_id,
            admin_id=admin_id,
            decision="accept",
        )

    except Exception:
        logger.exception(
            "Ошибка принятия запроса передачи #%s",
            request_id,
        )
        await callback.answer(
            "Внутренняя ошибка.",
            show_alert=True,
        )
        return

    if result != "accepted":
        error_messages = {
            "request_not_found": "Запрос не найден.",
            "permission_denied": "Этот запрос адресован другому администратору.",
            "request_not_pending": "Запрос уже обработан.",
            "ticket_not_found": "Тикет не найден.",
            "closed_ticket": "Тикет закрыт. Запрос отменён.",
            "ownership_changed": "Владелец тикета уже изменился.",
            "transfer_failed": "Не удалось передать тикет.",
        }

        await callback.answer(
            error_messages.get(
                result,
                "Не удалось принять запрос.",
            ),
            show_alert=True,
        )
        return

    await callback.answer(
        "Передача принята."
    )

    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(
                reply_markup=None
            )
        except TelegramBadRequest:
            pass

    # Получаем тикет после передачи.
    # Теперь его владельцем является инициатор запроса.
    try:
        ticket = await get_support_ticket(
            int(
                callback.data.split(":")[2]
            )
        )
    except Exception:
        ticket = None

    # request_id не равен ticket_id.
    # Поэтому определяем тикет через список ожидавших запросов
    # здесь нельзя — отдельный метод получения запроса нужен.
    # Уведомление инициатору добавим после его получения
    # из репозитория на следующем этапе.


@router.callback_query(
    F.data.startswith("ticket:transfer_reject:")
)
async def reject_ticket_transfer(
    callback: CallbackQuery,
) -> None:

    admin_id = callback.from_user.id

    if admin_id not in ADMIN_IDS:
        await callback.answer(
            "Недостаточно прав.",
            show_alert=True,
        )
        return

    if not await check_callback_cooldown(callback):
        return

    try:
        request_id = int(callback.data.split(":")[2])

        if request_id < 1:
            raise ValueError

    except (ValueError, IndexError):
        await callback.answer(
            "Некорректный запрос.",
            show_alert=True,
        )
        return

    try:
        result = await respond_ticket_transfer(
            request_id=request_id,
            admin_id=admin_id,
            decision="reject",
        )

    except Exception:
        logger.exception(
            "Ошибка отклонения запроса передачи #%s",
            request_id,
        )
        await callback.answer(
            "Внутренняя ошибка.",
            show_alert=True,
        )
        return

    if result != "rejected":
        error_messages = {
            "request_not_found": "Запрос не найден.",
            "permission_denied": "Этот запрос адресован другому администратору.",
            "request_not_pending": "Запрос уже обработан.",
            "ticket_not_found": "Тикет не найден.",
            "ownership_changed": "Владелец тикета уже изменился.",
        }

        await callback.answer(
            error_messages.get(
                result,
                "Не удалось отклонить запрос.",
            ),
            show_alert=True,
        )
        return

    await callback.answer(
        "Запрос отклонён."
    )

    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(
                reply_markup=None
            )
        except TelegramBadRequest:
            pass


@router.callback_query(
    F.data.startswith("ticket:force_transfer:")
)
async def force_ticket_transfer(
    callback: CallbackQuery,
) -> None:

    admin_id = callback.from_user.id

    if admin_id != CREATOR_ID:
        await callback.answer(
            "Эта функция доступна только создателю.",
            show_alert=True,
        )
        return

    if not await check_callback_cooldown(callback):
        return

    try:
        ticket_id = int(callback.data.split(":")[2])

        if ticket_id < 1:
            raise ValueError

    except (ValueError, IndexError):
        await callback.answer(
            "Некорректный номер тикета.",
            show_alert=True,
        )
        return

    try:
        result = await force_reassign_ticket(
            ticket_id=ticket_id,
            admin_id=admin_id,
        )

    except Exception:
        logger.exception(
            "Ошибка принудительной передачи тикета #%s",
            ticket_id,
        )
        await callback.answer(
            "Внутренняя ошибка.",
            show_alert=True,
        )
        return

    error_messages = {
        "permission_denied": "Недостаточно прав.",
        "ticket_not_found": "Тикет не найден.",
        "closed_ticket": "Тикет уже закрыт.",
        "not_assigned": "Тикет ещё никому не назначен.",
        "already_owner": "Тикет уже назначен вам.",
        "transfer_failed": "Не удалось переназначить тикет.",
    }

    if result in error_messages:
        await callback.answer(
            error_messages[result],
            show_alert=True,
        )
        return

    if result != "transferred":
        await callback.answer(
            "Не удалось передать тикет.",
            show_alert=True,
        )
        return

    await callback.answer(
        "Тикет переназначен вам."
    )

    if isinstance(callback.message, Message):
        await callback.message.answer(
            f"⚡ Тикет #{ticket_id} переназначен вам."
        )

        await send_ticket_card(
            callback.message,
            ticket_id,
            admin_id,
        )
        
        
@router.callback_query(F.data.startswith("ticket:close:"))
async def close_support_ticket(
    callback: CallbackQuery,
) -> None:

    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(
            "Недостаточно прав.",
            show_alert=True,
        )
        return

    if not await check_callback_cooldown(callback):
        return

    try:
        ticket_id = int(callback.data.split(":")[2])

        if ticket_id < 1:
            raise ValueError

    except (ValueError, IndexError):
        await callback.answer(
            "Некорректный номер тикета.",
            show_alert=True,
        )
        return

    try:
        result = await close_ticket(
            ticket_id=ticket_id,
            admin_id=callback.from_user.id,
        )

    except Exception:
        logger.exception(
            "Ошибка закрытия тикета #%s",
            ticket_id,
        )
        await callback.answer(
            "Внутренняя ошибка.",
            show_alert=True,
        )
        return

    error_messages = {
        "ticket_not_found": "Тикет не найден.",
        "already_closed": "Тикет уже закрыт.",
        "not_assigned": "Этот тикет вам не назначен.",
        "permission_denied": "Недостаточно прав.",
    }

    if result in error_messages:
        await callback.answer(
            error_messages[result],
            show_alert=True,
        )
        return

    if result != "closed":
        await callback.answer(
            "Не удалось закрыть тикет.",
            show_alert=True,
        )
        return

    await callback.answer("Тикет закрыт.")

    if not isinstance(callback.message, Message):
        return

    try:
        await callback.message.answer(
            f"🔒 Тикет #{ticket_id} успешно закрыт."
        )

        ticket = await get_support_ticket(ticket_id)

        if ticket is None:
            return

        messages = await get_ticket_messages(ticket_id)

        chunks = build_ticket_card_text(
            ticket,
            messages,
        )

        for index, chunk in enumerate(chunks):
            await callback.message.answer(
                chunk,
                parse_mode="HTML",
                reply_markup=(
                    get_ticket_card_keyboard(
                        ticket_id=ticket_id,
                        assigned_admin_id=ticket["assigned_admin_id"],
                        status=ticket["status"],
                        current_admin_id=callback.from_user.id,
                    )
                    if index == len(chunks) - 1
                    else None
                ),
            )

    except Exception:
        logger.exception(
            "Тикет #%s закрыт, но не удалось обновить карточку.",
            ticket_id,
        )
        
        
@router.callback_query(F.data.startswith("ticket:reply:"))
async def start_admin_reply(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:

    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(
            "Недостаточно прав.",
            show_alert=True,
        )
        return

    if not await check_callback_cooldown(callback):
        return

    try:
        ticket_id = int(callback.data.split(":")[2])

        if ticket_id < 1:
            raise ValueError

    except (ValueError, IndexError):
        await callback.answer(
            "Некорректный номер тикета.",
            show_alert=True,
        )
        return

    try:
        ticket = await get_support_ticket(ticket_id)

        if ticket is None:
            await callback.answer(
                "Тикет не найден.",
                show_alert=True,
            )
            return

        if ticket["status"] == "closed":
            await callback.answer(
                "Тикет уже закрыт.",
                show_alert=True,
            )
            return

        if ticket["assigned_admin_id"] != callback.from_user.id:
            await callback.answer(
                "Этот тикет вам не назначен.",
                show_alert=True,
            )
            return

        await state.clear()
        await state.update_data(
            ticket_id=ticket_id,
        )

        await state.set_state(
            SupportState.waiting_for_admin_reply
        )

        await callback.answer()

        if isinstance(callback.message, Message):
            await callback.message.answer(
                f"💬 <b>Ответ на тикет #{ticket_id}</b>\n\n"
                "Отправьте сообщение пользователю.\n"
                "Для отмены используйте /cancel.",
                parse_mode="HTML",
            )

    except Exception:
        logger.exception(
            "Ошибка запуска ответа на тикет #%s",
            ticket_id,
        )

        await callback.answer(
            "Внутренняя ошибка.",
            show_alert=True,
        )
        
        
@router.message(
    SupportState.waiting_for_admin_reply,
    F.text,
    ~F.text.startswith("/"),
)
async def process_admin_reply(
    message: Message,
    state: FSMContext,
) -> None:

    admin = message.from_user

    if admin is None or admin.id not in ADMIN_IDS:
        await state.clear()
        return

    data = await state.get_data()
    ticket_id = data.get("ticket_id")

    if not isinstance(ticket_id, int):
        await state.clear()
        await message.answer(
            "⚠️ Не удалось определить тикет."
        )
        return

    reply_text = message.text.strip()

    if not reply_text:
        await message.answer(
            "⚠️ Сообщение не может быть пустым."
        )
        return

    if len(reply_text) > 4000:
        await message.answer(
            "⚠️ Сообщение не должно превышать 4000 символов."
        )
        return

    try:
        ticket = await get_support_ticket(ticket_id)

        if ticket is None:
            await state.clear()
            await message.answer(
                "⚠️ Тикет не найден."
            )
            return

        if ticket["status"] == "closed":
            await state.clear()
            await message.answer(
                "⚠️ Тикет уже закрыт."
            )
            return

        if ticket["assigned_admin_id"] != admin.id:
            await state.clear()
            await message.answer(
                "⚠️ Тикет больше не назначен вам."
            )
            return

        await message.bot.send_message(
            chat_id=ticket["user_id"],
            text=(
                f"🛡 <b>Ответ поддержки F-Society</b>\n\n"
                f"Тикет #{ticket_id}\n\n"
                f"{escape(reply_text)}"
            ),
            parse_mode="HTML",
        )

        result = await add_ticket_message(
            ticket_id=ticket_id,
            sender_id=admin.id,
            sender_type="admin",
            message=reply_text,
        )

        if result != "added":
            logger.error(
                "Ответ отправлен пользователю, "
                "но не сохранён в тикете #%s. Результат: %s",
                ticket_id,
                result,
            )

            await state.clear()
            await message.answer(
                "⚠️ Ответ отправлен пользователю, "
                "но сохранить его в истории тикета не удалось."
            )
            return

        await state.clear()

        await message.answer(
            f"✅ Ответ отправлен пользователю по тикету #{ticket_id}."
        )

    except Exception:
        logger.exception(
            "Ошибка отправки ответа по тикету #%s",
            ticket_id,
        )

        await message.answer(
            "⚠️ Не удалось отправить ответ. "
            "Проверьте состояние тикета и попробуйте снова."
        )
        
        
@router.message(
    SupportState.waiting_for_admin_reply,
    ~F.text,
)
async def invalid_admin_reply_content(
    message: Message,
) -> None:
    await message.answer(
        "⚠️ Для ответа на тикет отправьте обычный текст.\n\n"
        "Или используйте /cancel для отмены."
    )

# =========================
# ВЫБОР КАТЕГОРИИ
# =========================

SUPPORT_CATEGORIES = {
    "support_problem": "problem",
    "support_suggestion": "suggestion",
    "support_review": "feedback",
    "support_question": "question",
}


@router.callback_query(F.data.in_(SUPPORT_CATEGORIES))
async def select_support_category(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:

    if not await check_callback_cooldown(callback):
        return

    await callback.answer()

    category = SUPPORT_CATEGORIES[callback.data]

    await state.clear()
    await state.update_data(category=category)

    await state.set_state(
        SupportState.waiting_for_message
    )

    category_names = {
        "problem": "⚠️ Сообщение о проблеме",
        "suggestion": "💡 Предложение",
        "feedback": "💬 Отзыв",
        "question": "❓ Вопрос",
    }

    if not isinstance(callback.message, Message):
        return

    await callback.message.answer(
        (
            f"<b>{category_names[category]}</b>\n\n"
            "Опишите ваше обращение одним сообщением.\n\n"
            "Для отмены используйте /cancel."
        ),
        parse_mode="HTML",
    )


# =========================
# НЕ ТЕКСТОВОЕ СООБЩЕНИЕ
# =========================

@router.message(
    SupportState.waiting_for_message,
    ~F.text,
)
async def invalid_support_content(
    message: Message,
) -> None:

    await message.answer(
        "⚠️ Отправьте обращение обычным текстовым сообщением."
    )


# =========================
# СОЗДАНИЕ ТИКЕТА
# =========================

@router.message(
    SupportState.waiting_for_message,
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_({
        "🏠 Главное меню",
        "👤 Профиль",
        "🆘 Поддержка",
    }),
)
async def process_support_message(
    message: Message,
    state: FSMContext,
) -> None:

    user = message.from_user

    if user is None:
        return

    data = await state.get_data()
    category = data.get("category")

    if category not in {
        "problem",
        "suggestion",
        "feedback",
        "question",
    }:
        await state.clear()

        await message.answer(
            "⚠️ Не удалось определить категорию обращения. "
            "Откройте поддержку заново."
        )
        return

    try:
        status, retry_at = await create_support_ticket(
            user_id=user.id,
            category=category,
            message=message.text,
        )

    except Exception:
        logger.exception(
            "Ошибка создания тикета пользователя %s",
            user.id,
        )

        await message.answer(
            "⚠️ Не удалось отправить обращение. "
            "Попробуйте ещё раз."
        )
        return

    if status == "created":
        await state.clear()

        await message.answer(
            (
                "✅ <b>Тикет успешно создан!</b>\n\n"
                "Ваше сообщение сохранено в системе поддержки.\n"
                "Администратор рассмотрит его в ближайшее время.\n\n"
                "Спасибо за обращение в F-Society."
            ),
            parse_mode="HTML",
        )

        await notify_admins_about_tickets(message.bot)

    elif status == "active_ticket":
        await state.clear()

        await message.answer(
            (
                "⚠️ <b>У вас уже есть активный тикет "
                "в этой категории.</b>\n\n"
                "Дождитесь его рассмотрения."
            ),
            parse_mode="HTML",
        )

    elif status == "cooldown":
        await state.clear()

        retry_text = (
            retry_at.strftime("%d.%m.%Y в %H:%M")
            if retry_at is not None
            else "позже"
        )

        await message.answer(
            (
                "⏳ <b>Повторное создание тикета пока недоступно.</b>\n\n"
                f"Вы сможете создать новый тикет: "
                f"{retry_text} (МСК)."
            ),
            parse_mode="HTML",
        )

    else:
        logger.error(
            "Неизвестный результат создания тикета: %s",
            status,
        )

        await message.answer(
            "⚠️ Не удалось обработать обращение. "
            "Попробуйте позже."
        )