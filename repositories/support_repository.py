from datetime import (
    datetime,
    timedelta,
    timezone,
)

from database.db import connect_db
from admin_config import ADMIN_IDS
from admin_config import ADMIN_IDS, CREATOR_ID


MSK = timezone(
    timedelta(hours=3)
)

UNREVIEWED_COOLDOWN = timedelta(hours=12)
CLOSED_COOLDOWN = timedelta(minutes=30)

ALLOWED_CATEGORIES = {
    "problem",
    "suggestion",
    "feedback",
    "question",
}


def get_current_datetime() -> datetime:
    return datetime.now(MSK)


def get_current_timestamp() -> str:
    return get_current_datetime().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


async def create_support_ticket(
    user_id: int,
    category: str,
    message: str,
) -> tuple[str, datetime | None]:

    if category not in ALLOWED_CATEGORIES:
        raise ValueError(
            "Недопустимая категория обращения."
        )

    message = message.strip()

    if not message:
        raise ValueError(
            "Сообщение не может быть пустым."
        )

    if len(message) > 4000:
        raise ValueError(
            "Сообщение не должно превышать 4000 символов."
        )

    now = get_current_datetime()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    async with connect_db() as db:
        await db.execute("BEGIN IMMEDIATE")

        try:
            async with db.execute(
                """
                SELECT
                    status,
                    created_at,
                    closed_at
                FROM support_tickets
                WHERE user_id = ?
                  AND category = ?
                ORDER BY created_at DESC, ticket_id DESC
                LIMIT 1
                """,
                (user_id, category),
            ) as cursor:
                last_ticket = await cursor.fetchone()

            if last_ticket is not None:

                if last_ticket["status"] == "closed":
                    cooldown_start = (
                        last_ticket["closed_at"]
                        or last_ticket["created_at"]
                    )

                    retry_at = (
                        datetime.strptime(
                            cooldown_start,
                            "%Y-%m-%d %H:%M:%S",
                        ).replace(tzinfo=MSK)
                        + CLOSED_COOLDOWN
                    )

                else:
                    retry_at = (
                        datetime.strptime(
                            last_ticket["created_at"],
                            "%Y-%m-%d %H:%M:%S",
                        ).replace(tzinfo=MSK)
                        + UNREVIEWED_COOLDOWN
                    )

                if now < retry_at:
                    await db.commit()
                    return "cooldown", retry_at

            async with db.execute(
                """
                INSERT INTO support_tickets (
                    user_id,
                    category,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, 'open', ?, ?)
                """,
                (
                    user_id,
                    category,
                    timestamp,
                    timestamp,
                ),
            ) as cursor:
                ticket_id = cursor.lastrowid

            await db.execute(
                """
                INSERT INTO support_ticket_messages (
                    ticket_id,
                    sender_id,
                    sender_type,
                    message_text,
                    created_at
                )
                VALUES (?, ?, 'user', ?, ?)
                """,
                (
                    ticket_id,
                    user_id,
                    message,
                    timestamp,
                ),
            )

            await db.commit()
            return "created", None

        except Exception:
            await db.rollback()
            raise


async def get_user_tickets(
    user_id: int,
    limit: int = 20,
) -> list:

    if limit < 1:
        raise ValueError(
            "Лимит должен быть положительным."
        )

    async with connect_db() as db:
        async with db.execute(
            """
            SELECT
                ticket_id,
                user_id,
                category,
                status,
                created_at,
                updated_at,
                closed_at,
                assigned_admin_id
            FROM support_tickets
            WHERE user_id = ?
            ORDER BY created_at DESC, ticket_id DESC
            LIMIT ?
            """,
            (
                user_id,
                limit,
            ),
        ) as cursor:
            return await cursor.fetchall()


async def get_support_ticket(
    ticket_id: int,
):

    async with connect_db() as db:
        async with db.execute(
            """
            SELECT
                ticket_id,
                user_id,
                category,
                status,
                created_at,
                updated_at,
                closed_at,
                assigned_admin_id
            FROM support_tickets
            WHERE ticket_id = ?
            """,
            (ticket_id,),
        ) as cursor:
            return await cursor.fetchone()


async def get_ticket_messages(
    ticket_id: int,
) -> list:

    async with connect_db() as db:
        async with db.execute(
            """
            SELECT
                message_id,
                ticket_id,
                sender_id,
                sender_type,
                message_text,
                created_at
            FROM support_ticket_messages
            WHERE ticket_id = ?
            ORDER BY created_at ASC, message_id ASC
            """,
            (ticket_id,),
        ) as cursor:
            return await cursor.fetchall()
            
