from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup

def get_logist_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Yangi buyurtma")],
            [KeyboardButton(text="📋 Buyurtmalarim"), KeyboardButton(text="📊 Statistika")]
        ],
        resize_keyboard=True
    )

def get_dispatchers_keyboard(dispatchers):
    builder = InlineKeyboardBuilder()
    for d in dispatchers:
        builder.button(text=f"👨‍💻 {d.full_name}", callback_data=f"assign_disp_{d.id}")
    builder.adjust(1)
    return builder.as_markup()