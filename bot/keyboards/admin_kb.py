from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_admin_approve_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Logist",     callback_data=f"set_role_LOGIST_{user_id}")
    builder.button(text="🎧 Dispetcher", callback_data=f"set_role_DISPATCHER_{user_id}")
    builder.button(text="🚛 Haydovchi",  callback_data=f"set_role_DRIVER_{user_id}")
    builder.button(text="💵 Kassir",     callback_data=f"set_role_CASHIER_{user_id}")
    builder.button(text="👤 Mijoz",      callback_data=f"set_role_CLIENT_{user_id}")
    builder.adjust(2)
    return builder.as_markup()
