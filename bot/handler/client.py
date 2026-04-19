import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from database.session import async_session
from database.models import User, Order, OrderStatus, UserRole
from bot.keyboards.client_kb import get_client_main_keyboard

client_router = Router()

# 1. Mijoz menyusi (Start bossa yoki tasdiqlansa chiqishi uchun)
@client_router.message(F.text == "/start")
async def client_start(message: Message, user: User):
    if user.role == UserRole.CLIENT:
        await message.answer(
            "Xush kelibsiz, hurmatli Mijoz!", 
            reply_markup=get_client_main_keyboard()
        )

# 2. Buyurtmalar ro'yxati (Sizning kodingiz + yaxshilangan holat)
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

# 3. Lokatsiya so'rash (Sizning kodingiz)
@client_router.callback_query(F.data.startswith("ask_driver_loc_"))
async def client_trigger_location(callback: CallbackQuery):
    from bot.handler.logist import location_timer_logic
    order_id = int(callback.data.split("_")[3])
    
    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        driver = (await session.execute(select(User).where(User.id == order.driver_id))).scalar_one()
        logist = (await session.execute(select(User).where(User.id == order.logist_id))).scalar_one()
        disp = (await session.execute(select(User).where(User.id == order.dispatcher_id))).scalar_one()

    kb = InlineKeyboardBuilder()
    kb.button(text="📍 Lokatsiya yuborish", callback_data=f"act_on_way_{order_id}")
    
    try:
        await callback.bot.send_message(
            driver.telegram_id, 
            f"🔔 #{order_id} buyurtma bo'yicha mijoz lokatsiya so'ramoqda. Tezda yuboring!",
            reply_markup=kb.as_markup()
        )
        asyncio.create_task(location_timer_logic(
            order_id, callback.bot, driver.full_name, disp.telegram_id, logist.telegram_id
        ))
        await callback.answer("Haydovchidan lokatsiya so'raldi.")
    except:
        await callback.answer("Haydovchi bilan bog'lanib bo'lmadi.", show_alert=True)

# 4. Faktura tasdiqlash (Sizning kodingiz)
@client_router.callback_query(F.data.startswith("cl_confirm_inv_"))
async def finalize_payment_process(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[3])
    async with async_session() as session:
        cashier_res = await session.execute(select(User).where(User.role == UserRole.CASHIER))
        cashiers = cashier_res.scalars().all()
    
    for c in cashiers:
        if c.telegram_id:
            await callback.bot.send_message(
                c.telegram_id, 
                f"💰 **TO'LOV KUTILMOQDA!**\nMijoz #{order_id} buyurtma fakturasini tasdiqladi."
            )
    await callback.message.edit_caption(caption="✅ Faktura tasdiqlandi. Kassir to'lovni kutmoqda.")
    await callback.answer("Tasdiqlandi!")

# 5. Lokatsiya tugmasi uchun handler
@client_router.message(F.text == "📍 Yukim qayerda?")
async def where_is_my_cargo_general(message: Message):
    await message.answer("Lokatsiyani ko'rish uchun '📦 Buyurtmalarim' bo'limiga kiring va yo'ldagi yukingiz ostidagi '📍 Hozir qayerda?' tugmasini bosing.")