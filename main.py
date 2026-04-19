import asyncio
import logging
import os
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv
from sqlalchemy import update, select

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

MY_ID = 1687872138

async def on_startup():
    logging.info("⏳ Ma'lumotlar bazasi tekshirilmoqda...")
    try:
        # Jadvallarni yaratish
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        # Founder-ni tekshirish va yaratish
        async with async_session() as session:
            # select endi to'g'ri ishlaydi, tepada import qilingan
            stmt = select(User).where(User.telegram_id == MY_ID)
            res = await session.execute(stmt)
            founder = res.scalar_one_or_none()

            if not founder:
                founder = User(
                    telegram_id=MY_ID,
                    full_name="Founder Nodir",
                    role=UserRole.FOUNDER
                )
                session.add(founder)
                logging.info("👤 Founder bazaga yangi qo'shildi.")
            else:
                founder.role = UserRole.FOUNDER
                logging.info("✅ Founder allaqachon mavjud.")
            
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
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            link_preview_is_disabled=True  # GLOBAL REKLAMANI O'CHIRISH SHU YERDA
        )
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