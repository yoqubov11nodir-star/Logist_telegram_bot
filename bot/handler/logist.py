import asyncio
import re
import datetime
import logging

from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command
from sqlalchemy import select, update, func

from database.session import async_session
from database.models import Order, OrderStatus, User, UserRole, OrderLocation
from bot.states.order_states import OrderCreation
from bot.states.logist_states import LogistSteps
from bot.keyboards.logist_kb import get_logist_main_keyboard, get_dispatchers_keyboard
from bot.keyboards.dispatcher_kb import get_dispatcher_main_keyboard
from bot.keyboards.admin_kb import get_admin_approve_keyboard
from bot.keyboards.founder_kb import founder_main_kb

logist_router     = Router()
logist_doc_router = Router()   # PDF hujjatlar uchun alohida router

# ─── Global taymer lug'ati ────────────────────────────────────────────────────
active_location_requests: dict = {}

FOUNDER_ID = 1687872138  # Founder Telegram ID

STATUS_UZ = {
    "NEW":                 "🆕 Yangi",
    "DISPATCHER_ASSIGNED": "📋 Dispetcherga biriktirildi",
    "DRIVER_ASSIGNED":     "🚛 Haydovchi biriktirildi",
    "ARRIVED_A":           "📍 A nuqtaga keldi",
    "LOADING":             "📦 Yuk ortilmoqda",
    "ON_WAY":              "🚚 Yo'lda",
    "ARRIVED_B":           "🏁 B nuqtada",
    "DIDOX_TASDIQDA":      "✅ Faktura yuborildi",
    "UNLOADED":            "📤 Yuk tushirildi",
    "PAID":                "💰 To'langan",
    "COMPLETED":           "✅ Yakunlandi",
    "CANCELLED":           "❌ Bekor qilindi",
}


# ─── 15 DAQIQALIK TAYMER ─────────────────────────────────────────────────────
async def location_timer_logic(
    order_id: int, bot: Bot,
    driver_name: str, disp_tg_id: int, logist_tg_id: int,
):
    stop_event = asyncio.Event()
    active_location_requests[order_id] = stop_event
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=900)
    except asyncio.TimeoutError:
        alert = (
            f"🚨 <b>OGOHLANTIRISH!</b>\n\n"
            f"👨‍✈️ Haydovchi: <b>{driver_name}</b>\n"
            f"📦 Buyurtma: <b>#{order_id}</b>\n\n"
            f"⏰ 15 daqiqadan beri lokatsiya yuborilmadi!\n"
            f"Haydovchi bilan bog'laning."
        )
        for chat_id in (disp_tg_id, logist_tg_id):
            try:
                await bot.send_message(chat_id, alert, parse_mode="HTML")
            except Exception:
                pass
    finally:
        active_location_requests.pop(order_id, None)


