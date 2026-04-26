import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy import select

from database.session import async_session
from database.models import User, UserRole


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
                user = User(
                    telegram_id=tg_user.id,
                    full_name=tg_user.full_name or "Noma'lum",
                    username=tg_user.username,
                    role=UserRole.PENDING,
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)
                # Founder notification is sent after user submits phone (handle_contact)

        data["user"] = user
        return await handler(event, data)
