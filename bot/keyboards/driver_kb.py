from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_driver_main_keyboard():
    keyboard = [
        [KeyboardButton(text="🚛 Mening buyurtmalarim")],
        [KeyboardButton(text="📊 Statistika")]
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard, 
        resize_keyboard=True,
        one_time_keyboard=False
    )