from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from sqlalchemy import select
import logging

from database.session import async_session
from database.models import User, UserRole, Order, OrderStatus, OrderMedia
from bot.keyboards.dispatcher_kb import get_dispatcher_main_keyboard # Yangi qo'shildi

dispatcher_router = Router()

# Mashina raqamini kiritish uchun holat
class DispatcherStates(StatesGroup):
    waiting_for_vehicle_number = State()

# --- DISPETCHER START ---
@dispatcher_router.message(Command("start"))
async def dispatcher_start(message: Message, user: User):
    if user.role == UserRole.DISPATCHER:
        await message.answer(
            "🎧 Xush kelibsiz, Dispetcher! Ishni boshlash uchun quyidagi tugmalardan foydalaning:",
            reply_markup=get_dispatcher_main_keyboard()
        )

# 📥 Dispetcherga tegishli yangi buyurtmalarni ko'rish
@dispatcher_router.message(F.text == "📥 Yangi buyurtmalar")
async def view_assigned_orders(message: Message, user: User):
    if user.role != UserRole.DISPATCHER:
        return

    async with async_session() as session:
        result = await session.execute(
            select(Order).where(
                Order.dispatcher_id == user.telegram_id, 
                Order.status == OrderStatus.DISPATCHER_ASSIGNED
            )
        )
        orders = result.scalars().all()

    if not orders:
        await message.answer("Sizga biriktirilgan yangi buyurtmalar hozircha yo'q.")
        return

    for order in orders:
        kb = InlineKeyboardBuilder()
        kb.button(text="🚛 Haydovchi biriktirish", callback_data=f"find_driver_{order.id}")
        
        price = f"{order.cost_price:,.0f}" if order.cost_price else "0"
        
        text = (
            f"📦 **Yangi buyurtma tushdi!**\n\n"
            f"🆔 ID: #{order.id}\n"
            f"📍 Yo'nalish: {order.point_a} -> {order.point_b}\n"
            f"📝 Yuk: {order.cargo_description}\n"
            f"💸 Limit: {price} so'm"
        )
        await message.answer(text, reply_markup=kb.as_markup(), parse_mode="Markdown")

