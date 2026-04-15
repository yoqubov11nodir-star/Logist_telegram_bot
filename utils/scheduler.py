from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database.session import async_session
from database.models import Order, User, UserRole
from sqlalchemy import select

scheduler = AsyncIOScheduler()

async def check_location_timeout(order_id: int, bot):
    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        
        # Agar hali ham lokatsiya tasdiqlanmagan bo'lsa
        if not order.location_confirmed: 
            # Logist va Dispetcherni topish
            staff = await session.execute(
                select(User).where(User.role.in_([UserRole.LOGIST, UserRole.DISPATCHER]))
            )
            for s in staff.scalars().all():
                try:
                    await bot.send_message(
                        s.telegram_id, 
                        f"🚨 **DIQQAT!** #{order_id}-buyurtma haydovchisi 15 daqiqadan beri lokatsiya yubormadi!"
                    )
                except: pass