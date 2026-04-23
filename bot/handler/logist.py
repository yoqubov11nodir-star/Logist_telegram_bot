import asyncio
import re
import datetime
import logging

from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton,
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

import os

logist_router     = Router()
logist_doc_router = Router()

active_location_requests: dict = {}

FOUNDER_ID = int(os.getenv("FOUNDER_ID", 0))


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

ACTIVE_STATUSES = [
    OrderStatus.NEW,
    OrderStatus.DISPATCHER_ASSIGNED,
    OrderStatus.DRIVER_ASSIGNED,
    OrderStatus.ARRIVED_A,
    OrderStatus.LOADING,
    OrderStatus.ON_WAY,
    OrderStatus.ARRIVED_B,
    OrderStatus.DIDOX_TASDIQDA,
    OrderStatus.UNLOADED,
]
DONE_STATUSES = [OrderStatus.PAID, OrderStatus.COMPLETED, OrderStatus.CANCELLED]


# ─── YORDAMCHI ────────────────────────────────────────────────────────────────
def _point_display(name: str, lat, lon) -> str:
    if lat and lon:
        maps_link = f"https://maps.google.com/?q={lat},{lon}"
        return f"{name}\n   🗺 <a href='{maps_link}'>Xaritada ko'rish</a>"
    return name


# ─── 15 DAQIQALIK TAYMER ─────────────────────────────────────────────────────
async def location_timer_logic(order_id: int, bot: Bot, driver_name: str, disp_tg_id: int, logist_tg_id: int):
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
        await message.answer("👋 Xush kelibsiz!\nYukingiz holatini kuzatishingiz mumkin.", reply_markup=get_client_main_keyboard())
    else:
        try:
            await message.bot.send_message(
                chat_id=FOUNDER_ID,
                text=(
                    f"🔔 <b>Yangi xodim so'rovi!</b>\n\n"
                    f"👤 Ism: {user.full_name}\n"
                    f"🆔 ID: <code>{user.telegram_id}</code>\n"
                    f"Username: @{user.username or 'Yoq'}\n\nRol bering:"
                ),
                parse_mode="HTML",
                reply_markup=get_admin_approve_keyboard(user.telegram_id),
            )
        except Exception as e:
            logging.error(f"Founderga xabar: {e}")
        await message.answer("⏳ So'rovingiz admin tasdig'ida. Iltimos, kutib turing.")


# ─── KONTAKT ─────────────────────────────────────────────────────────────────
@logist_router.message(F.contact)
async def handle_contact(message: Message, user: User):
    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone
    async with async_session() as session:
        await session.execute(update(User).where(User.telegram_id == user.telegram_id).values(phone=phone))
        await session.commit()
    await message.answer(f"✅ Raqamingiz ({phone}) qabul qilindi.\n\n/start bosing.", reply_markup=ReplyKeyboardRemove())


