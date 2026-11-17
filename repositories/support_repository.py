from datetime import (
    datetime,
    timedelta,
    timezone,
)

from database.db import connect_db
from admin_config import ADMIN_IDS


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
            