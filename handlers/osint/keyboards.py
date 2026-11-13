from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)


def get_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back_to_main",
                )
            ]
        ]
    )


def get_search_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📱 По номеру телефона",
                    callback_data="osint_phone",
                )
            ],
            [
                InlineKeyboardButton(
                    text="👤 По username",
                    callback_data="osint_username",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🆔 По Telegram ID",
                    callback_data="osint_telegram_id",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back_to_main",
                )
            ],
        ]
    )


def get_result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Повторить поиск",
                    callback_data="osint_repeat",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔎 Другой тип поиска",
                    callback_data="osint_scan",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Главное меню",
                    callback_data="back_to_main",
                )
            ],
        ]
    )