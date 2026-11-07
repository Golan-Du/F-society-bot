import asyncio
import tempfile
from pathlib import Path

import database.db as db_module


async def main():
    original_db = db_module.DB_NAME

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_module.DB_NAME = str(Path(temp_dir) / "test.db")

            await db_module.init_db()

            # 1. Регистрация пригласившего
            first = await db_module.add_user_to_db(
                user_id=1001,
                username="referrer",
                full_name="Referrer"
            )

            # 2. Регистрация приглашённого
            second = await db_module.add_user_to_db(
                user_id=1002,
                username="invited",
                full_name="Invited",
                referrer_id=1001
            )

            # 3. Повторная регистрация
            duplicate = await db_module.add_user_to_db(
                user_id=1002,
                username="invited",
                full_name="Invited",
                referrer_id=1001
            )

            # 4. Попытка самореферала
            self_referral = await db_module.add_user_to_db(
                user_id=1003,
                username="self",
                full_name="Self",
                referrer_id=1003
            )

            # 5. Несуществующий пригласивший
            invalid_referral = await db_module.add_user_to_db(
                user_id=1004,
                username="invalid",
                full_name="Invalid",
                referrer_id=9999
            )

            # 6. Получение профилей
            referrer_profile = await db_module.get_user_profile(1001)
            invited_profile = await db_module.get_user_profile(1002)
            self_profile = await db_module.get_user_profile(1003)
            invalid_profile = await db_module.get_user_profile(1004)

            # 7. Извлечение значений
            invited_count = referrer_profile["invited_count"]

            self_referrer_id = await get_referrer_id(1003)
            invalid_referrer_id = await get_referrer_id(1004)
            invited_referrer_id = await get_referrer_id(1002)

            # 8. Проверки
            tests = {
                "New referrer": first is True,
                "New invited": second is True,
                "Duplicate registration": duplicate is False,
                "Referral counter": invited_count == 1,
                "Valid referrer": invited_referrer_id == 1001,
                "Self-referral blocked": self_referrer_id is None,
                "Invalid referrer blocked": invalid_referrer_id is None,
            }

            # 9. Результаты
            print("\n=== REGISTRATION TESTS ===")
            print("New referrer:", first)
            print("New invited:", second)
            print("Duplicate registration:", duplicate)

            print("\n=== REFERRAL TESTS ===")
            print("Invited referrer ID:", invited_referrer_id)
            print("Self referrer ID:", self_referrer_id)
            print("Invalid referrer ID:", invalid_referrer_id)
            print("Invited count:", invited_count)

            print("\n=== TEST RESULTS ===")

            for name, passed in tests.items():
                print(f"{'PASS' if passed else 'FAIL'}: {name}")

            print(
                f"\nTOTAL: {sum(tests.values())}/{len(tests)} passed"
            )

            assert all(tests.values()), "Some tests failed!"

    finally:
        db_module.DB_NAME = original_db


async def get_referrer_id(user_id: int):
    async with db_module.connect_db() as db:
        async with db.execute(
            "SELECT referrer_id FROM users WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            result = await cursor.fetchone()

            return result["referrer_id"] if result else None


if __name__ == "__main__":
    asyncio.run(main())
    