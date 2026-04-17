import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from database.session import async_session
from database.models import User, Order, OrderStatus, UserRole

client_router = Router()

@client_router.message(F.text == "📦 Buyurtmalarim")
async def client_orders_list(message: Message, user: User):
    async with async_session() as session:
        result = await session.execute(
            select(Order).where(Order.client_phone == user.phone).order_by(Order.id.desc())
        )
        orders = result.scalars().all()
    
    if not orders:
        await message.answer("Sizda hali buyurtmalar mavjud emas.")
        return

    for o in orders:
        kb = InlineKeyboardBuilder()
        if o.status == OrderStatus.ON_WAY:
            kb.button(text="📍 Hozir qayerda?", callback_data=f"ask_driver_loc_{o.id}")
        
        msg = f"🆔 **Buyurtma: #{o.id}**\n" \
              f"📦 Yuk: {o.cargo_description}\n" \
              f"🚚 Status: {o.status.value}\n" \
              f"📍 Yo'nalish: {o.point_a} -> {o.point_b}"
        
        await message.answer(msg, reply_markup=kb.as_markup() if kb.as_markup().inline_keyboard else None)

@client_router.callback_query(F.data.startswith("ask_driver_loc_"))
async def client_trigger_location(callback: CallbackQuery):
    from bot.handler.logist import location_timer_logic
    order_id = int(callback.data.split("_")[3])
    
    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        driver = (await session.execute(select(User).where(User.id == order.driver_id))).scalar_one()
        logist = (await session.execute(select(User).where(User.id == order.logist_id))).scalar_one()
        disp = (await session.execute(select(User).where(User.id == order.dispatcher_id))).scalar_one()

    # Haydovchiga so'rov yuborish
    kb = InlineKeyboardBuilder()
    kb.button(text="📍 Lokatsiya yuborish", callback_data=f"act_on_way_{order_id}")
    
    await callback.bot.send_message(
        driver.telegram_id, 
        f"🔔 #{order_id} buyurtma bo'yicha mijoz lokatsiya so'ramoqda. Tezda yuboring!",
        reply_markup=kb.as_markup()
    )
    
    # 15 daqiqalik nazorat taymerini yoqish
    asyncio.create_task(location_timer_logic(
        order_id, callback.bot, driver.full_name, disp.telegram_id, logist.telegram_id
    ))
    
    await callback.answer("Haydovchidan lokatsiya so'raldi. 15 daqiqa ichida yubormasa, adminlar ogohlantiriladi.")

@client_router.callback_query(F.data.startswith("cl_confirm_inv_"))
async def finalize_payment_process(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[3])
    
    async with async_session() as session:
        cashier_res = await session.execute(select(User).where(User.role == UserRole.CASHIER))
        cashiers = cashier_res.scalars().all()
    
    # Kassirlarni ogohlantirish
    for c in cashiers:
        if c.telegram_id:
            await callback.bot.send_message(
                c.telegram_id, 
                f"💰 **TO'LOV KUTILMOQDA!**\nMijoz #{order_id} buyurtma fakturasini tasdiqladi. To'lovni qabul qiling."
            )
    
    await callback.message.edit_caption(caption="✅ Faktura tasdiqlandi. To'lov amalga oshirilgach, kassir tasdiqlaydi.")
    await callback.answer("Rahmat, tasdiqlandi!")

