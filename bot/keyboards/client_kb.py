from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_client_main_keyboard():
    keyboard = [
        [KeyboardButton(text="📦 Buyurtmalarim")],
        [KeyboardButton(text="📍 Yukim qayerda?")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)