# ─── BUYURTMALARIM ───────────────────────────────────────────────────────────
@logist_router.message(F.text == "📋 Buyurtmalarim")
async def my_orders(message: Message, user: User):
    if user.role != UserRole.LOGIST:
        return
    async with async_session() as session:
        active_orders = (
            await session.execute(
                select(Order)
                .where(Order.logist_id == user.telegram_id, Order.status.in_(ACTIVE_STATUSES))
                .order_by(Order.id.desc())
            )
        ).scalars().all()

    done_btn = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📁 Tugatilgan buyurtmalar", callback_data="logist_done_orders_0")
    ]])

    if not active_orders:
        await message.answer("📭 Hozirda faol buyurtmalaringiz yo'q.", reply_markup=done_btn)
        return

    for o in active_orders:
        status = STATUS_UZ.get(o.status.value, o.status.value)
        kb = InlineKeyboardBuilder()
        if o.status == OrderStatus.NEW:
            kb.button(text="📋 Dispetcher biriktirish", callback_data=f"reassign_disp_{o.id}")
        elif o.status == OrderStatus.DISPATCHER_ASSIGNED:
            kb.button(text="📌 Dispetcherni o'zgartirish", callback_data=f"reassign_disp_{o.id}")
        elif o.status == OrderStatus.ARRIVED_B:
            kb.button(text="📄 Shot-faktura yuborish", callback_data=f"send_invoice_{o.id}")
        kb.adjust(1)

        a_display = _point_display(o.point_a, o.point_a_lat, o.point_a_lon)
        b_display = _point_display(o.point_b, o.point_b_lat, o.point_b_lon)

        await message.answer(
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Buyurtma #{o.id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 Mijoz: {o.client_phone}\n"
            f"📦 Yuk: {o.cargo_description}\n\n"
            f"🔵 <b>A nuqta:</b> {a_display}\n\n"
            f"🔴 <b>B nuqta:</b> {b_display}\n\n"
            f"📊 <b>Holat: {status}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💵 Sotish: {(o.sale_price or 0):,.0f} so'm\n"
            f"💸 Xarajat: {(o.cost_price or 0):,.0f} so'm\n"
            f"💰 Foyda: {((o.sale_price or 0) - (o.cost_price or 0)):,.0f} so'm\n"
            f"━━━━━━━━━━━━━━━━━━",
            reply_markup=kb.as_markup() if kb.export() else None,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    await message.answer(
        f"📋 Faol buyurtmalar: <b>{len(active_orders)} ta</b>",
        reply_markup=done_btn,
        parse_mode="HTML",
    )


@logist_router.callback_query(F.data.startswith("logist_done_orders_"))
async def logist_done_orders(callback: CallbackQuery, user: User):
    page = int(callback.data.split("_")[3])
    per_page = 5
    async with async_session() as session:
        all_done = (
            await session.execute(
                select(Order)
                .where(Order.logist_id == user.telegram_id, Order.status.in_(DONE_STATUSES))
                .order_by(Order.id.desc())
            )
        ).scalars().all()

    total = len(all_done)
    if not total:
        await callback.answer("Tugatilgan buyurtmalar yo'q!", show_alert=True)
        return

    start = page * per_page
    end   = start + per_page
    chunk = all_done[start:end]

    for o in chunk:
        status = STATUS_UZ.get(o.status.value, o.status.value)
        await callback.message.answer(
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Buyurtma #{o.id}</b> — {status}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📦 {o.cargo_description}\n"
            f"🔵 {o.point_a} → 🔴 {o.point_b}\n"
            f"💵 {(o.sale_price or 0):,.0f} | 💸 {(o.cost_price or 0):,.0f} | "
            f"💰 {((o.sale_price or 0)-(o.cost_price or 0)):,.0f} so'm\n"
            f"━━━━━━━━━━━━━━━━━━",
            parse_mode="HTML",
        )

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"logist_done_orders_{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"logist_done_orders_{page+1}"))

    await callback.message.answer(
        f"📁 Tugatilgan: {start+1}–{min(end,total)} / {total} ta",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[nav]) if nav else None,
    )
    await callback.answer()


@logist_router.callback_query(F.data.startswith("reassign_disp_"))
async def reassign_dispatcher(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[2])
    async with async_session() as session:
        dispatchers = (await session.execute(select(User).where(User.role == UserRole.DISPATCHER))).scalars().all()
    await state.update_data(current_order_id=order_id)
    await callback.message.answer("📋 Dispetcherni tanlang:", reply_markup=get_dispatchers_keyboard(dispatchers))


# ─── STATISTIKA ──────────────────────────────────────────────────────────────
@logist_router.message(F.text == "📊 Statistika")
async def show_stats(message: Message, user: User):
    if user.role != UserRole.LOGIST:
        return
    async with async_session() as session:
        total = (await session.execute(select(func.count(Order.id)).where(Order.logist_id == user.telegram_id))).scalar() or 0
        today = datetime.datetime.utcnow().date()
        today_count = (await session.execute(
            select(func.count(Order.id)).where(Order.logist_id == user.telegram_id, func.date(Order.created_at) == today)
        )).scalar() or 0
    await message.answer(
        f"📊 <b>Sizning statistikangiz:</b>\n\n"
        f"📋 Jami buyurtmalar: {total} ta\n"
        f"📅 Bugun yaratilgan: {today_count} ta",
        parse_mode="HTML",
    )


