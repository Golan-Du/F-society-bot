import asyncio
from database.db import connect_db


async def main():
    async with connect_db() as db:
        async with db.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type IN ('table', 'index')
              AND (
                  name LIKE 'support_%'
                  OR name LIKE 'idx_support_%'
              )
            ORDER BY type, name
        """) as cursor:
            rows = await cursor.fetchall()

        for row in rows:
            print(row["name"])


asyncio.run(main())