# ─── /start ──────────────────────────────────────────────────────────────────
@logist_router.message(Command("start"))
async def cmd_start(message: Message, user: User):
    # Telefon yo'q → kontakt so'ra
    if not user.phone:
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]],
            resize_keyboard=True, one_time_keyboard=True,
        )
        await message.answer(
            f"Assalomu alaykum, <b>{user.full_name}</b>!\n\n"
            f"Botdan foydalanish uchun telefon raqamingizni yuboring:",
            reply_markup=kb, parse_mode="HTML",
        )
        return

    # Rol bo'yicha menyu
    role = user.role
    if role == UserRole.FOUNDER:
        await message.answer("👑 Xush kelibsiz, Asoschi!", reply_markup=founder_main_kb)
    elif role == UserRole.LOGIST:
        await message.answer("📋 Xush kelibsiz, Logist!", reply_markup=get_logist_main_keyboard())
    elif role == UserRole.DISPATCHER:
        await message.answer("🎧 Xush kelibsiz, Dispetcher!", reply_markup=get_dispatcher_main_keyboard())
    elif role == UserRole.DRIVER:
        from bot.keyboards.driver_kb import get_driver_main_keyboard
        await message.answer(
            f"👨‍✈️ Xush kelibsiz, <b>{user.full_name}</b>!\n\n"
            f"Mening yuklarim bo'limidan faol yukingizni ko'rishingiz mumkin.",
            reply_markup=get_driver_main_keyboard(), parse_mode="HTML",
        )
    elif role == UserRole.CASHIER:
        from bot.keyboards.cashier_kb import get_cashier_main_keyboard
        await message.answer("💵 Xush kelibsiz, Kassir!", reply_markup=get_cashier_main_keyboard())
    elif role == UserRole.CLIENT:
        from bot.keyboards.client_kb import get_client_main_keyboard
        await message.answer(
            "👋 Xush kelibsiz!\nYukingiz holatini kuzatishingiz mumkin.",
            reply_markup=get_client_main_keyboard(),
        )
    else:
        # PENDING — admin tasdig'ini kutish
        try:
            await message.bot.send_message(
                chat_id=FOUNDER_ID,
                text=(
                    f"🔔 <b>Yangi xodim so'rovi!</b>\n\n"
                    f"👤 Ism: {user.full_name}\n"
                    f"📱 Raqam: {user.phone}\n"
                    f"🆔 ID: <code>{user.telegram_id}</code>\n"
                    f"Username: @{user.username or 'Yo\'q'}\n\n"
                    f"Rol bering:"
                ),
                parse_mode="HTML",
                reply_markup=get_admin_approve_keyboard(user.telegram_id),
            )
        except Exception as e:
            logging.error(f"Founderga xabar yuborishda xato: {e}")
        await message.answer("⏳ So'rovingiz admin tasdig'ida. Iltimos, kutib turing.")


# ─── KONTAKT ─────────────────────────────────────────────────────────────────
@logist_router.message(F.contact)
async def handle_contact(message: Message, user: User):
    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone
    async with async_session() as session:
        await session.execute(
            update(User).where(User.telegram_id == user.telegram_id).values(phone=phone)
        )
        await session.commit()
    await message.answer(
        f"✅ Raqamingiz ({phone}) qabul qilindi.\n\n/start bosing.",
        reply_markup=ReplyKeyboardRemove(),
    )


