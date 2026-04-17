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
# Kodingni eng tepasiga boshqa importlar qatoriga qo'sh:
from bot.keyboards.admin_kb import get_admin_approve_keyboard

import logging

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

MY_ID = 1687872138

@logist_router.message(F.text == "/start")
async def cmd_start(message: Message, user: User = None):
    # 1. Agar Middleware user-ni topmagan bo'lsa (Mutlaqo yangi user)
    if user is None:
        async with async_session() as session:
            stmt = select(User).where(User.telegram_id == message.from_user.id)
            res = await session.execute(stmt)
            db_user = res.scalar_one_or_none()

            if not db_user:
                db_user = User(
                    telegram_id=message.from_user.id,
                    full_name=message.from_user.full_name,
                    role=UserRole.PENDING
                )
                session.add(db_user)
                await session.commit()
                # Obyektni sessiyada yangilab olamiz
                await session.refresh(db_user)
                user = db_user
            else:
                user = db_user

    # 2. ENG MUHIM QISM: Agar foydalanuvchi tasdiqlanmagan bo'lsa (PENDING)
    if user.role == UserRole.PENDING:
        try:
            # Markdown o'rniga HTML ishlatamiz - bu xatolikni (parse error) 100% yo'qotadi
            admin_text = (
                f"<b>🔔 Yangi ruxsat so'rovi!</b>\n\n"
                f"👤 Ism: {message.from_user.full_name}\n"
                f"🆔 ID: <code>{message.from_user.id}</code>\n"
                f"📱 Username: @{message.from_user.username or 'yoq'}\n\n"
                f"Ushbu xodimga tizimda rol bering:"
            )
            
            await message.bot.send_message(
                chat_id=MY_ID,
                text=admin_text,
                parse_mode="HTML",
                reply_markup=get_admin_approve_keyboard(message.from_user.id)
            )
            logging.info(f"Founderga xabar yuborildi: {MY_ID}")
        except Exception as e:
            logging.error(f"Founderga xabar yuborishda texnik xato: {e}")

        await message.answer(
            f"Sizning so'rovingiz adminga yuborilgan. ⏳\n"
            f"Iltimos, admin tasdiqlashini kuting.\n\n"
            f"Sizning ID: {message.from_user.id}"
        )
        return

    # 3. Agar foydalanuvchi allaqachon FOUNDER bo'lsa
    if user.role == UserRole.FOUNDER:
        try:
            from bot.keyboards.founder_kb import founder_main_kb
            await message.answer(
                f"Xush kelibsiz, Asoschi {user.full_name}! 👑",
                reply_markup=founder_main_kb
            )
        except Exception as e:
            await message.answer(f"Xush kelibsiz, {user.full_name}! (Menyu yuklashda xato)")
        return

    # 4. Boshqa tasdiqlangan rollar
    if user.role == UserRole.LOGIST:
        from bot.keyboards.logist_kb import get_logist_main_keyboard
        await message.answer(
            f"Xush kelibsiz, Logist {user.full_name}! 🚛",
            reply_markup=get_logist_main_keyboard()
        )
    elif user.role == UserRole.DISPATCHER:
        from bot.keyboards.dispatcher_kb import get_dispatcher_main_keyboard
        await message.answer(
            f"Xush kelibsiz, Dispetcher {user.full_name}! 🎧",
            reply_markup=get_dispatcher_main_keyboard()
        )
    elif user.role == UserRole.DRIVER:
        await message.answer(f"Xush kelibsiz, Haydovchi {user.full_name}! 🚚")
    elif user.role == UserRole.CASHIER:
        await message.answer(f"Xush kelibsiz, Kassir {user.full_name}! 💰")
        
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
    # Raqamdan boshqa hamma narsani olib tashlaymiz
    clean_price = "".join(filter(str.isdigit, message.text))
    
    if not clean_price:
        await message.answer("❌ Iltimos, sotish narxini faqat raqamlarda kiriting (masalan: 5000):")
        return
        
    await state.update_data(s_price=float(clean_price))
    await message.answer("💸 **XARAJAT NARXI** (Haydovchiga beriladigan summa):")
    await state.set_state(OrderCreation.waiting_for_cost_price)

# BU YERDA @ BELGISI QOLIB KETGAN EDI:
@logist_router.message(OrderCreation.waiting_for_cost_price)
async def finish_order(message: Message, state: FSMContext):
    clean_cost = "".join(filter(str.isdigit, message.text))
    
    if not clean_cost:
        await message.answer("❌ Iltimos, xarajat narxini faqat raqamlarda kiriting:")
        return
    
    data = await state.get_data()
    
    async with async_session() as session:
        try:
            new_order = Order(
                # message.from_user.id bu telegram_id, bazada shuni saqlaymiz
                logist_id=message.from_user.id, 
                client_phone=data['c_phone'],
                cargo_description=data['cargo'],
                point_a=data['p_a'],
                point_b=data['p_b'],
                sale_price=data['s_price'],
                cost_price=float(clean_cost),
                status=OrderStatus.NEW
            )
            
            session.add(new_order)
            await session.commit()
            await session.refresh(new_order)
            
            disp_result = await session.execute(
                select(User).where(User.role == UserRole.DISPATCHER)
            )
            dispatchers = disp_result.scalars().all()

            await state.update_data(current_order_id=new_order.id)
            
            if not dispatchers:
                await message.answer(
                    f"✅ <b>Buyurtma #{new_order.id} saqlandi.</b>\n\n"
                    f"⚠️ Lekin tizimda birorta ham dispetcher topilmadi!",
                    parse_mode="HTML"
                )
                await state.clear()
                return

            await message.answer(
                f"✅ <b>Buyurtma #{new_order.id} muvaffaqiyatli saqlandi.</b>\n\n"
                f"Endi ushbu buyurtmani qaysi dispetcherga biriktirmoqchisiz?",
                reply_markup=get_dispatchers_keyboard(dispatchers),
                parse_mode="HTML"
            )

        except Exception as e:
            logging.error(f"DATABASE ERROR in finish_order: {e}")
            await message.answer("❌ Ma'lumotlarni saqlashda texnik xato.")

