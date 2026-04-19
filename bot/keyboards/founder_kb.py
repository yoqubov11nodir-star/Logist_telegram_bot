from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

founder_main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Barcha buyurtmalar")],
        [KeyboardButton(text="💰 Foyda statistikasi")],
        [KeyboardButton(text="👥 Xodimlar faoliyati")]
    ],
    resize_keyboard=True
)

# Yangi foydalanuvchi kelganda chiqadigan tugmalar
def get_set_role_keyboard(user_id: int):
    keyboard = [
        [
            InlineKeyboardButton(text="👨‍💼 Logist", callback_data=f"set_role_LOGIST_{user_id}"),
            InlineKeyboardButton(text="🎧 Dispetcher", callback_data=f"set_role_DISPATCHER_{user_id}")
        ],
        [
            InlineKeyboardButton(text="🚛 Haydovchi", callback_data=f"set_role_DRIVER_{user_id}"),
            InlineKeyboardButton(text="💰 Kassir", callback_data=f"set_role_CASHIER_{user_id}")
        ],
        [
            InlineKeyboardButton(text="👤 Mijoz (Client)", callback_data=f"set_role_CLIENT_{user_id}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)