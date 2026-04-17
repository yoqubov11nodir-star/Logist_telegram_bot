import asyncio
import re
import datetime
from aiogram import Router, F, Bot
from aiogram.types import (
    Message, 
    CallbackQuery, 
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    ReplyKeyboardRemove  # <--- Mana shu yetishmayotgan edi
)
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
async def cmd_start(message: Message, user: User):
    """
    Middleware orqali kelgan user ma'lumotlarini tekshirish va 
    tegishli menyuni chiqarish funksiyasi.
    """
    
    # 1. FOYDALANUVCHIDA RAQAM BORLIGINI TEKSHIRISH
    # Agar raqami yo'q bo'lsa, u kimligini (mijoz/xodim) bilolmaymiz
    if not user.phone:
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        await message.answer(
            f"Assalomu alaykum, {user.full_name}!\n"
            f"Tizimdan to'liq foydalanish uchun telefon raqamingizni yuboring:",
            reply_markup=kb
        )
        return

    # 2. MIJOZLARNI FILTRLASH
    # Agar raqami bor bo'lsa va Middleware uni CLIENT deb belgilagan bo'lsa
    if user.role == UserRole.CLIENT:
        await message.answer(
            "📦 Xush kelibsiz! Siz mijoz sifatida tizimdasiz.\n"
            "Buyurtmalaringiz holatini shu yerda kuzatib borishingiz mumkin.",
            reply_markup=ReplyKeyboardRemove()
        )
        # Agar mijoz menyusi bo'lsa, shu yerda reply_markup-ga biriktirishing mumkin
        return

    # 3. TASDIQLANMAGAN XODIMLARNI FILTRLASH (PENDING)
    # Agar raqami bor, lekin hali admin rol bermagan bo'lsa
    if user.role == UserRole.PENDING:
        try:
            admin_text = (
                f"<b>🔔 Yangi xodim so'rovi!</b>\n\n"
                f"👤 Ism: {user.full_name}\n"
                f"📱 Raqam: {user.phone}\n"
                f"🆔 ID: <code>{user.telegram_id}</code>\n"
                f"📱 Username: @{user.username or 'yoq'}\n\n"
                f"Ushbu xodimga tizimda rol bering:"
            )
            
            await message.bot.send_message(
                chat_id=MY_ID,
                text=admin_text,
                parse_mode="HTML",
                reply_markup=get_admin_approve_keyboard(user.telegram_id)
            )
        except Exception as e:
            logging.error(f"Founderga xabar yuborishda xato: {e}")

        await message.answer(
            "⏳ Sizning ma'lumotlaringiz adminga yuborildi.\n"
            "Iltimos, admin tasdiqlashini kuting."
        )
        return

    # 4. TASDIQLANGAN ROLLLAR UCHUN MENYULAR
    # Agar roli PENDING emas va CLIENT ham emas bo'lsa, demak bu tasdiqlangan xodim
    
    if user.role == UserRole.FOUNDER:
        from bot.keyboards.founder_kb import founder_main_kb
        await message.answer(
            f"👑 Xush kelibsiz, Asoschi {user.full_name}!", 
            reply_markup=founder_main_kb
        )
    
    elif user.role == UserRole.LOGIST:
        await message.answer(
            f"🚛 Xush kelibsiz, Logist {user.full_name}!", 
            reply_markup=get_logist_main_keyboard()
        )
    
    elif user.role == UserRole.DISPATCHER:
        from bot.keyboards.dispatcher_kb import get_dispatcher_main_keyboard
        await message.answer(
            f"🎧 Xush kelibsiz, Dispetcher {user.full_name}!", 
            reply_markup=get_dispatcher_main_keyboard()
        )
    
    elif user.role == UserRole.DRIVER:
        await message.answer(f"🚚 Xush kelibsiz, Haydovchi {user.full_name}!")
    
    elif user.role == UserRole.CASHIER:
        await message.answer(f"💰 Xush kelibsiz, Kassir {user.full_name}!")
        
# --- BUYURTMALAR RO'YXATI ---
@logist_router.message(F.text == "📋 Buyurtmalarim")
async def my_orders(message: Message):
    async with async_session() as session:
        result = await session.execute(select(Order).order_by(Order.id.desc()).limit(10))
        orders = result.scalars().all()
        if not orders:
            await message.answer("Hozircha tizimda buyurtmalar mavjud emas.")
            return
        text = "📋 **Oxirgi 10 ta buyurtma:**\n\n"
        for o in orders:
            text += f"🆔 **#{o.id}** | {o.point_a} ➔ {o.point_b}\n📊 Status: `{o.status.value}`\n➖➖➖➖➖➖➖➖➖➖\n"
        await message.answer(text, parse_mode="Markdown")

