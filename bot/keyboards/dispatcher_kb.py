from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_dispatcher_main_keyboard():
    keyboard = [
        [KeyboardButton(text="📥 Yangi buyurtmalar")],
        [KeyboardButton(text="📊 Mening statistikam")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)