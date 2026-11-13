from aiogram.fsm.state import State, StatesGroup


class OsintSearchState(StatesGroup):
    waiting_for_phone = State()
    waiting_for_username = State()
    waiting_for_telegram_id = State()