# ─── BUYURTMALARIM ───────────────────────────────────────────────────────────
@logist_router.message(F.text == "📋 Buyurtmalarim")
async def my_orders(message: Message, user: User):
    async with async_session() as session:
        result = await session.execute(
            select(Order)
            .where(Order.logist_id == user.telegram_id)
            .order_by(Order.id.desc())
            .limit(20)
        )
        orders = result.scalars().all()

    if not orders:
        await message.answer("📭 Hozircha buyurtmalar mavjud emas.")
        return

    for o in orders:
        status = STATUS_UZ.get(o.status.value, o.status.value)
        kb = InlineKeyboardBuilder()
        if o.status == OrderStatus.NEW:
            kb.button(text="📋 Dispetcher biriktirish", callback_data=f"reassign_disp_{o.id}")
        elif o.status == OrderStatus.ARRIVED_B:
            kb.button(text="📄 Shot-faktura yuborish", callback_data=f"send_invoice_{o.id}")
        kb.adjust(1)

        text = (
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Buyurtma #{o.id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 Mijoz: {o.client_phone}\n"
            f"📦 Yuk: {o.cargo_description}\n"
            f"🔵 A nuqta: {o.point_a}\n"
            f"🔴 B nuqta: {o.point_b}\n"
            f"📊 <b>Holat: {status}</b>\n"
            f"💸 Xarajat: {o.cost_price:,.0f} so'm\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        markup = kb.as_markup() if kb.export() else None
        await message.answer(text, reply_markup=markup, parse_mode="HTML")


@logist_router.callback_query(F.data.startswith("reassign_disp_"))
async def reassign_dispatcher(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[2])
    async with async_session() as session:
        dispatchers = (
            await session.execute(select(User).where(User.role == UserRole.DISPATCHER))
        ).scalars().all()
    await state.update_data(current_order_id=order_id)
    await callback.message.answer("📋 Dispetcherni tanlang:", reply_markup=get_dispatchers_keyboard(dispatchers))


# ─── STATISTIKA ──────────────────────────────────────────────────────────────
@logist_router.message(F.text == "📊 Statistika")
async def show_stats(message: Message, user: User):
    async with async_session() as session:
        total = (
            await session.execute(
                select(func.count(Order.id)).where(Order.logist_id == user.telegram_id)
            )
        ).scalar() or 0
        today = datetime.datetime.utcnow().date()
        today_count = (
            await session.execute(
                select(func.count(Order.id)).where(
                    Order.logist_id == user.telegram_id,
                    func.date(Order.created_at) == today,
                )
            )
        ).scalar() or 0
    await message.answer(
        f"📊 <b>Sizning statistikangiz:</b>\n\n"
        f"📋 Jami buyurtmalar: {total} ta\n"
        f"📅 Bugun yaratilgan: {today_count} ta",
        parse_mode="HTML",
    )


# ─── YANGI BUYURTMA (FSM) ────────────────────────────────────────────────────
@logist_router.message(F.text == "➕ Yangi buyurtma")
async def start_order(message: Message, state: FSMContext):
    await message.answer("👤 Mijoz ismi yoki kompaniya nomini kiriting:")
    await state.set_state(OrderCreation.waiting_for_client_name)


@logist_router.message(OrderCreation.waiting_for_client_name)
async def get_name(message: Message, state: FSMContext):
    await state.update_data(c_name=message.text)
    await message.answer("📞 Mijoz telefon raqamini kiriting (+998XXXXXXXXX):")
    await state.set_state(OrderCreation.waiting_for_client_phone)


@logist_router.message(OrderCreation.waiting_for_client_phone)
async def get_phone(message: Message, state: FSMContext):
    phone = message.text.replace(" ", "")
    if not re.match(r"^\+998\d{9}$", phone):
        await message.answer("❌ Xato format! (+998901234567):")
        return
    await state.update_data(c_phone=phone)
    await message.answer("📦 Yuk tavsifi (nima, qancha, o'lchamlar):")
    await state.set_state(OrderCreation.waiting_for_cargo_desc)


@logist_router.message(OrderCreation.waiting_for_cargo_desc)
async def get_cargo(message: Message, state: FSMContext):
    await state.update_data(cargo=message.text)
    await message.answer("🔵 A nuqta — yuklash manzili (nom va to'liq manzil):")
    await state.set_state(OrderCreation.waiting_for_point_a)


@logist_router.message(OrderCreation.waiting_for_point_a)
async def get_point_a(message: Message, state: FSMContext):
    await state.update_data(p_a=message.text)
    await message.answer("🔴 B nuqta — tushirish manzili (nom va to'liq manzil):")
    await state.set_state(OrderCreation.waiting_for_point_b)


@logist_router.message(OrderCreation.waiting_for_point_b)
async def get_point_b(message: Message, state: FSMContext):
    await state.update_data(p_b=message.text)
    await message.answer("💰 <b>SOTISH NARXI</b> (mijoz to'laydi, faqat raqam):", parse_mode="HTML")
    await state.set_state(OrderCreation.waiting_for_sale_price)


@logist_router.message(OrderCreation.waiting_for_sale_price)
async def get_sale_price(message: Message, state: FSMContext):
    clean = "".join(filter(str.isdigit, message.text))
    if not clean:
        await message.answer("❌ Faqat raqam kiriting:")
        return
    await state.update_data(s_price=float(clean))
    await message.answer("💸 <b>XARAJAT NARXI</b> (haydovchiga, faqat raqam):", parse_mode="HTML")
    await state.set_state(OrderCreation.waiting_for_cost_price)


@logist_router.message(OrderCreation.waiting_for_cost_price)
async def finish_order(message: Message, state: FSMContext, user: User):
    clean = "".join(filter(str.isdigit, message.text))
    if not clean:
        await message.answer("❌ Faqat raqam kiriting:")
        return

    data = await state.get_data()
    async with async_session() as session:
        try:
            order = Order(
                logist_id=user.telegram_id,
                client_phone=data["c_phone"],
                cargo_description=data["cargo"],
                point_a=data["p_a"],
                point_b=data["p_b"],
                sale_price=data["s_price"],
                cost_price=float(clean),
                status=OrderStatus.NEW,
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)

            dispatchers = (
                await session.execute(select(User).where(User.role == UserRole.DISPATCHER))
            ).scalars().all()

            await state.update_data(current_order_id=order.id)
            await message.answer(
                f"✅ <b>Buyurtma #{order.id} yaratildi!</b>\n\n"
                f"📦 Yuk: {data['cargo']}\n"
                f"📍 {data['p_a']} → {data['p_b']}\n\n"
                f"👇 Dispetcherni tanlang:",
                reply_markup=get_dispatchers_keyboard(dispatchers),
                parse_mode="HTML",
            )
        except Exception as e:
            await session.rollback()
            logging.error(f"Buyurtma yaratishda xato: {e}")
            await message.answer("❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.")


# ─── DISPETCHER BIRIKTIRISH ───────────────────────────────────────────────────
@logist_router.callback_query(F.data.startswith("assign_disp_"))
async def process_assign_dispatcher(callback: CallbackQuery, state: FSMContext):
    target_db_id = int(callback.data.split("_")[2])
    data = await state.get_data()
    order_id = data.get("current_order_id")

    async with async_session() as session:
        try:
            dispatcher = (
                await session.execute(select(User).where(User.id == target_db_id))
            ).scalar_one_or_none()
            if not dispatcher:
                await callback.answer("Dispetcher topilmadi!")
                return

            order = (
                await session.execute(select(Order).where(Order.id == order_id))
            ).scalar_one_or_none()
            if not order:
                await callback.answer("Buyurtma topilmadi!")
                return

            order.dispatcher_id = dispatcher.telegram_id
            order.status = OrderStatus.DISPATCHER_ASSIGNED
            await session.commit()

            await callback.message.edit_text(
                f"✅ <b>Buyurtma #{order_id}</b> — {dispatcher.full_name}ga biriktirildi.",
                parse_mode="HTML",
            )
            await callback.bot.send_message(
                chat_id=dispatcher.telegram_id,
                text=(
                    f"🔔 <b>Sizga yangi buyurtma biriktirildi!</b>\n\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"📦 <b>Buyurtma #{order_id}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"🔵 A nuqta: {order.point_a}\n"
                    f"🔴 B nuqta: {order.point_b}\n"
                    f"📦 Yuk: {order.cargo_description}\n"
                    f"💸 Limit: {order.cost_price:,.0f} so'm\n"
                    f"━━━━━━━━━━━━━━━━━━\n\n"
                    f"📥 <b>Yangi buyurtmalar</b> bo'limidan ko'ring."
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            await session.rollback()
            logging.error(f"Dispetcher biriktirishda xato: {e}")
            await callback.answer("Xatolik yuz berdi!")
    await state.clear()


# ─── SHOT-FAKTURA YUBORISH ────────────────────────────────────────────────────
@logist_router.callback_query(F.data.startswith("send_invoice_"))
async def start_invoice_upload(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[2])
    await state.update_data(current_order_id=order_id)
    await state.set_state(LogistSteps.waiting_for_invoice)
    await callback.message.answer(
        f"📄 <b>#{order_id} buyurtma uchun Didox PDF faylini yuboring.</b>\n\n"
        f"<i>Faqat PDF format qabul qilinadi.</i>",
        parse_mode="HTML",
    )


@logist_doc_router.message(LogistSteps.waiting_for_invoice, F.document)
async def handle_shot_faktura(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("current_order_id")
    if not order_id:
        await message.answer("❌ Xatolik: Buyurtma raqami topilmadi.")
        return

    async with async_session() as session:
        order = (
            await session.execute(select(Order).where(Order.id == order_id))
        ).scalar_one_or_none()
        if not order:
            return

        order.status = OrderStatus.DIDOX_TASDIQDA
        dispatcher = (
            await session.execute(select(User).where(User.telegram_id == order.dispatcher_id))
        ).scalar_one_or_none()
        client = (
            await session.execute(select(User).where(User.phone == order.client_phone))
        ).scalar_one_or_none()
        await session.commit()

    # Haydovchiga ruxsat
    if order.driver_id:
        kb = InlineKeyboardBuilder()
        kb.button(text="📤 Yuk tushirdim (Media yuborish)", callback_data=f"st_unload_media_{order_id}")
        try:
            await message.bot.send_message(
                chat_id=order.driver_id,
                text=(
                    f"✅ <b>Ruxsat berildi!</b>\n\n"
                    f"📦 Buyurtma #{order_id}\n\n"
                    f"Yukni tushirishni boshlashingiz mumkin.\n"
                    f"Tushirgach, media (rasm va video) yuborishingiz kerak."
                ),
                reply_markup=kb.as_markup(),
                parse_mode="HTML",
            )
        except Exception:
            pass

    # Dispetcherga PDF
    if dispatcher:
        try:
            await message.bot.send_document(
                chat_id=dispatcher.telegram_id,
                document=message.document.file_id,
                caption=f"📄 #{order_id} — Logist shot-faktura yubordi. Haydovchiga ruxsat berildi.",
            )
        except Exception:
            pass

    # Mijozga PDF
    if client and client.telegram_id:
        try:
            await message.bot.send_document(
                chat_id=client.telegram_id,
                document=message.document.file_id,
                caption=(
                    f"🎉 <b>Yukingiz #{order_id} manzilga yetib keldi!</b>\n\n"
                    f"Shot-faktura yuborildi. Iltimos, imkon qadar tezroq qabul qiling."
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    await message.answer(
        f"✅ <b>#{order_id} faktura qabul qilindi!</b>\nHaydovchiga ruxsat berildi.",
        parse_mode="HTML",
    )
    await state.clear()


# ─── ROL BERISH (CALLBACK) ────────────────────────────────────────────────────
@logist_router.callback_query(F.data.startswith("set_role_"))
async def process_callback_set_role(callback: CallbackQuery):
    parts = callback.data.split("_")
    new_role_str = parts[2]
    target_tg_id = int(parts[3])

    ROLE_NAMES = {
        "LOGIST": "Logist", "DISPATCHER": "Dispetcher",
        "DRIVER": "Haydovchi", "CASHIER": "Kassir", "CLIENT": "Mijoz",
    }

    async with async_session() as session:
        try:
            await session.execute(
                update(User)
                .where(User.telegram_id == target_tg_id)
                .values(role=UserRole[new_role_str])
            )
            await session.commit()
            role_uz = ROLE_NAMES.get(new_role_str, new_role_str)
            await callback.message.edit_text(
                f"✅ Foydalanuvchi roli <b>{role_uz}</b> qilib belgilandi!",
                parse_mode="HTML",
            )
            try:
                await callback.bot.send_message(
                    chat_id=target_tg_id,
                    text=(
                        f"🎉 Admin so'rovingizni tasdiqladi.\n"
                        f"Sizga <b>{role_uz}</b> roli berildi.\n\n"
                        f"/start bosing."
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        except Exception as e:
            logging.error(f"Rol berishda xato: {e}")
            await callback.answer("Xatolik yuz berdi!")
    await callback.answer()