@logist_router.message(F.text == "➕ Yangi buyurtma")
async def start_order(message: Message, user: User, state: FSMContext):
    if user.role != UserRole.LOGIST:
        return
    await message.answer("👤 Mijoz ismi yoki kompaniya nomini kiriting:")
    await state.set_state(OrderCreation.waiting_for_client_name)


# 1. Mijoz ismi
@logist_router.message(OrderCreation.waiting_for_client_name, F.text)
async def get_name(message: Message, state: FSMContext):
    await state.update_data(c_name=message.text.strip())
    await message.answer("📞 Mijoz telefon raqamini kiriting:\n\n<i>Misol: +998901234567</i>", parse_mode="HTML")
    await state.set_state(OrderCreation.waiting_for_client_phone)


# 2. Telefon
@logist_router.message(OrderCreation.waiting_for_client_phone, F.text)
async def get_phone(message: Message, state: FSMContext):
    phone = message.text.strip().replace(" ", "")
    if not re.match(r"^\+998\d{9}$", phone):
        await message.answer("❌ Xato format! Qaytadan kiriting:\n\n<i>Misol: +998901234567</i>", parse_mode="HTML")
        return
    await state.update_data(c_phone=phone)
    await message.answer("📦 Yuk tavsifini kiriting:\n\n<i>Misol: Paxta, 20 tonna, qoplarda</i>", parse_mode="HTML")
    await state.set_state(OrderCreation.waiting_for_cargo_desc)


# 3. Yuk tavsifi
@logist_router.message(OrderCreation.waiting_for_cargo_desc, F.text)
async def get_cargo(message: Message, state: FSMContext):
    await state.update_data(cargo=message.text.strip())
    await message.answer(
        "🔵 <b>1-qadam: A nuqta — YUKLASH joyi</b>\n\n"
        "A nuqtaning <b>manzilini</b> kiriting:\n\n"
        "<i>Misol: Toshkent, Yunusobod tumani, Navoiy ko'chasi 5</i>",
        parse_mode="HTML",
    )
    await state.set_state(OrderCreation.waiting_for_point_a_name)


# 4. A nuqta manzili (faqat F.text — boshqa media qabul qilinmaydi)
@logist_router.message(OrderCreation.waiting_for_point_a_name, F.text)
async def get_point_a_name(message: Message, state: FSMContext):
    await state.update_data(p_a=message.text.strip())
    await message.answer(
        "🔵 <b>2-qadam: A nuqtaning lokatsiyasini tashlang</b>\n\n"
        "📌 Qanday yuborish:\n"
        "1️⃣ 📎 ikonkasiga bosing\n"
        "2️⃣ <b>Location</b> ni tanlang\n"
        "3️⃣ Xaritadan A nuqtani topib yuboring\n\n"
        "⚠️ <b>Lokatsiya majburiy — o'tkazib bo'lmaydi!</b>",
        parse_mode="HTML",
    )
    await state.set_state(OrderCreation.waiting_for_point_a_location)


# Agar A nuqta state'da matn kelsa — eslatma ber (stuck emas)
@logist_router.message(OrderCreation.waiting_for_point_a_name)
async def get_point_a_name_wrong(message: Message, state: FSMContext):
    await message.answer(
        "⚠️ Iltimos, A nuqtaning <b>manzilini matn sifatida</b> yozing.\n\n"
        "<i>Misol: Toshkent, Yunusobod, Navoiy ko'chasi 5</i>",
        parse_mode="HTML",
    )