async def add_ticket_message(
    ticket_id: int,
    sender_id: int,
    sender_type: str,
    message: str,
) -> str:

    if sender_type not in {"user", "admin"}:
        raise ValueError(
            "Недопустимый тип отправителя."
        )

    message = message.strip()

    if not message:
        raise ValueError(
            "Сообщение не может быть пустым."
        )

    if len(message) > 4000:
        raise ValueError(
            "Сообщение не должно превышать 4000 символов."
        )

    timestamp = get_current_timestamp()

    async with connect_db() as db:
        await db.execute("BEGIN IMMEDIATE")

        try:
            async with db.execute(
                """
                SELECT user_id, status
                FROM support_tickets
                WHERE ticket_id = ?
                """,
                (ticket_id,),
            ) as cursor:
                ticket = await cursor.fetchone()

            if ticket is None:
                await db.commit()
                return "ticket_not_found"

            if ticket["status"] == "closed":
                await db.commit()
                return "closed_ticket"

            if (
                sender_type == "user"
                and sender_id != ticket["user_id"]
            ):
                await db.commit()
                return "permission_denied"

            await db.execute(
                """
                INSERT INTO support_ticket_messages (
                    ticket_id,
                    sender_id,
                    sender_type,
                    message_text,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    sender_id,
                    sender_type,
                    message,
                    timestamp,
                ),
            )

            await db.execute(
                """
                UPDATE support_tickets
                SET updated_at = ?
                WHERE ticket_id = ?
                """,
                (
                    timestamp,
                    ticket_id,
                ),
            )

            await db.commit()
            return "added"

        except Exception:
            await db.rollback()
            raise
            
            
async def update_ticket_status(
    ticket_id: int,
    status: str,
) -> str:

    allowed_statuses = {
        "open",
        "in_progress",
        "closed",
    }

    if status not in allowed_statuses:
        raise ValueError(
            "Недопустимый статус тикета."
        )

    timestamp = get_current_timestamp()

    closed_at = (
        timestamp
        if status == "closed"
        else None
    )

    async with connect_db() as db:
        await db.execute("BEGIN IMMEDIATE")

        try:
            async with db.execute(
                """
                SELECT ticket_id
                FROM support_tickets
                WHERE ticket_id = ?
                """,
                (ticket_id,),
            ) as cursor:
                ticket = await cursor.fetchone()

            if ticket is None:
                await db.commit()
                return "ticket_not_found"

            await db.execute(
                """
                UPDATE support_tickets
                SET
                    status = ?,
                    updated_at = ?,
                    closed_at = ?
                WHERE ticket_id = ?
                """,
                (
                    status,
                    timestamp,
                    closed_at,
                    ticket_id,
                ),
            )

            if status == "closed":
                async with db.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM support_tickets
                    WHERE assigned_admin_id IS NULL
                      AND status IN ('open', 'in_progress')
                    """
                ) as cursor:
                    row = await cursor.fetchone()

                if row["total"] == 0:
                    await db.execute(
                        """
                        UPDATE support_admin_notifications
                        SET is_active = 0
                        WHERE is_active = 1
                        """
                    )

            await db.commit()
            return "updated"

        except Exception:
            await db.rollback()
            raise
            
            
async def close_ticket(
    ticket_id: int,
    admin_id: int,
) -> str:

    if admin_id not in ADMIN_IDS:
        return "permission_denied"

    timestamp = get_current_timestamp()

    async with connect_db() as db:
        await db.execute("BEGIN IMMEDIATE")

        try:
            async with db.execute(
                """
                SELECT status, assigned_admin_id
                FROM support_tickets
                WHERE ticket_id = ?
                """,
                (ticket_id,),
            ) as cursor:
                ticket = await cursor.fetchone()

            if ticket is None:
                await db.commit()
                return "ticket_not_found"

            if ticket["status"] == "closed":
                await db.commit()
                return "already_closed"

            if ticket["assigned_admin_id"] != admin_id:
                await db.commit()
                return "not_assigned"

            cursor = await db.execute(
                """
                UPDATE support_tickets
                SET
                    status = 'closed',
                    updated_at = ?,
                    closed_at = ?
                WHERE ticket_id = ?
                  AND assigned_admin_id = ?
                  AND status IN ('open', 'in_progress')
                """,
                (
                    timestamp,
                    timestamp,
                    ticket_id,
                    admin_id,
                ),
            )

            if cursor.rowcount == 0:
                await db.rollback()
                return "close_failed"

            await db.commit()
            return "closed"

        except Exception:
            await db.rollback()
            raise
       
