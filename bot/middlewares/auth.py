from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from sqlalchemy import select
from database.session import async_session
from database.models import User, UserRole

class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # User obyekti Message yoki CallbackQuery ichidan olinadi
        tg_user = data.get("event_from_user")
        
        if not tg_user:
            return await handler(event, data)

        async with async_session() as session:
            # 1. Bazadan foydalanuvchini qidiramiz
            result = await session.execute(
                select(User).where(User.telegram_id == tg_user.id)
            )
            user = result.scalar_one_or_none()

            # 2. Agar foydalanuvchi bazada yo'q bo'lsa, uni yaratamiz
            if not user:
                user = User(
                    telegram_id=tg_user.id,
                    full_name=tg_user.full_name,
                    username=tg_user.username,
                    role=UserRole.PENDING  # Default rol
                )
                session.add(user)
                await session.commit()
                await session.refresh(user) # ID va boshqa ma'lumotlarni yangilash

            # 3. Handlerlarga 'user' obyektini uzatamiz
            data["user"] = user
            
            return await handler(event, data)