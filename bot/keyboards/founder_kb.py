from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

founder_main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Barcha buyurtmalar")],
        [KeyboardButton(text="💰 Foyda statistikasi")],
        [KeyboardButton(text="👥 Xodimlar faoliyati")],
    ],
    resize_keyboard=True,
)


def get_set_role_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Logist",     callback_data=f"set_role_LOGIST_{user_id}"),
                InlineKeyboardButton(text="🎧 Dispetcher", callback_data=f"set_role_DISPATCHER_{user_id}"),
            ],
            [
                InlineKeyboardButton(text="🚛 Haydovchi",  callback_data=f"set_role_DRIVER_{user_id}"),
                InlineKeyboardButton(text="💵 Kassir",     callback_data=f"set_role_CASHIER_{user_id}"),
            ],
            [
                InlineKeyboardButton(text="👤 Mijoz",      callback_data=f"set_role_CLIENT_{user_id}"),
            ],
        ]
    )