async def assign_ticket_admin(
    ticket_id: int,
    admin_id: int,
) -> str:

    if admin_id not in ADMIN_IDS:
        return "permission_denied"

    timestamp = get_current_timestamp()

    async with connect_db() as db:
        await db.execute("BEGIN IMMEDIATE")

        try:
            cursor = await db.execute(
                """
                UPDATE support_tickets
                SET
                    assigned_admin_id = ?,
                    updated_at = ?
                WHERE ticket_id = ?
                  AND assigned_admin_id IS NULL
                  AND status IN ('open', 'in_progress')
                """,
                (
                    admin_id,
                    timestamp,
                    ticket_id,
                ),
            )

            if cursor.rowcount == 0:
                async with db.execute(
                    """
                    SELECT
                        status,
                        assigned_admin_id
                    FROM support_tickets
                    WHERE ticket_id = ?
                    """,
                    (ticket_id,),
                ) as cursor:
                    ticket = await cursor.fetchone()

                await db.commit()

                if ticket is None:
                    return "ticket_not_found"

                if ticket["status"] == "closed":
                    return "closed_ticket"

                if ticket["assigned_admin_id"] is not None:
                    return "already_assigned"

                return "assignment_failed"

            async with db.execute(
                """
                SELECT COUNT(*) AS total
                FROM support_tickets
                WHERE assigned_admin_id IS NULL
                  AND status IN ('open', 'in_progress')
                """
            ) as cursor:
                row = await cursor.fetchone()

            if row["total"] == 0:
                await db.execute(
                    """
                    UPDATE support_admin_notifications
                    SET is_active = 0
                    WHERE is_active = 1
                    """
                )

            await db.commit()
            return "assigned"

        except Exception:
            await db.rollback()
            raise
            
           
async def get_admin_tickets(
    admin_id: int,
    status: str | None = None,
    limit: int = 50,
) -> list:

    if admin_id not in ADMIN_IDS:
        raise PermissionError(
            "Недостаточно прав для просмотра тикетов."
        )

    allowed_statuses = {
        "open",
        "in_progress",
        "closed",
    }

    if status is not None and status not in allowed_statuses:
        raise ValueError(
            "Недопустимый статус тикета."
        )

    if limit < 1:
        raise ValueError(
            "Лимит должен быть положительным."
        )

    query = """
        SELECT
            ticket_id,
            user_id,
            category,
            status,
            created_at,
            updated_at,
            closed_at,
            assigned_admin_id
        FROM support_tickets
        WHERE assigned_admin_id = ?
    """

    params = [admin_id]

    if status is not None:
        query += " AND status = ?"
        params.append(status)

    query += """
        ORDER BY updated_at DESC, ticket_id DESC
        LIMIT ?
    """

    params.append(limit)

    async with connect_db() as db:
        async with db.execute(
            query,
            tuple(params),
        ) as cursor:
            return await cursor.fetchall()

            