# 5. A nuqta lokatsiyasi
@logist_router.message(OrderCreation.waiting_for_point_a_location, F.location)
async def get_point_a_location(message: Message, state: FSMContext):
    await state.update_data(p_a_lat=message.location.latitude, p_a_lon=message.location.longitude)
    data = await state.get_data()
    await message.answer(
        f"✅ <b>A nuqta saqlandi!</b>\n\n"
        f"📍 Manzil: {data['p_a']}\n"
        f"🗺 Lokatsiya: ✅ saqlandi\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔴 <b>3-qadam: B nuqta — TUSHIRISH joyi</b>\n\n"
        f"B nuqtaning <b>manzilini</b> kiriting:\n\n"
        f"<i>Misol: Samarqand, Registon ko'chasi 7</i>",
        parse_mode="HTML",
    )
    await state.set_state(OrderCreation.waiting_for_point_b_name)


# Agar A nuqta location state'da matn/boshqa narsa kelsa
@logist_router.message(OrderCreation.waiting_for_point_a_location)
async def get_point_a_location_fallback(message: Message, state: FSMContext):
    await message.answer(
        "⚠️ <b>Lokatsiya yuborilmadi!</b>\n\n"
        "Iltimos, xaritadan <b>lokatsiya</b> yuboring (matn emas).\n\n"
        "📌 Qanday yuborish:\n"
        "1️⃣ 📎 ikonkasiga bosing\n"
        "2️⃣ <b>Location</b> ni tanlang\n"
        "3️⃣ Xaritadan A nuqtani topib yuboring\n\n"
        "⚠️ <b>Lokatsiya majburiy — o'tkazib bo'lmaydi!</b>",
        parse_mode="HTML",
    )



# 6. B nuqta manzili (faqat F.text)
@logist_router.message(OrderCreation.waiting_for_point_b_name, F.text)
async def get_point_b_name(message: Message, state: FSMContext):
    await state.update_data(p_b=message.text.strip())
    await message.answer(
        "🔴 <b>4-qadam: B nuqtaning lokatsiyasini tashlang</b>\n\n"
        "📌 Qanday yuborish:\n"
        "1️⃣ 📎 ikonkasiga bosing\n"
        "2️⃣ <b>Location</b> ni tanlang\n"
        "3️⃣ Xaritadan B nuqtani topib yuboring\n\n"
        "⚠️ <b>Lokatsiya majburiy — o'tkazib bo'lmaydi!</b>",
        parse_mode="HTML",
    )
    await state.set_state(OrderCreation.waiting_for_point_b_location)


# Agar B nuqta state'da matn emas narsa kelsa
@logist_router.message(OrderCreation.waiting_for_point_b_name)
async def get_point_b_name_wrong(message: Message, state: FSMContext):
    await message.answer(
        "⚠️ Iltimos, B nuqtaning <b>manzilini matn sifatida</b> yozing.\n\n"
        "<i>Misol: Samarqand, Registon ko'chasi 7</i>",
        parse_mode="HTML",
    )


# 7. B nuqta lokatsiyasi
@logist_router.message(OrderCreation.waiting_for_point_b_location, F.location)
async def get_point_b_location(message: Message, state: FSMContext):
    await state.update_data(p_b_lat=message.location.latitude, p_b_lon=message.location.longitude)
    data = await state.get_data()
    await message.answer(
        f"✅ <b>B nuqta saqlandi!</b>\n\n"
        f"📍 Manzil: {data['p_b']}\n"
        f"🗺 Lokatsiya: ✅ saqlandi\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>SOTISH NARXI</b> (mijoz to'laydi)\n\n"
        f"Faqat raqam kiriting:",
        parse_mode="HTML",
    )
    await state.set_state(OrderCreation.waiting_for_sale_price)


# Agar B nuqta location state'da boshqa narsa kelsa
@logist_router.message(OrderCreation.waiting_for_point_b_location)
async def get_point_b_location_fallback(message: Message, state: FSMContext):
    await message.answer(
        "⚠️ <b>Lokatsiya yuborilmadi!</b>\n\n"
        "Iltimos, xaritadan <b>lokatsiya</b> yuboring (matn emas).\n\n"
        "📌 Qanday yuborish:\n"
        "1️⃣ 📎 ikonkasiga bosing\n"
        "2️⃣ <b>Location</b> ni tanlang\n"
        "3️⃣ Xaritadan B nuqtani topib yuboring\n\n"
        "⚠️ <b>Lokatsiya majburiy — o'tkazib bo'lmaydi!</b>",
        parse_mode="HTML",
    )


