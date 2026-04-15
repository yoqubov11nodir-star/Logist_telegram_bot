import asyncio
import re
import datetime
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, update, func

from database.session import async_session
from database.models import Order, OrderStatus, User, UserRole, OrderLocation
from bot.states.order_states import OrderCreation
from bot.states.logist_states import LogistSteps
from bot.keyboards.logist_kb import get_logist_main_keyboard, get_dispatchers_keyboard
from bot.keyboards.dispatcher_kb import get_dispatcher_main_keyboard

logist_router = Router()

# Global lug'at taymerlarni boshqarish uchun (Memory-based)
active_location_requests = {} 

# --- TAYMER MANTIQI: 15 DAQIQALIK NAZORAT ---
async def location_timer_logic(order_id: int, bot: Bot, driver_name: str, disp_tg_id: int, logist_tg_id: int):
    """Haydovchi 15 daqiqa ichida lokatsiya yubormasa ogohlantirish beradi"""
    stop_event = asyncio.Event()
    active_location_requests[order_id] = stop_event
    
    try:
        # 15 daqiqa (900 soniya) kutadi
        await asyncio.wait_for(stop_event.wait(), timeout=900)
        # Agar haydovchi lokatsiya yuborsa, .set() bo'ladi va bu yerga tushadi
    except asyncio.TimeoutError:
        # 15 daqiqa o'tdi, lekin haydovchi lokatsiya yubormadi
        alert_text = (
            f"🚨 **DIQQAT! OGOHLANTIRISH!**\n\n"
            f"Haydovchi: **{driver_name}**\n"
            f"Buyurtma: **#{order_id}**\n"
            f"Holat: 15 daqiqadan beri joylashuv yuborilmadi! Iltimos, haydovchi bilan bog'laning."
        )
        # Dispetcherga yuborish
        try:
            await bot.send_message(chat_id=disp_tg_id, text=alert_text, parse_mode="Markdown")
        except: pass
        # Logistga yuborish
        try:
            await bot.send_message(chat_id=logist_tg_id, text=alert_text, parse_mode="Markdown")
        except: pass
    finally:
        # Jarayon tugagach lug'atdan tozalash
        if order_id in active_location_requests:
            active_location_requests.pop(order_id)

# --- START KOMANDASI (FOYDALANUVCHILARNI SARALASH) ---
@logist_router.message(F.text == "/start")
async def cmd_start(message: Message, user: User = None):
    # 1. Foydalanuvchi bazada yo'q bo'lsa
    if not user:
        async with async_session() as session:
            new_user = User(
                telegram_id=message.from_user.id,
                full_name=message.from_user.full_name,
                role=UserRole.PENDING
            )
            session.add(new_user)
            await session.commit()
        
        await message.answer(
            f"Assalomu alaykum! Siz tizimda ro'yxatdan o'tmagansiz.\n"
            f"Adminga murojaat qiling va ID raqamingizni bering:\n"
            f"Sizning ID: `{message.from_user.id}`"
        )
        return

    # 2. Foydalanuvchi kutilmoqda holatida bo'lsa
    if user.role == UserRole.PENDING:
        await message.answer(
            f"Sizning so'rovingiz hali tasdiqlanmagan.\n"
            f"Iltimos, admin javobini kuting.\n"
            f"Sizning ID: `{message.from_user.id}`"
        )
        return

    # 3. Foydalanuvchi roliga qarab menyu chiqarish
    if user.role == UserRole.LOGIST:
        await message.answer(
            f"Xush kelibsiz, Logist {user.full_name}!", 
            reply_markup=get_logist_main_keyboard()
        )
    elif user.role == UserRole.DISPATCHER:
        await message.answer(
            f"Xush kelibsiz, Dispetcher {user.full_name}!", 
            reply_markup=get_dispatcher_main_keyboard()
        )
    elif user.role == UserRole.DRIVER:
        await message.answer(f"Xush kelibsiz, Haydovchi {user.full_name}!")
    else:
        await message.answer(f"Xush kelibsiz, {user.full_name}!\nSizning rolingiz: {user.role.value}")