async def get_all_open_tickets(
    admin_id: int,
    limit: int = 50,
) -> list:

    if admin_id not in ADMIN_IDS:
        raise PermissionError(
            "Недостаточно прав для просмотра тикетов."
        )

    if limit < 1:
        raise ValueError(
            "Лимит должен быть положительным."
        )

    async with connect_db() as db:
        async with db.execute(
            """
            SELECT
                ticket_id,
                user_id,
                category,
                status,
                created_at,
                updated_at,
                closed_at,
                assigned_admin_id
            FROM support_tickets
            WHERE status IN ('open', 'in_progress')
            ORDER BY updated_at DESC, ticket_id DESC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            return await cursor.fetchall()


async def get_admin_open_tickets(
    admin_id: int,
    limit: int = 50,
) -> list:

    if admin_id not in ADMIN_IDS:
        raise PermissionError(
            "Недостаточно прав для просмотра тикетов."
        )

    if limit < 1:
        raise ValueError(
            "Лимит должен быть положительным."
        )

    async with connect_db() as db:
        async with db.execute(
            """
            SELECT
                ticket_id,
                user_id,
                category,
                status,
                created_at,
                updated_at,
                closed_at,
                assigned_admin_id
            FROM support_tickets
            WHERE assigned_admin_id = ?
              AND status IN ('open', 'in_progress')
            ORDER BY updated_at DESC, ticket_id DESC
            LIMIT ?
            """,
            (admin_id, limit),
        ) as cursor:
            return await cursor.fetchall()


async def get_admin_closed_tickets(
    admin_id: int,
    limit: int = 50,
) -> list:

    if admin_id not in ADMIN_IDS:
        raise PermissionError(
            "Недостаточно прав для просмотра тикетов."
        )

    if limit < 1:
        raise ValueError(
            "Лимит должен быть положительным."
        )

    async with connect_db() as db:
        async with db.execute(
            """
            SELECT
                ticket_id,
                user_id,
                category,
                status,
                created_at,
                updated_at,
                closed_at,
                assigned_admin_id
            FROM support_tickets
            WHERE assigned_admin_id = ?
              AND status = 'closed'
            ORDER BY closed_at DESC, ticket_id DESC
            LIMIT ?
            """,
            (admin_id, limit),
        ) as cursor:
            return await cursor.fetchall()
                        
            
async def get_unassigned_tickets(
    admin_id: int,
    status: str | None = None,
    limit: int = 50,
) -> list:

    if admin_id not in ADMIN_IDS:
        raise PermissionError(
            "Недостаточно прав для просмотра тикетов."
        )

    allowed_statuses = {
        "open",
        "in_progress",
        "closed",
    }

    if status is not None and status not in allowed_statuses:
        raise ValueError(
            "Недопустимый статус тикета."
        )

    if limit < 1:
        raise ValueError(
            "Лимит должен быть положительным."
        )

    query = """
        SELECT
            ticket_id,
            user_id,
            category,
            status,
            created_at,
            updated_at,
            closed_at,
            assigned_admin_id
        FROM support_tickets
        WHERE assigned_admin_id IS NULL
    """

    params = []

    if status is not None:
        query += " AND status = ?"
        params.append(status)
    else:
        query += " AND status IN ('open', 'in_progress')"

    query += """
        ORDER BY updated_at DESC, ticket_id DESC
        LIMIT ?
    """

    params.append(limit)

    async with connect_db() as db:
        async with db.execute(
            query,
            tuple(params),
        ) as cursor:
            return await cursor.fetchall()
            
            
async def get_closed_tickets(
    admin_id: int,
    limit: int = 50,
) -> list:

    if admin_id not in ADMIN_IDS:
        raise PermissionError(
            "Недостаточно прав для просмотра тикетов."
        )

    if limit < 1:
        raise ValueError(
            "Лимит должен быть положительным."
        )

    async with connect_db() as db:
        async with db.execute(
            """
            SELECT
                ticket_id,
                user_id,
                category,
                status,
                created_at,
                updated_at,
                closed_at,
                assigned_admin_id
            FROM support_tickets
            WHERE status = 'closed'
            ORDER BY closed_at DESC, ticket_id DESC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            return await cursor.fetchall()
            
            
async def get_ticket_statistics(
    admin_id: int,
) -> dict:

    if admin_id not in ADMIN_IDS:
        raise PermissionError(
            "Недостаточно прав для просмотра статистики."
        )

    async with connect_db() as db:
        async with db.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open,
                SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) AS in_progress,
                SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) AS closed,
                SUM(
                    CASE
                        WHEN assigned_admin_id IS NULL
                         AND status IN ('open', 'in_progress')
                        THEN 1
                        ELSE 0
                    END
                ) AS unassigned
            FROM support_tickets
            """
        ) as cursor:
            row = await cursor.fetchone()

            return {
                "total": row["total"],
                "open": row["open"],
                "in_progress": row["in_progress"],
                "closed": row["closed"],
                "unassigned": row["unassigned"],
            }
            
async def get_admin_notification(
    admin_id: int,
):
    if admin_id not in ADMIN_IDS:
        raise PermissionError(
            "Недостаточно прав."
        )

    async with connect_db() as db:
        async with db.execute(
            """
            SELECT message_id, is_active
            FROM support_admin_notifications
            WHERE admin_id = ?
            """,
            (admin_id,),
        ) as cursor:
            return await cursor.fetchone()


async def save_admin_notification(
    admin_id: int,
    message_id: int,
) -> None:

    if admin_id not in ADMIN_IDS:
        raise PermissionError(
            "Недостаточно прав."
        )

    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO support_admin_notifications (
                admin_id,
                message_id,
                is_active
            )
            VALUES (?, ?, 1)
            ON CONFLICT(admin_id)
            DO UPDATE SET
                message_id = excluded.message_id,
                is_active = 1
            """,
            (
                admin_id,
                message_id,
            ),
        )
        await db.commit()


