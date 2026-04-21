from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_driver_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚚 Mening yuklarim")],
            [KeyboardButton(text="💳 Karta va ma'lumotlarim")],
        ],
        resize_keyboard=True,
    )
