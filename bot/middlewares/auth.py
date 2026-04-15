from aiogram import BaseMiddleware
from aiogram.types import Message
from typing import Callable, Dict, Any, Awaitable
from database.session import async_session
from database.models import User
from sqlalchemy import select

class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user_id = event.from_user.id
        async with async_session() as session:
            # Foydalanuvchini bazadan qidirish
            user = await session.execute(select(User).where(User.telegram_id == user_id))
            user = user.scalar_one_or_none()
            
            # MUHIM: Foydalanuvchi bo'lmasa ham handlerni davom ettirish kerak
            # Aks holda /start handleri yangi foydalanuvchini bazaga qo'sha olmaydi
            data["user"] = user 
            return await handler(event, data)