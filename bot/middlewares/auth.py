import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy import select
from sqlalchemy import update

from database.session import async_session
from database.models import User, UserRole

FOUNDER_ID = 1687872138  # .env ga ko'chirish tavsiya etiladi


class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if not tg_user:
            return await handler(event, data)

        async with async_session() as session:
            res = await session.execute(
                select(User).where(User.telegram_id == tg_user.id)
            )
            user = res.scalar_one_or_none()

            if not user:
                # Yangi foydalanuvchi — bazaga qo'shish
                user = User(
                    telegram_id=tg_user.id,
                    full_name=tg_user.full_name or "Noma'lum",
                    username=tg_user.username,
                    role=UserRole.PENDING,
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)

                # Founderga xabar
                bot = data.get("bot")
                if bot:
                    from bot.keyboards.founder_kb import get_set_role_keyboard
                    try:
                        await bot.send_message(
                            chat_id=FOUNDER_ID,
                            text=(
                                f"🔔 <b>Yangi foydalanuvchi botga kirdi!</b>\n\n"
                                f"👤 Ism: {user.full_name}\n"
                                f"🆔 ID: <code>{user.telegram_id}</code>\n"
                                f"🔗 Username: @{user.username or 'Yo\'q'}\n\n"
                                f"Rol tayinlang:"
                            ),
                            reply_markup=get_set_role_keyboard(user.telegram_id),
                            parse_mode="HTML",
                        )
                    except Exception as e:
                        logging.error(f"Founderga xabar yuborishda xato: {e}")

        data["user"] = user
        return await handler(event, data)
