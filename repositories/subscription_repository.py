from datetime import (
    datetime,
    timedelta,
    timezone
)

from database.db import connect_db


MSK = timezone(
    timedelta(hours=3)
)


ALLOWED_NOTIFICATION_TYPES = {
    "vpn",
    "osint"
}


def get_current_timestamp() -> str:
    return datetime.now(MSK).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


async def subscribe_user(
    user_id: int,
    notification_type: str
) -> str:

    if (
        notification_type
        not in ALLOWED_NOTIFICATION_TYPES
    ):
        raise ValueError(
            "Недопустимый тип уведомлений."
        )

    now = get_current_timestamp()

    async with connect_db() as db:
        async with db.execute(
            """
            SELECT is_active
            FROM user_subscriptions
            WHERE user_id = ?
            AND notification_type = ?
            """,
            (
                user_id,
                notification_type
            )
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            await db.execute(
                """
                INSERT INTO user_subscriptions (
                    user_id,
                    notification_type,
                    is_active,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, 1, ?, ?)
                """,
                (
                    user_id,
                    notification_type,
                    now,
                    now
                )
            )

            await db.commit()

            return "new"

        if bool(row["is_active"]):
            return "already_active"

        await db.execute(
            """
            UPDATE user_subscriptions
            SET
                is_active = 1,
                updated_at = ?
            WHERE user_id = ?
            AND notification_type = ?
            """,
            (
                now,
                user_id,
                notification_type
            )
        )

        await db.commit()

        return "reactivated"


async def unsubscribe_user(
    user_id: int,
    notification_type: str
) -> bool:

    if (
        notification_type
        not in ALLOWED_NOTIFICATION_TYPES
    ):
        raise ValueError(
            "Недопустимый тип уведомлений."
        )

    now = get_current_timestamp()

    async with connect_db() as db:
        cursor = await db.execute(
            """
            UPDATE user_subscriptions
            SET
                is_active = 0,
                updated_at = ?
            WHERE user_id = ?
            AND notification_type = ?
            AND is_active = 1
            """,
            (
                now,
                user_id,
                notification_type
            )
        )

        await db.commit()

        return cursor.rowcount == 1


async def get_subscribers(
    notification_type: str
) -> list[int]:

    if (
        notification_type
        not in ALLOWED_NOTIFICATION_TYPES
    ):
        raise ValueError(
            "Недопустимый тип уведомлений."
        )

    async with connect_db() as db:
        async with db.execute(
            """
            SELECT user_id
            FROM user_subscriptions
            WHERE notification_type = ?
            AND is_active = 1
            """,
            (notification_type,)
        ) as cursor:
            rows = await cursor.fetchall()

            return [
                row["user_id"]
                for row in rows
            ]


async def get_user_subscriptions(
    user_id: int
) -> dict[str, bool]:

    subscriptions = {
        notification_type: False
        for notification_type
        in ALLOWED_NOTIFICATION_TYPES
    }

    async with connect_db() as db:
        async with db.execute(
            """
            SELECT
                notification_type,
                is_active
            FROM user_subscriptions
            WHERE user_id = ?
            """,
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()

    for row in rows:
        notification_type = row[
            "notification_type"
        ]

        if (
            notification_type
            in subscriptions
        ):
            subscriptions[
                notification_type
            ] = bool(
                row["is_active"]
            )

    return subscriptions
            