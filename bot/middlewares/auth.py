from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy import select
from database.session import async_session
from database.models import User, UserRole, Order

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
            # 1. Bazadan foydalanuvchini qidirish
            result = await session.execute(
                select(User).where(User.telegram_id == tg_user.id)
            )
            user = result.scalar_one_or_none()

            # 2. Yangi user bo'lsa yaratish
            if not user:
                user = User(
                    telegram_id=tg_user.id,
                    full_name=tg_user.full_name,
                    username=tg_user.username,
                    role=UserRole.PENDING
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)

            # 3. Agar raqami bor bo'lsa va hali PENDING bo'lsa, MIJOZligini tekshirish
            if user.role == UserRole.PENDING and user.phone:
                order_check = await session.execute(
                    select(Order).where(Order.client_phone == user.phone).limit(1)
                )
                if order_check.scalar_one_or_none():
                    user.role = UserRole.CLIENT
                    await session.commit()

            data["user"] = user
            return await handler(event, data)