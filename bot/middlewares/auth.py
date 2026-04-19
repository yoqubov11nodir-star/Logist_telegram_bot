from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from sqlalchemy import select
from database.session import async_session
from database.models import User, UserRole

# Founder keyboardini rolni tayinlash tugmalari uchun import qilamiz
from bot.keyboards.founder_kb import get_set_role_keyboard

class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        tg_user = data.get("event_from_user")
        if not tg_user:
            return await handler(event, data)

        async with async_session() as session:
            # Foydalanuvchini bazadan qidiramiz
            res = await session.execute(
                select(User).where(User.telegram_id == tg_user.id)
            )
            user = res.scalar_one_or_none()

            # 1. Agar foydalanuvchi bazada yo'q bo'lsa (yangi foydalanuvchi)
            if not user:
                user = User(
                    telegram_id=tg_user.id,
                    full_name=tg_user.full_name or "Noma'lum",
                    username=tg_user.username,
                    role=UserRole.PENDING
                )
                session.add(user)
                await session.commit()
                await session.refresh(user) # ID larni yangilab olish uchun

                # 2. Founderga xabar yuborish
                FOUNDER_ID = 1687872138  # Sizning ID raqamingiz
                bot = data.get("bot") # Bot obyektini data'dan olamiz
                
                try:
                    await bot.send_message(
                        chat_id=FOUNDER_ID,
                        text=(
                            f"🔔 **Yangi foydalanuvchi botga kirdi!**\n\n"
                            f"👤 Ismi: {user.full_name}\n"
                            f"🆔 ID: {user.telegram_id}\n"
                            f"🔗 Username: @{user.username if user.username else 'Yo\'q'}\n\n"
                            f"Ushbu foydalanuvchi tizimda foydalanishi uchun rol tayinlang:"
                        ),
                        reply_markup=get_set_role_keyboard(user.telegram_id)
                    )
                except Exception as e:
                    # Agar founderga xabar bormasa, logga yozamiz
                    import logging
                    logging.error(f"Founderga bildirishnoma yuborishda xato: {e}")

            # Foydalanuvchi ma'lumotlarini keyingi handlerlarga uzatamiz
            data["user"] = user
            return await handler(event, data)