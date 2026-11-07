import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from database.db import (
    get_banned_users,
    set_user_ban,
)
from repositories.subscription_repository import (
    get_subscribers,
    subscribe_user,
    unsubscribe_user,
)
from services.notification_service import send_notification


router = Router()
logger = logging.getLogger(__name__)


VPN_NOTIFICATION_TYPE = "vpn"
OSINT_NOTIFICATION_TYPE = "osint"

ADMIN_IDS = {
    6495550812,
    6326978216,
}


class BroadcastState(StatesGroup):
    waiting_for_type = State()
    waiting_for_text = State()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def check_admin(message: Message) -> bool:
    """Проверяет права администратора."""

    user = message.from_user

    if user is None or not is_admin(user.id):
        await message.answer(
            "⛔ Недостаточно прав."
        )
        return False

    return True


async def handle_subscribe(
    message: Message,
    notification_type: str,
    notification_name: str,
) -> None:
    """Оформляет подписку на определённый тип уведомлений."""

    user = message.from_user

    if user is None:
        return

    try:
        result = await subscribe_user(
            user.id,
            notification_type,
        )

        responses = {
            "new": (
                f"🔔 Вы подписались на уведомления "
                f"{notification_name}."
            ),
            "reactivated": (
                f"🔔 Подписка на уведомления "
                f"{notification_name} снова активирована."
            ),
            "already_active": (
                f"ℹ️ Вы уже подписаны на уведомления "
                f"{notification_name}."
            ),
        }

        await message.answer(
            responses.get(
                result,
                "⚠️ Не удалось определить статус подписки.",
            )
        )

    except Exception:
        logger.exception(
            "Ошибка подписки пользователя %s "
            "на уведомления %s",
            user.id,
            notification_type,
        )

        await message.answer(
            "⚠️ Не удалось оформить подписку. "
            "Попробуйте позже."
        )


async def handle_unsubscribe(
    message: Message,
    notification_type: str,
    notification_name: str,
) -> None:
    """Отменяет подписку на определённый тип уведомлений."""

    user = message.from_user

    if user is None:
        return

    try:
        success = await unsubscribe_user(
            user.id,
            notification_type,
        )

        if success:
            await message.answer(
                f"🔕 Вы отписались от уведомлений "
                f"{notification_name}."
            )
        else:
            await message.answer(
                f"ℹ️ У вас нет активной подписки "
                f"на уведомления {notification_name}."
            )

    except Exception:
        logger.exception(
            "Ошибка отписки пользователя %s "
            "от уведомлений %s",
            user.id,
            notification_type,
        )

        await message.answer(
            "⚠️ Не удалось выполнить отписку. "
            "Попробуйте позже."
        )


# =========================
# ПОЛЬЗОВАТЕЛЬСКИЕ ПОДПИСКИ
# =========================

@router.message(Command("subscribe"))
async def subscribe_menu(
    message: Message,
) -> None:
    await message.answer(
        "🔔 <b>Управление уведомлениями</b>\n\n"
        "🛡 <b>VPN:</b>\n"
        "/subscribe_vpn — подписаться\n"
        "/unsubscribe_vpn — отписаться\n\n"
        "🔎 <b>OSINT:</b>\n"
        "/subscribe_osint — подписаться\n"
        "/unsubscribe_osint — отписаться",
        parse_mode="HTML",
    )


@router.message(Command("unsubscribe"))
async def unsubscribe_menu(
    message: Message,
) -> None:
    await message.answer(
        "🔕 <b>Отмена подписок</b>\n\n"
        "🛡 VPN:\n"
        "/unsubscribe_vpn\n\n"
        "🔎 OSINT:\n"
        "/unsubscribe_osint",
        parse_mode="HTML",
    )


@router.message(Command("subscribe_vpn"))
async def subscribe_vpn(
    message: Message,
) -> None:
    await handle_subscribe(
        message,
        VPN_NOTIFICATION_TYPE,
        "VPN",
    )


