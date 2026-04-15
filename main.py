import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties # 3-punkt uchun
from aiogram.enums import ParseMode                      # 3-punkt uchun
from dotenv import load_dotenv

from bot.handler.logist import logist_router
from bot.handler.dispatcher import dispatcher_router
from bot.handler.driver import driver_router # DRIVER routeri qo'shildi
from bot.middlewares.auth import AuthMiddleware
from database.base import Base
from database.session import engine

load_dotenv()

async def main():
    # 1. Ma'lumotlar bazasida jadvallarni yaratish
    async with engine.begin() as conn:
        from database.models import User, Order, OrderLocation, OrderMedia
        await conn.run_sync(Base.metadata.create_all)
    
    logging.basicConfig(level=logging.INFO)

    # 2. Bot ob'ektini yaratish (3-punkt: ParseMode shu yerda sozlanadi)
    bot = Bot(
        token=os.getenv("BOT_TOKEN"),
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )
    
    dp = Dispatcher()

    # 3. Middleware-larni ulash (2-punkt: Message va Callback uchun)
    # Bu handlerlar ishlashidan oldin foydalanuvchini bazadan topib beradi
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(AuthMiddleware())

    # 4. Routerlarni ulash
    dp.include_router(logist_router)
    dp.include_router(dispatcher_router)
    dp.include_router(driver_router) # DRIVER routeri zanjirga qo'shildi

    print("🚀 Bot ishlamoqda...")
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot to'xtatildi")