async def deactivate_admin_notifications() -> None:

    async with connect_db() as db:
        await db.execute(
            """
            UPDATE support_admin_notifications
            SET is_active = 0
            WHERE is_active = 1
            """
        )
        await db.commit()
   
            
async def request_ticket_transfer(
    ticket_id: int,
    admin_id: int,
) -> tuple[str, int | None]:
    """
    Создаёт запрос на передачу тикета его текущему владельцу.
    admin_id — администратор, который хочет получить тикет.
    """

    if admin_id not in ADMIN_IDS:
        return "permission_denied", None

    timestamp = get_current_timestamp()

    async with connect_db() as db:
        await db.execute("BEGIN IMMEDIATE")

        try:
            async with db.execute(
                """
                SELECT status, assigned_admin_id
                FROM support_tickets
                WHERE ticket_id = ?
                """,
                (ticket_id,),
            ) as cursor:
                ticket = await cursor.fetchone()

            if ticket is None:
                await db.commit()
                return "ticket_not_found", None

            if ticket["status"] == "closed":
                await db.commit()
                return "closed_ticket", None

            owner_id = ticket["assigned_admin_id"]

            if owner_id is None:
                await db.commit()
                return "not_assigned", None

            if owner_id == admin_id:
                await db.commit()
                return "already_owner", None

            async with db.execute(
                """
                SELECT request_id
                FROM support_ticket_transfer_requests
                WHERE ticket_id = ?
                  AND status = 'pending'
                """,
                (ticket_id,),
            ) as cursor:
                pending = await cursor.fetchone()

            if pending is not None:
                await db.commit()
                return "transfer_pending", pending["request_id"]

            async with db.execute(
                """
                INSERT INTO support_ticket_transfer_requests (
                    ticket_id,
                    from_admin_id,
                    to_admin_id,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (
                    ticket_id,
                    admin_id,
                    owner_id,
                    timestamp,
                ),
            ) as cursor:
                request_id = cursor.lastrowid

            await db.commit()
            return "requested", request_id

        except Exception:
            await db.rollback()
            raise


async def respond_ticket_transfer(
    request_id: int,
    admin_id: int,
    decision: str,
) -> str:
    """
    Текущий владелец тикета принимает или отклоняет запрос.
    decision: accept / reject.
    """

    if admin_id not in ADMIN_IDS:
        return "permission_denied"

    if decision not in {"accept", "reject"}:
        raise ValueError("Недопустимое решение.")

    timestamp = get_current_timestamp()

    async with connect_db() as db:
        await db.execute("BEGIN IMMEDIATE")

        try:
            async with db.execute(
                """
                SELECT
                    request_id,
                    ticket_id,
                    from_admin_id,
                    to_admin_id,
                    status
                FROM support_ticket_transfer_requests
                WHERE request_id = ?
                """,
                (request_id,),
            ) as cursor:
                request = await cursor.fetchone()

            if request is None:
                await db.commit()
                return "request_not_found"

            if request["to_admin_id"] != admin_id:
                await db.commit()
                return "permission_denied"

            if request["status"] != "pending":
                await db.commit()
                return "request_not_pending"

            async with db.execute(
                """
                SELECT status, assigned_admin_id
                FROM support_tickets
                WHERE ticket_id = ?
                """,
                (request["ticket_id"],),
            ) as cursor:
                ticket = await cursor.fetchone()

            if ticket is None:
                await db.commit()
                return "ticket_not_found"

            if ticket["status"] == "closed":
                await db.execute(
                    """
                    UPDATE support_ticket_transfer_requests
                    SET status = 'cancelled',
                        responded_at = ?
                    WHERE request_id = ?
                      AND status = 'pending'
                    """,
                    (timestamp, request_id),
                )
                await db.commit()
                return "closed_ticket"

            if ticket["assigned_admin_id"] != admin_id:
                await db.commit()
                return "ownership_changed"

            if decision == "reject":
                await db.execute(
                    """
                    UPDATE support_ticket_transfer_requests
                    SET status = 'rejected',
                        responded_at = ?
                    WHERE request_id = ?
                      AND status = 'pending'
                    """,
                    (timestamp, request_id),
                )

                await db.commit()
                return "rejected"

            cursor = await db.execute(
                """
                UPDATE support_tickets
                SET assigned_admin_id = ?,
                    updated_at = ?
                WHERE ticket_id = ?
                  AND assigned_admin_id = ?
                  AND status IN ('open', 'in_progress')
                """,
                (
                    request["from_admin_id"],
                    timestamp,
                    request["ticket_id"],
                    admin_id,
                ),
            )

            if cursor.rowcount == 0:
                await db.rollback()
                return "transfer_failed"

            await db.execute(
                """
                UPDATE support_ticket_transfer_requests
                SET status = 'accepted',
                    responded_at = ?
                WHERE request_id = ?
                  AND status = 'pending'
                """,
                (timestamp, request_id),
            )

            await db.commit()
            return "accepted"

        except Exception:
            await db.rollback()
            raise


async def force_reassign_ticket(
    ticket_id: int,
    admin_id: int,
) -> str:
    """
    Только создатель проекта может принудительно
    переназначить активный тикет на себя.
    """

    if admin_id != CREATOR_ID or admin_id not in ADMIN_IDS:
        return "permission_denied"

    timestamp = get_current_timestamp()

    async with connect_db() as db:
        await db.execute("BEGIN IMMEDIATE")

        try:
            async with db.execute(
                """
                SELECT status, assigned_admin_id
                FROM support_tickets
                WHERE ticket_id = ?
                """,
                (ticket_id,),
            ) as cursor:
                ticket = await cursor.fetchone()

            if ticket is None:
                await db.commit()
                return "ticket_not_found"

            if ticket["status"] == "closed":
                await db.commit()
                return "closed_ticket"

            if ticket["assigned_admin_id"] is None:
                await db.commit()
                return "not_assigned"

            if ticket["assigned_admin_id"] == admin_id:
                await db.commit()
                return "already_owner"

            cursor = await db.execute(
                """
                UPDATE support_tickets
                SET assigned_admin_id = ?,
                    updated_at = ?
                WHERE ticket_id = ?
                  AND assigned_admin_id = ?
                  AND status IN ('open', 'in_progress')
                """,
                (
                    admin_id,
                    timestamp,
                    ticket_id,
                    ticket["assigned_admin_id"],
                ),
            )

            if cursor.rowcount == 0:
                await db.rollback()
                return "transfer_failed"

            await db.execute(
                """
                UPDATE support_ticket_transfer_requests
                SET status = 'cancelled',
                    responded_at = ?
                WHERE ticket_id = ?
                  AND status = 'pending'
                """,
                (timestamp, ticket_id),
            )

            await db.commit()
            return "transferred"

        except Exception:
            await db.rollback()
            raise


async def get_pending_ticket_transfers(
    admin_id: int,
    limit: int = 50,
) -> list:
    """
    Получает запросы на передачу тикетов,
    адресованные конкретному администратору.
    """

    if admin_id not in ADMIN_IDS:
        raise PermissionError(
            "Недостаточно прав."
        )

    if limit < 1:
        raise ValueError(
            "Лимит должен быть положительным."
        )

    async with connect_db() as db:
        async with db.execute(
            """
            SELECT
                r.request_id,
                r.ticket_id,
                r.from_admin_id,
                r.to_admin_id,
                r.created_at,
                t.user_id,
                t.category,
                t.status AS ticket_status
            FROM support_ticket_transfer_requests AS r
            JOIN support_tickets AS t
                ON t.ticket_id = r.ticket_id
            WHERE r.to_admin_id = ?
              AND r.status = 'pending'
              AND t.assigned_admin_id = ?
              AND t.status IN ('open', 'in_progress')
            ORDER BY r.created_at ASC, r.request_id ASC
            LIMIT ?
            """,
            (
                admin_id,
                admin_id,
                limit,
            ),
        ) as cursor:
            return await cursor.fetchall()    
            
                 
async def get_ticket_transfer_request(request_id: int):
    async with connect_db() as db:
        async with db.execute(
            """
            SELECT
                request_id,
                ticket_id,
                from_admin_id,
                to_admin_id,
                status,
                created_at,
                responded_at
            FROM support_ticket_transfer_requests
            WHERE request_id = ?
            """,
            (request_id,),
        ) as cursor:
            return await cursor.fetchone()     