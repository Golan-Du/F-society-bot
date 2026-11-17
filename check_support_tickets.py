import asyncio
from database.db import connect_db


async def main():
    async with connect_db() as db:
        async with db.execute("""
            SELECT ticket_id, user_id, category, status, created_at
            FROM support_tickets
            ORDER BY ticket_id DESC
            LIMIT 5
        """) as cursor:
            tickets = await cursor.fetchall()

        for ticket in tickets:
            print("\nТикет:", dict(ticket))

            async with db.execute("""
                SELECT sender_id, sender_type, message_text, created_at
                FROM support_ticket_messages
                WHERE ticket_id = ?
                ORDER BY message_id ASC
            """, (ticket["ticket_id"],)) as cursor:
                messages = await cursor.fetchall()

            for message in messages:
                print("Сообщение:", dict(message))


asyncio.run(main())