@router.message(Command("unsubscribe_vpn"))
async def unsubscribe_vpn(
    message: Message,
) -> None:
    await handle_unsubscribe(
        message,
        VPN_NOTIFICATION_TYPE,
        "VPN",
    )


@router.message(Command("subscribe_osint"))
async def subscribe_osint(
    message: Message,
) -> None:
    await handle_subscribe(
        message,
        OSINT_NOTIFICATION_TYPE,
        "OSINT",
    )


@router.message(Command("unsubscribe_osint"))
async def unsubscribe_osint(
    message: Message,
) -> None:
    await handle_unsubscribe(
        message,
        OSINT_NOTIFICATION_TYPE,
        "OSINT",
    )


# =========================
# АДМИН: СТАТИСТИКА
# =========================

@router.message(Command("subscribers"))
async def subscribers_cmd(
    message: Message,
) -> None:
    if not await check_admin(message):
        return

    try:
        vpn_subscribers = await get_subscribers(
            VPN_NOTIFICATION_TYPE,
        )

        osint_subscribers = await get_subscribers(
            OSINT_NOTIFICATION_TYPE,
        )

        await message.answer(
            "📊 <b>Статистика подписчиков</b>\n\n"
            f"🛡 VPN: <b>{len(vpn_subscribers)}</b>\n"
            f"🔎 OSINT: <b>{len(osint_subscribers)}</b>",
            parse_mode="HTML",
        )

    except Exception:
        logger.exception(
            "Ошибка получения статистики подписчиков"
        )

        await message.answer(
            "⚠️ Не удалось получить статистику."
        )


# =========================
# АДМИН: РАССЫЛКА
# =========================

@router.message(Command("broadcast"))
async def broadcast_cmd(
    message: Message,
    state: FSMContext,
) -> None:
    if not await check_admin(message):
        return

    await state.set_state(
        BroadcastState.waiting_for_type,
    )

    await message.answer(
        "📢 <b>Создание рассылки</b>\n\n"
        "Выберите тип уведомления:\n\n"
        "🛡 <code>vpn</code> — VPN-подписчики\n"
        "🔎 <code>osint</code> — OSINT-подписчики\n\n"
        "Отправьте нужный тип сообщением.\n"
        "Для отмены используйте /cancel",
        parse_mode="HTML",
    )


@router.message(
    BroadcastState.waiting_for_type,
    F.text,
)
async def broadcast_select_type(
    message: Message,
    state: FSMContext,
) -> None:
    if not await check_admin(message):
        await state.clear()
        return

    notification_type = message.text.strip().lower()

    allowed_types = {
        VPN_NOTIFICATION_TYPE,
        OSINT_NOTIFICATION_TYPE,
    }

    if notification_type not in allowed_types:
        await message.answer(
            "⚠️ Неверный тип уведомления.\n\n"
            "Введите: <code>vpn</code> или "
            "<code>osint</code>.",
            parse_mode="HTML",
        )
        return

    await state.update_data(
        notification_type=notification_type,
    )

    await state.set_state(
        BroadcastState.waiting_for_text,
    )

    await message.answer(
        "✍️ Теперь отправьте текст уведомления.\n\n"
        "Для отмены используйте /cancel"
    )


@router.message(
    BroadcastState.waiting_for_text,
    F.text,
)
async def broadcast_send(
    message: Message,
    state: FSMContext,
) -> None:
    if not await check_admin(message):
        await state.clear()
        return

    data = await state.get_data()

    notification_type = data.get(
        "notification_type",
    )

    notification_text = message.text.strip()

    if not notification_text:
        await message.answer(
            "⚠️ Текст уведомления не может быть пустым."
        )
        return

    try:
        await message.answer(
            "⏳ Начинаю отправку уведомлений..."
        )

        result = await send_notification(
            bot=message.bot,
            notification_type=notification_type,
            text=notification_text,
        )

        await message.answer(
            "✅ <b>Рассылка завершена</b>\n\n"
            f"📨 Всего подписчиков: "
            f"<b>{result['total']}</b>\n"
            f"✅ Отправлено: "
            f"<b>{result['sent']}</b>\n"
            f"❌ Ошибок: "
            f"<b>{result['failed']}</b>",
            parse_mode="HTML",
        )

    except Exception:
        logger.exception(
            "Ошибка при выполнении рассылки"
        )

        await message.answer(
            "⚠️ Во время рассылки произошла ошибка."
        )

    finally:
        await state.clear()


