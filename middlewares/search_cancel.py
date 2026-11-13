from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from handlers.osint import (
    OsintSearchState,
    cancel_search_timer,
)
from handlers.subscriptions import BroadcastState


class SearchCancelMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[
            [Message, dict[str, Any]],
            Awaitable[Any],
        ],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if not event.text:
            return await handler(event, data)

        if not event.text.startswith("/"):
            return await handler(event, data)

        command = event.text.split()[0].split("@")[0]

        if command == "/cancel":
            return await handler(event, data)

        state: FSMContext | None = data.get("state")

        if state is None:
            return await handler(event, data)

        current_state = await state.get_state()

        cancellable_states = {
            OsintSearchState.waiting_for_phone.state,
            OsintSearchState.waiting_for_username.state,
            OsintSearchState.waiting_for_telegram_id.state,
            BroadcastState.waiting_for_type.state,
            BroadcastState.waiting_for_text.state,
        }

        if current_state in cancellable_states:
            user = event.from_user

            if user is not None:
                await cancel_search_timer(user.id)

            await state.clear()

        return await handler(event, data)
        