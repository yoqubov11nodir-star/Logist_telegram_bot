from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

founder_main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Barcha buyurtmalar")],
        [KeyboardButton(text="💰 Foyda statistikasi")],
        [KeyboardButton(text="👥 Xodimlar faoliyati")]
    ],
    resize_keyboard=True
)