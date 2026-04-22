import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv
from sqlalchemy import select

from bot.handler.founder    import founder_router
from bot.handler.logist     import logist_router, logist_doc_router
from bot.handler.dispatcher import dispatcher_router
from bot.handler.driver     import driver_router
from bot.handler.cashier    import cashier_router
from bot.handler.client     import client_router

from bot.middlewares.auth   import AuthMiddleware
from database.models        import Base, User, UserRole
from database.session       import engine, async_session

load_dotenv()

FOUNDER_ID = int(os.getenv("FOUNDER_ID", 1687872138))

async def on_startup():
    logging.info("⏳ Ma'lumotlar bazasi tekshirilmoqda...")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with async_session() as session:
            founder = (
                await session.execute(select(User).where(User.telegram_id == FOUNDER_ID))
            ).scalar_one_or_none()

            if not founder:
                session.add(User(
                    telegram_id=FOUNDER_ID,
                    full_name="Founder",
                    role=UserRole.FOUNDER,
                ))
                logging.info("👤 Founder bazaga qo'shildi.")
            else:
                founder.role = UserRole.FOUNDER

            await session.commit()

        logging.info("✅ Baza tayyor!")
    except Exception as e:
        logging.error(f"❌ Startup xatosi: {e}")


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )

    await on_startup()

    bot = Bot(
        token=os.getenv("BOT_TOKEN"),
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            link_preview_is_disabled=True,
        ),
    )
    dp = Dispatcher()

    dp.message.outer_middleware(AuthMiddleware())
    dp.callback_query.outer_middleware(AuthMiddleware())

    # Routerlar (tartib muhim: logist_doc_router logist_router dan oldin)
    dp.include_router(founder_router)
    dp.include_router(logist_doc_router)
    dp.include_router(logist_router)
    dp.include_router(dispatcher_router)
    dp.include_router(driver_router)
    dp.include_router(cashier_router)
    dp.include_router(client_router)

    print("─" * 40)
    print("🚀 OMON Logistics Bot ishga tushdi!")
    print("─" * 40)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logging.error(f"Bot xatosi: {e}")
    finally:
        await bot.session.close()
        await engine.dispose()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("🛑 Bot to'xtatildi.")