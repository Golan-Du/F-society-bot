from enum import Enum

from aiogram.fsm.state import State, StatesGroup
from aiogram.filters.callback_data import CallbackData


class OsintAction(str, Enum):
    SELECT = "select"


class OsintTargetType(str, Enum):
    USERNAME = "username"
    PHONE = "phone"
    ID = "id"


class OsintSearch(StatesGroup):
    waiting_for_target_type = State()
    waiting_for_target_value = State()


class OsintCallbackFactory(CallbackData, prefix="osint"):
    action: OsintAction
    target_type: OsintTargetType
    