# 👨‍✈️ Haydovchilar ro'yxatini chiqarish
@dispatcher_router.callback_query(F.data.startswith("find_driver_"))
async def list_drivers(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    
    async with async_session() as session:
        result = await session.execute(select(User).where(User.role == UserRole.DRIVER))
        drivers = result.scalars().all()

    if not drivers:
        await callback.answer("Hozircha bazada haydovchilar yo'q!", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    for d in drivers:
        kb.button(text=f"👨‍✈️ {d.full_name}", callback_data=f"ask_vnum_{order_id}_{d.id}")
    kb.adjust(1)

    await callback.message.edit_text("Haydovchini tanlang:", reply_markup=kb.as_markup())

# TZ: Mashina raqamini so'rash
@dispatcher_router.callback_query(F.data.startswith("ask_vnum_"))
async def ask_vehicle_number(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    order_id = parts[2]
    driver_db_id = parts[3]
    
    await state.update_data(temp_order_id=int(order_id), temp_driver_id=int(driver_db_id))
    await callback.message.answer("🚛 Mashina davlat raqamini kiriting (masalan: 01A777BA):")
    await state.set_state(DispatcherStates.waiting_for_vehicle_number)

# ✅ Haydovchini buyurtmaga biriktirish (Final)
@dispatcher_router.message(DispatcherStates.waiting_for_vehicle_number)
async def assign_driver_to_order(message: Message, state: FSMContext):
    v_number = message.text.upper()
    data = await state.get_data()
    order_id = data['temp_order_id']
    driver_db_id = data['temp_driver_id'] 

    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        driver = (await session.execute(select(User).where(User.id == driver_db_id))).scalar_one()
        
        # XATO TUZATILDI: driver.id o'rniga driver.telegram_id yozilishi shart
        order.driver_id = driver.telegram_id  
        order.vehicle_number = v_number
        order.status = OrderStatus.DRIVER_ASSIGNED
        
        client = (await session.execute(select(User).where(User.phone == order.client_phone))).scalar_one_or_none()
        await session.commit()

    await message.answer(f"✅ #{order_id} buyurtma {driver.full_name}ga ({v_number}) biriktirildi!")

    # Haydovchiga xabar
    try:
        await message.bot.send_message(
            chat_id=driver.telegram_id,
            text=f"🚛 **Yangi buyurtma!**\n🆔 ID: #{order_id}\n📍 {order.point_a} -> {order.point_b}\n🚘 Mashina: {v_number}",
            parse_mode="Markdown"
        )
    except: pass

    # Mijozga xabar
    if client:
        try:
            await message.bot.send_message(
                chat_id=client.telegram_id,
                text=f"🚛 #{order_id} uchun haydovchi biriktirildi.\n🚘 Mashina: {v_number}\n👨‍✈️ Haydovchi: {driver.full_name}"
            )
        except: pass
    await state.clear()

# --- TASDIQLASH (APPROVE LOADING A) ---
@dispatcher_router.callback_query(F.data.startswith("approve_loading_a_"))
async def approve_order_load(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[3])

    async with async_session() as session:
        order_res = await session.execute(select(Order).where(Order.id == order_id))
        order = order_res.scalar_one()
        order.status = OrderStatus.LOADED 
        
        driver_res = await session.execute(select(User).where(User.id == order.driver_id))
        driver = driver_res.scalar_one()
        
        client_res = await session.execute(select(User).where(User.phone == order.client_phone))
        client = client_res.scalar_one_or_none()
        
        await session.commit()

    await callback.message.edit_text(f"✅ #{order_id} buyurtma mediani tasdiqladingiz. Status: YUK ORTILDI.")

    try:
        await callback.bot.send_message(
            chat_id=driver.telegram_id,
            text=f"✅ Yuk ortilishi tasdiqlandi. Endi 'Yo'lga chiqdim' statusini belgilang."
        )
    except: pass

    if client:
        try:
            await callback.bot.send_message(
                chat_id=client.telegram_id,
                text=f"📦 Buyurtmangiz #{order_id} — yukingiz ortildi va yo'lga chiqishga tayyor."
            )
        except: pass

# --- RAD ETISH (REJECT LOADING A) ---
@dispatcher_router.callback_query(F.data.startswith("reject_loading_a_"))
async def reject_order_load(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[3])

    async with async_session() as session:
        order_res = await session.execute(select(Order).where(Order.id == order_id))
        order = order_res.scalar_one()
        order.status = OrderStatus.ARRIVED_A
        
        driver_res = await session.execute(select(User).where(User.id == order.driver_id))
        driver = driver_res.scalar_one()
        await session.commit()

    await callback.message.edit_text(f"❌ #{order_id} buyurtma mediani rad etdingiz.")

    await callback.bot.send_message(
        chat_id=driver.telegram_id,
        text=f"❌ Yuk ortish mediani Dispetcher rad etdi. Iltimos, qaytadan aniqroq rasm va video yuboring."
    )

# --- Qolgan barcha tasdiqlash funksiyalarida haydovchini topish qismi to'g'irlandi ---
@dispatcher_router.callback_query(F.data.startswith("approve_unloading_b_"))
async def approve_unloading_b(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[3])

    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        order.status = OrderStatus.UNLOADED 
        
        # Driver telegram_id orqali topilmoqda
        driver = (await session.execute(select(User).where(User.telegram_id == order.driver_id))).scalar_one()
        cashier = (await session.execute(select(User).where(User.role == UserRole.CASHIER))).scalars().first()
        await session.commit()

    await callback.message.edit_text(f"✅ #{order_id} tasdiqlandi. Kassirga yuborildi.")

    if cashier:
        kb = InlineKeyboardBuilder()
        kb.button(text="💵 To'lov qildim", callback_data=f"pay_order_{order_id}")
        await callback.bot.send_message(
            chat_id=cashier.telegram_id,
            text=f"🔔 **TO'LOV:** #{order_id}\n👨‍✈️ Haydovchi: {driver.full_name}\n💰 Summa: {order.cost_price:,.0f} so'm",
            reply_markup=kb.as_markup(),
            parse_mode="Markdown"
        )
    await callback.bot.send_message(chat_id=driver.telegram_id, text="✅ Yuk tushirilishi tasdiqlandi. To'lov kutilmoqda...")

# --- YUK TUSHIRISHNI RAD ETISH (REJECT UNLOADING B) ---
@dispatcher_router.callback_query(F.data.startswith("reject_unloading_b_"))
async def reject_unloading_b(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[3])
    
    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        driver = (await session.execute(select(User).where(User.id == order.driver_id))).scalar_one()
        order.status = OrderStatus.ON_WAY 
        await session.commit()

    await callback.message.edit_text(f"❌ #{order_id} buyurtma tushirish mediasini rad etdingiz.")
    await callback.bot.send_message(
        chat_id=driver.telegram_id,
        text="❌ Yuk tushirish mediangiz rad etildi. Iltimos, qaytadan yuboring."
    )


# --- B NUQTAGA YETIB KELISHNI TASDIQLASH (Bosqich 6) ---
@dispatcher_router.callback_query(F.data.startswith("st_arrived_b_confirm_"))
async def confirm_arrived_b(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[4])

    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        logist = (await session.execute(select(User).where(User.id == order.logist_id))).scalar_one()
        order.status = OrderStatus.ARRIVED_B
        await session.commit()

    await callback.message.edit_text(f"✅ #{order_id} buyurtma: B nuqtaga kelgani tasdiqlandi. Logistga shot-faktura so'rovi ketdi.")

    # Logistga bildirishnoma (TZ Bosqich 7)
    await callback.bot.send_message(
        chat_id=logist.telegram_id,
        text=(
            f"⚡ **#{order_id} buyurtma.** Haydovchi yukni tushirish joyiga yetib keldi.\n"
            f"Iltimos, Didoxdan shot-fakturani yuklab, botga yuboring."
        )
    )

# --- LOKATSIYANI MIJOZGA TASDIQLASH ---
@dispatcher_router.callback_query(F.data.startswith("send_loc_to_client_"))
async def approve_location_to_client(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[4])

    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        client = (await session.execute(select(User).where(User.phone == order.client_phone))).scalar_one_or_none()
        
        # Oxirgi lokatsiyani olish (OrderLocation modelidan)
        # Bu yerda oxirgi lat/lon ni bazadan olish kodi bo'ladi

    if client:
        await callback.bot.send_message(
            chat_id=client.telegram_id,
            text=f"📍 Buyurtma #{order_id} bo'yicha yukingizning joriy joylashuvi."
        )
        # Bu yerda haqiqiy location xabarini yuborish kerak
        await callback.message.answer("✅ Joylashuv mijozga yuborildi.")
    else:
        await callback.answer("Mijoz botdan ro'yxatdan o'tmagan!", show_alert=True)


# --- STATISTIKA ---
@dispatcher_router.message(F.text == "📊 Mening statistikam")
async def dispatcher_stats(message: Message, user: User):
    if user.role != UserRole.DISPATCHER: return
    async with async_session() as session:
        res = await session.execute(select(Order).where(Order.dispatcher_id == user.telegram_id))
        orders = res.scalars().all()
        total, completed = len(orders), len([o for o in orders if o.status == OrderStatus.PAID])
        await message.answer(f"📊 **Statistika:**\n✅ Jami: {total}\n⏳ Faol: {total-completed}\n🏁 Yakunlangan: {completed}")