# --- BUYURTMALAR RO'YXATI ---
@logist_router.message(F.text == "📋 Buyurtmalarim")
async def my_orders(message: Message):
    async with async_session() as session:
        result = await session.execute(
            select(Order).order_by(Order.id.desc()).limit(10)
        )
        orders = result.scalars().all()
        
        if not orders:
            await message.answer("Hozircha tizimda buyurtmalar mavjud emas.")
            return
            
        text = "📋 **Oxirgi 10 ta buyurtma:**\n\n"
        for o in orders:
            text += f"🆔 **#{o.id}** | {o.point_a} ➔ {o.point_b}\n" \
                    f"📊 Status: `{o.status.value}`\n" \
                    f"➖➖➖➖➖➖➖➖➖➖\n"
        await message.answer(text, parse_mode="Markdown")

# --- STATISTIKA ---
@logist_router.message(F.text == "📊 Statistika")
async def show_stats(message: Message):
    async with async_session() as session:
        count_res = await session.execute(select(func.count(Order.id)))
        count = count_res.scalar()
        
        # Qo'shimcha: Bugungi buyurtmalar soni
        today = datetime.datetime.utcnow().date()
        today_res = await session.execute(
            select(func.count(Order.id)).where(func.date(Order.created_at) == today)
        )
        today_count = today_res.scalar()
        
        await message.answer(
            f"📊 **Umumiy statistika:**\n\n"
            f"✅ Jami buyurtmalar: {count} ta\n"
            f"📅 Bugungi yangi buyurtmalar: {today_count} ta"
        )

# --- YANGI BUYURTMA YARATISH (FSM) ---
@logist_router.message(F.text == "➕ Yangi buyurtma")
async def start_order(message: Message, state: FSMContext):
    await message.answer("👤 Mijoz ismini kiriting (yoki kompaniya nomi):")
    await state.set_state(OrderCreation.waiting_for_client_name)

@logist_router.message(OrderCreation.waiting_for_client_name)
async def get_name(message: Message, state: FSMContext):
    await state.update_data(c_name=message.text)
    await message.answer("📞 Mijoz telefonini kiriting (Namuna: +998901234567):")
    await state.set_state(OrderCreation.waiting_for_client_phone)

@logist_router.message(OrderCreation.waiting_for_client_phone)
async def get_phone(message: Message, state: FSMContext):
    phone_number = message.text.replace(" ", "")
    if not re.match(r"^\+998\d{9}$", phone_number):
        await message.answer("❌ Xato format! Iltimos, raqamni to'liq kiriting (+998901234567):")
        return
    await state.update_data(c_phone=phone_number)
    await message.answer("📦 Yuk tavsifi (Nima yuklanadi?):")
    await state.set_state(OrderCreation.waiting_for_cargo_desc)

@logist_router.message(OrderCreation.waiting_for_cargo_desc)
async def get_cargo(message: Message, state: FSMContext):
    await state.update_data(cargo=message.text)
    await message.answer("📍 Yuk ortish manzili (A nuqta):")
    await state.set_state(OrderCreation.waiting_for_point_a)

@logist_router.message(OrderCreation.waiting_for_point_a)
async def get_point_a(message: Message, state: FSMContext):
    await state.update_data(p_a=message.text)
    await message.answer("🏁 Yuk tushirish manzili (B nuqta):")
    await state.set_state(OrderCreation.waiting_for_point_b)

@logist_router.message(OrderCreation.waiting_for_point_b)
async def get_point_b(message: Message, state: FSMContext):
    await state.update_data(p_b=message.text)
    await message.answer("💰 **SOTISH NARXI** (Mijoz to'laydigan summa):")
    await state.set_state(OrderCreation.waiting_for_sale_price)

@logist_router.message(OrderCreation.waiting_for_sale_price)
async def get_sale_price(message: Message, state: FSMContext):
    clean_price = "".join(filter(str.isdigit, message.text))
    if not clean_price:
        await message.answer("Iltimos, faqat raqamlarda kiriting:")
        return
    await state.update_data(s_price=float(clean_price))
    await message.answer("💸 **XARAJAT NARXI** (Haydovchiga beriladigan summa):")
    await state.set_state(OrderCreation.waiting_for_cost_price)