# 8. Sotish narxi
@logist_router.message(OrderCreation.waiting_for_sale_price, F.text)
async def get_sale_price(message: Message, state: FSMContext):
    clean = "".join(filter(str.isdigit, message.text))
    if not clean:
        await message.answer("❌ Faqat raqam kiriting (masalan: 5000000):")
        return
    await state.update_data(s_price=float(clean))
    await message.answer("💸 <b>XARAJAT NARXI</b> (haydovchiga to'lanadi)\n\nFaqat raqam kiriting:", parse_mode="HTML")
    await state.set_state(OrderCreation.waiting_for_cost_price)


# 9. Xarajat narxi → buyurtma yaratiladi
@logist_router.message(OrderCreation.waiting_for_cost_price, F.text)
async def finish_order(message: Message, state: FSMContext, user: User):
    clean = "".join(filter(str.isdigit, message.text))
    if not clean:
        await message.answer("❌ Faqat raqam kiriting:")
        return

    data = await state.get_data()

    # Majburiy tekshiruv: A va B lokatsiya bo'lishi shart
    if data.get("p_a_lat") is None or data.get("p_a_lon") is None:
        await message.answer(
            "❌ <b>A nuqta lokatsiyasi kiritilmagan!</b>\n\n"
            "Buyurtma yaratish uchun A va B nuqta lokatsiyalari majburiy.\n"
            "Qaytadan boshlash uchun /start bosing.",
            parse_mode="HTML",
        )
        await state.clear()
        return
    if data.get("p_b_lat") is None or data.get("p_b_lon") is None:
        await message.answer(
            "❌ <b>B nuqta lokatsiyasi kiritilmagan!</b>\n\n"
            "Buyurtma yaratish uchun A va B nuqta lokatsiyalari majburiy.\n"
            "Qaytadan boshlash uchun /start bosing.",
            parse_mode="HTML",
        )
        await state.clear()
        return
    async with async_session() as session:
        try:
            order = Order(
                logist_id=user.telegram_id,
                client_phone=data["c_phone"],
                cargo_description=data["cargo"],
                point_a=data["p_a"],
                point_a_lat=data.get("p_a_lat"),
                point_a_lon=data.get("p_a_lon"),
                point_b=data["p_b"],
                point_b_lat=data.get("p_b_lat"),
                point_b_lon=data.get("p_b_lon"),
                sale_price=data["s_price"],
                cost_price=float(clean),
                status=OrderStatus.NEW,
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)

            dispatchers = (await session.execute(select(User).where(User.role == UserRole.DISPATCHER))).scalars().all()
            await state.update_data(current_order_id=order.id)

            a_loc = "✅ bor" if data.get("p_a_lat") else "❌ yo'q"
            b_loc = "✅ bor" if data.get("p_b_lat") else "❌ yo'q"

            await message.answer(
                f"✅ <b>Buyurtma #{order.id} yaratildi!</b>\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📦 Yuk: {data['cargo']}\n\n"
                f"🔵 A nuqta manzili: {data['p_a']}\n"
                f"   📍 Lokatsiya: {a_loc}\n\n"
                f"🔴 B nuqta manzili: {data['p_b']}\n"
                f"   📍 Lokatsiya: {b_loc}\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
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
            dispatcher = (await session.execute(select(User).where(User.id == target_db_id))).scalar_one_or_none()
            if not dispatcher:
                await callback.answer("Dispetcher topilmadi!")
                return

            order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
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

            # Dispetcherga to'liq xabar: manzil + alohida Telegram location xabari
            a_has_loc = bool(order.point_a_lat and order.point_a_lon)
            b_has_loc = bool(order.point_b_lat and order.point_b_lon)

            await callback.bot.send_message(
                chat_id=dispatcher.telegram_id,
                text=(
                    f"🔔 <b>Sizga yangi buyurtma biriktirildi!</b>\n\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"📦 <b>Buyurtma #{order_id}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n\n"
                    f"🔵 <b>A nuqta manzili (Yuklash):</b>\n"
                    f"   {order.point_a}\n"
                    f"   📍 Lokatsiya: {'✅ quyida' if a_has_loc else '❌ kiritilmagan'}\n\n"
                    f"🔴 <b>B nuqta manzili (Tushirish):</b>\n"
                    f"   {order.point_b}\n"
                    f"   📍 Lokatsiya: {'✅ quyida' if b_has_loc else '❌ kiritilmagan'}\n\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"📦 <b>Yuk tavsifi:</b> {order.cargo_description}\n"
                    f"💸 <b>Limit:</b> {order.cost_price:,.0f} so'm\n"
                    f"━━━━━━━━━━━━━━━━━━\n\n"
                    f"📥 <b>Yangi buyurtmalar</b> bo'limidan ko'ring."
                ),
                parse_mode="HTML",
            )

            # A nuqta Telegram location xabari
            if a_has_loc:
                await callback.bot.send_location(
                    chat_id=dispatcher.telegram_id,
                    latitude=order.point_a_lat,
                    longitude=order.point_a_lon,
                )
                await callback.bot.send_message(
                    chat_id=dispatcher.telegram_id,
                    text=f"🔵 Yuqoridagi — <b>A nuqta lokatsiyasi</b>\n📍 {order.point_a}",
                    parse_mode="HTML",
                )

            # B nuqta Telegram location xabari
            if b_has_loc:
                await callback.bot.send_location(
                    chat_id=dispatcher.telegram_id,
                    latitude=order.point_b_lat,
                    longitude=order.point_b_lon,
                )
                await callback.bot.send_message(
                    chat_id=dispatcher.telegram_id,
                    text=f"🔴 Yuqoridagi — <b>B nuqta lokatsiyasi</b>\n📍 {order.point_b}",
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
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
        if not order:
            return
        order.status = OrderStatus.DIDOX_TASDIQDA
        dispatcher = (await session.execute(select(User).where(User.telegram_id == order.dispatcher_id))).scalar_one_or_none()
        client     = (await session.execute(select(User).where(User.phone == order.client_phone))).scalar_one_or_none()
        await session.commit()

    if order.driver_id:
        kb = InlineKeyboardBuilder()
        kb.button(text="📤 Yuk tushirdim (Media yuborish)", callback_data=f"st_unload_media_{order_id}")
        try:
            await message.bot.send_message(
                chat_id=order.driver_id,
                text=(
                    f"✅ <b>RUXSAT BERILDI!</b>\n\n"
                    f"📦 Buyurtma #{order_id}\n"
                    f"🔵 {order.point_a} → 🔴 {order.point_b}\n\n"
                    f"Yukni tushirishni boshlashingiz mumkin.\n"
                    f"Tushirgach, media (rasm va video) yuborishingiz kerak."
                ),
                reply_markup=kb.as_markup(),
                parse_mode="HTML",
            )
        except Exception: pass

    if dispatcher:
        try:
            await message.bot.send_document(
                chat_id=dispatcher.telegram_id,
                document=message.document.file_id,
                caption=f"📄 #{order_id} — Logist shot-faktura yubordi. Haydovchiga ruxsat berildi.",
            )
        except Exception: pass

    if client and client.telegram_id:
        try:
            await message.bot.send_document(
                chat_id=client.telegram_id,
                document=message.document.file_id,
                caption=f"🎉 <b>Yukingiz #{order_id} manzilga yetib keldi!</b>\n\nShot-faktura yuborildi.",
                parse_mode="HTML",
            )
        except Exception: pass

    await message.answer(f"✅ <b>#{order_id} faktura qabul qilindi!</b>\nHaydovchiga ruxsat berildi.", parse_mode="HTML")
    await state.clear()