# --- DISPETCHERNI BIRIKTIRISH (CALLBACK) ---
# bot/handler/logist.py

@logist_router.callback_query(F.data.startswith("assign_disp_"))
async def process_assign_dispatcher(callback: CallbackQuery, state: FSMContext):
    target_user_id = int(callback.data.split("_")[2])
    data = await state.get_data()
    order_id = data.get('current_order_id')

    async with async_session() as session:
        try:
            # Dispetcherni bazadagi serial ID si orqali topamiz
            res = await session.execute(select(User).where(User.id == target_user_id))
            dispatcher = res.scalar_one_or_none()

            if not dispatcher:
                await callback.answer("Dispetcher topilmadi!")
                return

            order_res = await session.execute(select(Order).where(Order.id == order_id))
            order = order_res.scalar_one_or_none()

            if order:
                # BU YERDA XATO BOR EDI: .id (3) emas, .telegram_id ni biriktiramiz!
                order.dispatcher_id = dispatcher.telegram_id 
                order.status = OrderStatus.DISPATCHER_ASSIGNED
                await session.commit()
                
                await callback.message.edit_text(
                    f"✅ Buyurtma #{order_id} dispetcher {dispatcher.full_name}ga biriktirildi."
                )
                
                await callback.bot.send_message(
                    chat_id=dispatcher.telegram_id,
                    text=f"🔔 Sizga yangi buyurtma biriktirildi: #{order_id}"
                )
            else:
                await callback.answer("Buyurtma topilmadi!")
        except Exception as e:
            await session.rollback()
            logging.error(f"Error in process_assign_dispatcher: {e}")
            await callback.answer("Xatolik yuz berdi!")

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

@logist_router.callback_query(F.data.startswith("cl_confirm_inv_"))
async def client_confirm_invoice(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[3])
    
    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        order.status = OrderStatus.UNLOADED # Yoki jarayon bo'yicha keyingi status
        
        # Kassirni topish va bildirishnoma yuborish
        cashier_res = await session.execute(select(User).where(User.role == UserRole.CASHIER))
        cashier = cashier_res.scalars().first()
        
        await session.commit()

    await callback.message.edit_caption(caption=callback.message.caption + "\n\n✅ Siz fakturani tasdiqladingiz.")
    
    if cashier:
        await callback.bot.send_message(
            chat_id=cashier.telegram_id,
            text=f"💵 Buyurtma #{order_id} mijoz tomonidan tasdiqlandi. To'lov qilishingiz mumkin."
        )

# ==========================================================================

logist_doc_router = Router() # Mana shu satr yetishmayapti

# Logist shot-faktura (PDF) yuborganda ushlab qolish
@logist_doc_router.message(F.document & F.caption.contains("faktura")) # yoki caption orqali filtrlaymiz
async def handle_shot_faktura(message: Message):
    # Bu yerda logist biror buyurtma ID sini yozib yuborishi kerak yoki 
    # biz state orqali qaysi buyurtma uchunligini bilishimiz kerak.
    # Hozircha caption-da ID bor deb hisoblaymiz (Masalan: "faktura #12")
    
    try:
        order_id = int(message.caption.split("#")[1])
    except:
        await message.answer("⚠️ Iltimos, fayl izohida (caption) buyurtma raqamini yozing. Masalan: 'faktura #12'")
        return

    async with async_session() as session:
        order_res = await session.execute(select(Order).where(Order.id == order_id))
        order = order_res.scalar_one_or_none()
        
        if not order:
            await message.answer("Buyurtma topilmadi!")
            return

        # Statusni o'zgartiramiz
        order.status = OrderStatus.DIDOX_TASDIQDA # TZ bo'yicha status
        
        # Haydovchi va Dispetcherni topish
        driver_res = await session.execute(select(User).where(User.id == order.driver_id))
        driver = driver_res.scalar_one()
        
        disp_res = await session.execute(select(User).where(User.id == order.dispatcher_id))
        dispatcher = disp_res.scalar_one()

        await session.commit()

    # 1. Dispetcherga bildirishnoma
    await message.bot.send_message(
        chat_id=dispatcher.telegram_id,
        text=f"📄 Logist #{order_id} buyurtma uchun shot-fakturani yubordi. Haydovchi yukni tushirishi mumkin."
    )

    # 2. Haydovchiga ruxsat va "Yukni tushiryapman" tugmasi
    from bot.handler.driver import get_driver_main_keyboard # o'zingdagi keyboard funksiyasi
    
    await message.bot.send_message(
        chat_id=driver.telegram_id,
        text=f"✅ Ruxsat berildi! Shot-faktura yuborildi. Yukni tushirishni boshlang va botga media yuboring."
    )

    # 3. Mijozga fakturani yuborish (TZ punkt 7)
    # Avvalroq order.client_phone orqali mijozni topishni yozgan eding
    # Mijozga PDF faylni forward qilamiz
    # ... (mijoz logikasi)

    await message.answer(f"✅ #{order_id} buyurtma uchun shot-faktura qabul qilindi va tarqatildi.")