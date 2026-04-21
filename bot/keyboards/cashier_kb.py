from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_cashier_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💰 To'lov kutilayotganlar")],
        ],
        resize_keyboard=True,
    )
