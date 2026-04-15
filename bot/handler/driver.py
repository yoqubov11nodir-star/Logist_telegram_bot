from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, update
import datetime

from database.session import async_session
from database.models import User, UserRole, Order, OrderStatus, OrderMedia, OrderLocation
from bot.states.driver_states import DriverSteps
from bot.handler.logist import active_location_requests  # Taymerni boshqarish uchun

driver_router = Router()

# --- KLAVIATURALAR ---
def get_driver_main_keyboard():
    keyboard = [
        [KeyboardButton(text="🚚 Mening yuklarim")],
        [KeyboardButton(text="💳 Karta raqamim")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

async def get_telegram_id(user_id: int):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        u = result.scalar_one_or_none()
        return u.telegram_id if u else None

# --- HANDLERLAR ---

@driver_router.message(F.text == "🚚 Mening yuklarim")
async def view_driver_orders(message: Message, user: User):
    if user.role != UserRole.DRIVER:
        return

    async with async_session() as session:
        result = await session.execute(
            select(Order).where(Order.driver_id == user.id, Order.status != OrderStatus.COMPLETED)
        )
        orders = result.scalars().all()

    if not orders:
        await message.answer("Sizda faol buyurtmalar yo'q.")
        return

    for order in orders:
        kb = InlineKeyboardBuilder()
        
        if order.status == OrderStatus.DRIVER_ASSIGNED:
            kb.button(text="📍 A nuqtaga keldim", callback_data=f"st_arrived_a_{order.id}")
        elif order.status == OrderStatus.ARRIVED_A:
            kb.button(text="📸 Yuk ortildi (Media)", callback_data=f"st_load_media_{order.id}")
        elif order.status == OrderStatus.LOADED:
            kb.button(text="🚚 Yo'lga chiqdim", callback_data=f"st_on_way_{order.id}")
        elif order.status == OrderStatus.ON_WAY:
            kb.button(text="🏁 B nuqtaga keldim", callback_data=f"st_arrived_b_{order.id}")
        elif order.status == OrderStatus.ARRIVED_B:
            kb.button(text="📦 Yukni tushirdim (Media)", callback_data=f"st_unload_media_{order.id}")
        
        text = (
            f"📦 **Buyurtma #{order.id}**\n"
            f"📍 {order.point_a} -> {order.point_b}\n"
            f"📝 Yuk: {order.cargo_description}\n"
            f"📊 Holat: {order.status.value}"
        )
        await message.answer(text, reply_markup=kb.as_markup())

@driver_router.callback_query(F.data.startswith("st_arrived_a_"))
async def status_arrived_a(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[3])
    async with async_session() as session:
        result = await session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one()
        order.status = OrderStatus.ARRIVED_A
        await session.commit()
    await callback.message.edit_text(f"✅ Status: {OrderStatus.ARRIVED_A.value}. Yukni ortib media yuboring.")

@driver_router.callback_query(F.data.startswith("st_load_media_"))
async def start_load_media(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[3])
    await state.update_data(current_order_id=order_id, media_paths=[], stage="loading_a")
    await state.set_state(DriverSteps.waiting_for_media)
    await callback.message.answer("Iltimos, yuk ortilgani haqida 1 ta video va 2 ta rasm yuboring.")

@driver_router.message(DriverSteps.waiting_for_media, F.photo | F.video)
async def handle_media_upload(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data['current_order_id']
    stage = data['stage']
    media_paths = data.get('media_paths', [])

    file_id = message.photo[-1].file_id if message.photo else message.video.file_id
    m_type = "photo" if message.photo else "video"
    media_paths.append({"id": file_id, "type": m_type})
    await state.update_data(media_paths=media_paths)

    if len(media_paths) < 3:
        await message.answer(f"Qabul qilindi ({len(media_paths)}/3). Davom eting...")
    else:
        async with async_session() as session:
            for m in media_paths:
                session.add(OrderMedia(order_id=order_id, media_type=m['type'], file_path=m['id'], stage=stage))
            
            result = await session.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one()
            order.status = OrderStatus.UNLOADED if stage == "unloading_b" else OrderStatus.LOADED
            disp_id = order.dispatcher_id
            await session.commit()
            
            disp_tg_id = await get_telegram_id(disp_id)

        await message.answer("✅ Media qabul qilindi. Dispetcher tasdiqlashini kuting.")
        
        if disp_tg_id:
            kb = InlineKeyboardBuilder()
            kb.button(text="✅ Tasdiqlash", callback_data=f"approve_{stage}_{order_id}")
            kb.button(text="❌ Rad etish", callback_data=f"reject_{stage}_{order_id}")
            try:
                await message.bot.send_message(
                    chat_id=disp_tg_id, 
                    text=f"🔔 #{order_id} buyurtma media ({stage}) keldi.", 
                    reply_markup=kb.as_markup()
                )
            except Exception: pass
        await state.clear()

@driver_router.callback_query(F.data.startswith("st_on_way_"))
async def start_on_way(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[3])
    await state.update_data(current_order_id=order_id)
    await state.set_state(DriverSteps.waiting_for_location)
    await callback.message.answer("📍 Iltimos, 'Live Location' yuboring.")

@driver_router.message(DriverSteps.waiting_for_location, F.location)
async def handle_location(message: Message, state: FSMContext):
    state_data = await state.get_data()
    order_id = state_data['current_order_id']
    
    async with async_session() as session:
        result = await session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one()
        order.status = OrderStatus.ON_WAY
        
        session.add(OrderLocation(
            order_id=order_id, 
            latitude=message.location.latitude, 
            longitude=message.location.longitude
        ))
        await session.commit()

    # 🔥 TAYMERNI TO'XTATISH
    if order_id in active_location_requests:
        active_location_requests[order_id].set() 
    
    await message.answer("🚀 Oq yo'l! Holat: Yo'lda.", reply_markup=get_driver_main_keyboard())
    await state.clear()

@driver_router.callback_query(F.data.startswith("st_arrived_b_"))
async def status_arrived_b(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[3])
    async with async_session() as session:
        result = await session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one()
        order.status = OrderStatus.ARRIVED_B
        await session.commit()
    await callback.message.edit_text("🏁 Manzilga yetib keldingiz. Yukni tushirgach media yuboring.")

@driver_router.callback_query(F.data.startswith("st_unload_media_"))
async def start_unload_media(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[3])
    await state.update_data(current_order_id=order_id, media_paths=[], stage="unloading_b")
    await state.set_state(DriverSteps.waiting_for_media)
    await callback.message.answer("Iltimos, yuk tushirilgani haqida 1 ta video va 2 ta rasm yuboring.")

@driver_router.message(F.text == "💳 Karta raqamim")
async def request_card(message: Message, state: FSMContext):
    await message.answer("💳 To'lov uchun karta raqamingizni va ism-sharifingizni yuboring:")
    await state.set_state(DriverSteps.waiting_for_card)

@driver_router.message(DriverSteps.waiting_for_card)
async def save_card(message: Message, state: FSMContext, user: User):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user.id))
        db_user = result.scalar_one()
        db_user.card_number = message.text 
        await session.commit()
    await message.answer("✅ Karta raqamingiz saqlandi.")
    await state.clear()