# --- 2. KONTAKTNI QABUL QILISH (Yangi qo'shildi) ---
@logist_router.message(F.contact)
async def handle_contact(message: Message, user: User):
    """Raqam yuborilganda uni saqlash va rolni aniqlash"""
    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone

    async with async_session() as session:
        # 1. User raqamini bazada yangilaymiz
        await session.execute(
            update(User).where(User.id == user.id).values(phone=phone)
        )
        
        # 2. Bu raqam biror buyurtmada mijoz sifatida bormi?
        order_res = await session.execute(
            select(Order).where(Order.client_phone == phone).limit(1)
        )
        is_client_order = order_res.scalar_one_or_none()

        if is_client_order:
            # Raqam topildi -> Demak bu MIJOZ
            await session.execute(
                update(User).where(User.id == user.id).values(role=UserRole.CLIENT)
            )
            await session.commit()
            await message.answer("✅ Tizim sizni mijoz sifatida tanidi!", reply_markup=ReplyKeyboardRemove())
        else:
            # Raqam buyurtmalarda yo'q -> Demak bu XODIM (PENDING bo'lib qoladi)
            await session.commit()
            await message.answer("✅ Raqamingiz qabul qilindi.")

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
async def finish_order(message: Message, state: FSMContext, user: User): # user argumentini qo'shdik
    # 1. Narxni raqamlardan tozalash
    clean_cost = "".join(filter(str.isdigit, message.text))
    
    if not clean_cost:
        await message.answer("❌ Iltimos, xarajat narxini faqat raqamlarda kiriting:")
        return
    
    # 2. FSM dan ma'lumotlarni olish
    data = await state.get_data()
    
    async with async_session() as session:
        try:
            # 3. Yangi buyurtma yaratish
            new_order = Order(
                logist_id=user.id,        # <--- TO'G'IRLANDI: Bazadagi User ID (masalan: 1, 2, 5)
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
            await session.refresh(new_order) # ID sini olish uchun yangilaymiz
            
            # 4. Dispetcherlarni qidirish
            disp_result = await session.execute(
                select(User).where(User.role == UserRole.DISPATCHER)
            )
            dispatchers = disp_result.scalars().all()

            # 5. Keyingi bosqich uchun order_id ni saqlaymiz
            await state.update_data(current_order_id=new_order.id)
            
            if not dispatchers:
                await message.answer(
                    f"✅ <b>Buyurtma #{new_order.id} saqlandi.</b>\n\n"
                    f"⚠️ Lekin tizimda birorta ham dispetcher topilmadi!",
                    parse_mode="HTML"
                )
                await state.clear()
                return

            # 6. Dispetcher tanlash klaviaturasini chiqarish
            await message.answer(
                f"✅ <b>Buyurtma #{new_order.id} muvaffaqiyatli saqlandi.</b>\n\n"
                f"Endi ushbu buyurtmani qaysi dispetcherga biriktirmoqchisiz?",
                reply_markup=get_dispatchers_keyboard(dispatchers),
                parse_mode="HTML"
            )

        except Exception as e:
            await session.rollback()
            logging.error(f"DATABASE ERROR in finish_order: {e}")
            await message.answer("❌ Ma'lumotlarni saqlashda texnik xato yuz berdi.")

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

logist_doc_router = Router()
# Logist shot-faktura (PDF) yuborganda ushlab qolish
@logist_doc_router.message(F.document & F.caption.contains("faktura"))
async def handle_shot_faktura(message: Message):
    """
    Logist PDF faktura yuborganda uni bazadagi order bilan bog'laydi,
    Dispetcher va Haydovchini Telegram ID orqali topib, ularga xabar yuboradi.
    """
    
    # 1. Captiondan Order ID ni ajratib olish (Masalan: "faktura #12")
    try:
        order_id = int(message.caption.split("#")[1].strip())
    except (IndexError, ValueError):
        await message.answer("⚠️ Iltimos, fayl izohida (caption) buyurtma raqamini to'g'ri yozing.\nNamuna: <code>faktura #12</code>")
        return

    async with async_session() as session:
        try:
            # 2. Buyurtmani bazadan qidirish
            order_res = await session.execute(select(Order).where(Order.id == order_id))
            order = order_res.scalar_one_or_none()
            
            if not order:
                await message.answer(f"❌ #{order_id} raqamli buyurtma topilmadi!")
                return

            # 3. Buyurtma holatini yangilash
            order.status = OrderStatus.DIDOX_TASDIQDA 
            
            # 4. Haydovchi va Dispetcherni TELEGRAM_ID orqali qidirish
            # DIQQAT: order.driver_id va order.dispatcher_id ichida Telegram ID saqlangan
            driver_res = await session.execute(
                select(User).where(User.telegram_id == order.driver_id)
            )
            driver = driver_res.scalar_one_or_none()
            
            disp_res = await session.execute(
                select(User).where(User.telegram_id == order.dispatcher_id)
            )
            dispatcher = disp_res.scalar_one_or_none()

            await session.commit()

            # 5. Dispetcherga bildirishnoma yuborish
            if dispatcher:
                try:
                    await message.bot.send_message(
                        chat_id=dispatcher.telegram_id,
                        text=f"📄 Logist #{order_id} buyurtma uchun shot-fakturani yubordi.\n"
                             f"Haydovchiga ruxsat berildi."
                    )
                except Exception as e:
                    logging.error(f"Dispetcherga xabar yuborishda xato: {e}")

            # 6. Haydovchiga ruxsat va ko'rsatma yuborish
            if driver:
                try:
                    # Bu yerda driver_kb dan kerakli tugmani yuborishing mumkin
                    await message.bot.send_message(
                        chat_id=driver.telegram_id,
                        text=f"✅ <b>Ruxsat berildi!</b>\n\n"
                             f"#{order_id} buyurtma uchun shot-faktura tasdiqlandi. "
                             f"Yukni tushirishni boshlang va yakunlangach botga media (rasm/video) yuboring."
                    )
                except Exception as e:
                    logging.error(f"Haydovchiga xabar yuborishda xato: {e}")

            # 7. Logistga hisobot
            await message.answer(f"✅ #{order_id} buyurtma hujjati qabul qilindi va tegishli xodimlarga yuborildi.")

        except Exception as e:
            await session.rollback()
            logging.error(f"Error in handle_shot_faktura: {e}")
            await message.answer("❌ Shot-fakturani qayta ishlashda texnik xato yuz berdi.")