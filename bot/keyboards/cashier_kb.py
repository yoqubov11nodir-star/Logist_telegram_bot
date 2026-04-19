from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_cashier_main_keyboard():
    keyboard = [
        [KeyboardButton(text="💰 To'lov kutilayotganlar")],
        [KeyboardButton(text="📈 Kunlik hisobot")]
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard, 
        resize_keyboard=True
    )