@logist_router.message(OrderCreation.waiting_for_cost_price)
async def finish_order(message: Message, state: FSMContext):
    clean_cost = "".join(filter(str.isdigit, message.text))
    if not clean_cost:
        await message.answer("Iltimos, faqat raqamlarda kiriting:")
        return
    
    data = await state.get_data()
    async with async_session() as session:
        new_order = Order(
            logist_id=message.from_user.id,
            client_phone=data['c_phone'],
            cargo_description=data['cargo'],
            point_a=data['p_a'],
            point_b=data['p_b'],
            sale_price=data['s_price'],
            cost_price=float(clean_cost),
            status=OrderStatus.NEW,
            created_at=datetime.datetime.utcnow()
        )
        session.add(new_order)
        await session.commit()
        await session.refresh(new_order)
        
        # Dispetcherlar ro'yxatini olish
        disp_result = await session.execute(
            select(User).where(User.role == UserRole.DISPATCHER)
        )
        dispatchers = disp_result.scalars().all()

    if not dispatchers:
        await message.answer(f"✅ Buyurtma #{new_order.id} saqlandi. Lekin tizimda birorta ham dispetcher topilmadi!")
        await state.clear()
        return

    await state.update_data(current_order_id=new_order.id)
    await message.answer(
        f"✅ Buyurtma #{new_order.id} muvaffaqiyatli saqlandi.\n\n"
        f"Endi ushbu buyurtmani qaysi dispetcherga biriktirmoqchisiz?",
        reply_markup=get_dispatchers_keyboard(dispatchers)
    )

# --- DISPETCHERNI BIRIKTIRISH (CALLBACK) ---
@logist_router.callback_query(F.data.startswith("assign_disp_"))
async def process_assign_dispatcher(callback: CallbackQuery, state: FSMContext):
    disp_id = int(callback.data.split("_")[2])
    data = await state.get_data()
    order_id = data.get('current_order_id')

    if not order_id:
        await callback.answer("Xatolik: Buyurtma ID topilmadi.", show_alert=True)
        return

    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        order.dispatcher_id = disp_id
        order.status = OrderStatus.DISPATCHER_ASSIGNED
        
        dispatcher = (await session.execute(select(User).where(User.id == disp_id))).scalar_one()
        await session.commit()

    await callback.message.edit_text(f"✅ Buyurtma #{order_id} dispetcher **{dispatcher.full_name}**ga biriktirildi.")
    
    # Dispetcherga xabar yuborish
    try:
        await callback.bot.send_message(
            chat_id=dispatcher.telegram_id,
            text=f"🔔 **YANGI BUYURTMA KELDI!**\n\n"
                 f"🆔 ID: #{order_id}\n"
                 f"📍 Manzil: {order.point_a} ➔ {order.point_b}\n"
                 f"📦 Yuk: {order.cargo_description}"
        )
    except: pass
    await state.clear()

# --- BOSQICH 7: DIDOX SHOT-FAKTURA YUBORISH ---
@logist_router.callback_query(F.data.startswith("send_invoice_"))
async def start_invoice_upload(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[2])
    await state.update_data(order_id=order_id)
    await state.set_state(LogistSteps.waiting_for_invoice)
    await callback.message.answer("📄 Iltimos, Didox tizimidan olingan PDF shot-faktura faylini yuboring.")

@logist_router.message(LogistSteps.waiting_for_invoice, F.document)
async def handle_invoice_pdf(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data['order_id']
    pdf_file_id = message.document.file_id

    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        order.status = OrderStatus.DIDOX_PENDING
        
        # Mijozni telefon raqami orqali topish
        client_res = await session.execute(
            select(User).where(User.phone == order.client_phone)
        )
        client = client_res.scalar_one_or_none()
        await session.commit()

    if client and client.telegram_id:
        try:
            kb = InlineKeyboardBuilder()
            kb.button(text="✅ Tasdiqlayman", callback_data=f"cl_confirm_inv_{order_id}")
            
            await message.bot.send_document(
                chat_id=client.telegram_id,
                document=pdf_file_id,
                caption=f"🧾 **#{order_id} buyurtma uchun shot-faktura.**\n\n"
                        f"Yuk muvaffaqiyatli yetkazildi. Iltimos, fakturani tekshirib tasdiqlang.",
                reply_markup=kb.as_markup()
            )
            await message.answer("✅ Faktura mijozga tasdiqlash uchun yuborildi.")
        except Exception as e:
            await message.answer(f"❌ Mijozga yuborishda xatolik: {str(e)}")
    else:
        await message.answer("⚠️ Mijoz botdan ro'yxatdan o'tmagan, shuning uchun faktura unga telegram orqali yuborilmadi.")

    await state.clear()