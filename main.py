import asyncio
import logging
import os
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv
from sqlalchemy import update

# Routerlarni import qilish
from bot.handler.founder import founder_router 
from bot.handler.logist import logist_router, logist_doc_router # doc_router qo'shildi
from bot.handler.dispatcher import dispatcher_router
from bot.handler.driver import driver_router
from bot.handler.cashier import cashier_router
from bot.handler.client import client_router # client_router qo'shildi

# Middleware va Baza komponentlari
from bot.middlewares.auth import AuthMiddleware
from database.models import Base, User, UserRole
from database.session import engine, async_session

# .env faylini yuklash
load_dotenv()

async def on_startup():
    """Bot ishga tushganda bazani tayyorlash va adminni tayinlash"""
    logging.info("⏳ Ma'lumotlar bazasi tekshirilmoqda...")
    try:
        # 1. Jadvallarni yaratish
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        # 2. Founder rolingni bazada yangilash
        async with async_session() as session:
            stmt = (
                update(User)
                .where(User.telegram_id == 1687872138)
                .values(role=UserRole.FOUNDER)
            )
            await session.execute(stmt)
            await session.commit()
            
        logging.info("✅ Baza tayyor va Founder roli tasdiqlandi!")
    except Exception as e:
        logging.error(f"❌ Startup xatosi: {e}")

async def main():
    # Loglarni sozlash
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout
    )

    # 1. Startup funksiyasini chaqirish
    await on_startup()

    # 2. Bot va Dispatcher
    bot = Bot(
        token=os.getenv("BOT_TOKEN"),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # 3. Middleware ulanishi
    dp.message.outer_middleware(AuthMiddleware())
    dp.callback_query.outer_middleware(AuthMiddleware())

    # 4. Routerlarni ulash (Tartib muhim)
    dp.include_router(founder_router)
    dp.include_router(logist_router)
    dp.include_router(logist_doc_router) # Shot-faktura uchun router
    dp.include_router(dispatcher_router)
    dp.include_router(driver_router)
    dp.include_router(cashier_router)
    dp.include_router(client_router) # Mijoz routeri

    print("-" * 30)
    print("🚀 Logistic Bot muvaffaqiyatli ishga tushdi!")
    print("-" * 30)
    
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logging.error(f"Bot ishlashida kutilmagan xato: {e}")
    finally:
        await bot.session.close()
        await engine.dispose()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("🛑 Bot to'xtatildi")