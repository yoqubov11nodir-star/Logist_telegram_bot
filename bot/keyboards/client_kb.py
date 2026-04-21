from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_client_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📦 Buyurtmalarim")],
            [KeyboardButton(text="📍 Yukim qayerda?")],
        ],
        resize_keyboard=True,
    )
