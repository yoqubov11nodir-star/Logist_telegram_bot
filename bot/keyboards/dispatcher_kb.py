from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_dispatcher_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📥 Yangi buyurtmalar")],
            [KeyboardButton(text="📊 Mening statistikam")],
        ],
        resize_keyboard=True,
    )
