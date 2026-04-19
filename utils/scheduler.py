from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database.session import async_session
from database.models import Order, User, UserRole
from sqlalchemy import select

scheduler = AsyncIOScheduler()

async def check_location_timeout(order_id: int, bot):
    async with async_session() as session:
        result = await session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        
        if order and not order.location_confirmed: 
            staff_res = await session.execute(
                select(User).where(User.role.in_([UserRole.LOGIST, UserRole.DISPATCHER]))
            )
            staff = staff_res.scalars().all()
            for s in staff:
                try:
                    await bot.send_message(
                        s.telegram_id, 
                        f"🚨 #{order_id}-buyurtma haydovchisi 15 daqiqadan beri lokatsiya yubormadi!"
                    )
                except: continue