# =========================
# АДМИН: ЗАБЛОКИРОВАННЫЕ
# =========================

@router.message(Command("banned"))
async def banned_cmd(
    message: Message,
) -> None:
    if not await check_admin(message):
        return

    try:
        banned_users = await get_banned_users()

        if not banned_users:
            await message.answer(
                "✅ Заблокированных пользователей нет."
            )
            return

        lines = [
            "🚫 <b>Заблокированные пользователи</b>\n"
        ]

        for banned_user in banned_users:
            user_id = banned_user["user_id"]
            username = banned_user["username"]
            full_name = banned_user["full_name"]
            joined_date = banned_user["joined_date"]

            safe_name = (
                full_name
                if full_name
                else "Неизвестно"
            )

            safe_username = (
                f"@{username}"
                if username
                else "Без username"
            )

            lines.append(
                f"🆔 <code>{user_id}</code>\n"
                f"👤 {safe_name}\n"
                f"📌 {safe_username}\n"
                f"📅 Регистрация: {joined_date}\n"
            )

        await message.answer(
            "\n".join(lines),
            parse_mode="HTML",
        )

    except Exception:
        logger.exception(
            "Ошибка получения списка "
            "заблокированных пользователей"
        )

        await message.answer(
            "⚠️ Не удалось получить список "
            "заблокированных пользователей."
        )


# =========================
# АДМИН: БАН
# =========================

@router.message(Command("ban"))
async def ban_user_cmd(
    message: Message,
) -> None:
    if not await check_admin(message):
        return

    parts = (
        message.text.split(maxsplit=1)
        if message.text
        else []
    )

    if (
        len(parts) != 2
        or not parts[1].isdigit()
    ):
        await message.answer(
            "⚠️ Использование:\n"
            "<code>/ban USER_ID</code>",
            parse_mode="HTML",
        )
        return

    target_user_id = int(parts[1])

    if target_user_id in ADMIN_IDS:
        await message.answer(
            "⛔ Нельзя заблокировать администратора."
        )
        return

    try:
        updated = await set_user_ban(
            target_user_id,
            True,
        )

        if not updated:
            await message.answer(
                "⚠️ Пользователь с таким ID "
                "не найден."
            )
            return

        await message.answer(
            f"🚫 Пользователь "
            f"<code>{target_user_id}</code> "
            f"заблокирован.",
            parse_mode="HTML",
        )

    except Exception:
        logger.exception(
            "Ошибка блокировки пользователя %s",
            target_user_id,
        )

        await message.answer(
            "⚠️ Не удалось заблокировать пользователя."
        )


# =========================
# АДМИН: РАЗБАН
# =========================

@router.message(Command("unban"))
async def unban_user_cmd(
    message: Message,
) -> None:
    if not await check_admin(message):
        return

    parts = (
        message.text.split(maxsplit=1)
        if message.text
        else []
    )

    if (
        len(parts) != 2
        or not parts[1].isdigit()
    ):
        await message.answer(
            "⚠️ Использование:\n"
            "<code>/unban USER_ID</code>",
            parse_mode="HTML",
        )
        return

    target_user_id = int(parts[1])

    try:
        updated = await set_user_ban(
            target_user_id,
            False,
        )

        if not updated:
            await message.answer(
                "⚠️ Пользователь с таким ID "
                "не найден."
            )
            return

        await message.answer(
            f"✅ Пользователь "
            f"<code>{target_user_id}</code> "
            f"разблокирован.",
            parse_mode="HTML",
        )

    except Exception:
        logger.exception(
            "Ошибка разблокировки пользователя %s",
            target_user_id,
        )

        await message.answer(
            "⚠️ Не удалось разблокировать пользователя."
        )
        