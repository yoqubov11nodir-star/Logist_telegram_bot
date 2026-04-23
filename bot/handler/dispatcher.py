import logging
 
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, update

from database.session import async_session
from database.models import User, UserRole, Order, OrderStatus, OrderMedia, OrderLocation
from bot.keyboards.dispatcher_kb import get_dispatcher_main_keyboard
 
dispatcher_router = Router()
 
STATUS_UZ = {
    "NEW":                 "🆕 Yangi",
    "DISPATCHER_ASSIGNED": "📋 Haydovchi kutilmoqda",
    "DRIVER_ASSIGNED":     "🚛 Haydovchi yo'lda (A nuqtaga)",
    "ARRIVED_A":           "📍 A nuqtada — yuk ortilmoqda",
    "LOADING":             "📦 Yuk ortildi — yo'lga chiqmoqda",
    "ON_WAY":              "🚚 Yo'lda",
    "ARRIVED_B":           "🏁 B nuqtada — kutilmoqda",
    "DIDOX_TASDIQDA":      "✅ Faktura yuborildi — tushirish",
    "UNLOADED":            "📤 Yuk tushirildi — to'lov",
    "PAID":                "💰 To'langan",
    "COMPLETED":           "✅ Yakunlandi",
    "CANCELLED":           "❌ Bekor qilindi",
}
 
ACTIVE_STATUSES = [
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
 
 
class DispatcherStates(StatesGroup):
    waiting_for_vehicle_number       = State()
    waiting_for_rejection_reason     = State()
    waiting_for_driver_fullname      = State()
    waiting_for_driver_reg_photo     = State()
    waiting_for_driver_lic_photo     = State()
 
 
# ─── YANGI BUYURTMALAR ───────────────────────────────────────────────────────
@dispatcher_router.message(F.text == "📥 Yangi buyurtmalar")
async def view_assigned_orders(message: Message, user: User):
    if user.role != UserRole.DISPATCHER:
        return
    async with async_session() as session:
        orders = (await session.execute(
            select(Order).where(
                Order.dispatcher_id == user.telegram_id,
                Order.status == OrderStatus.DISPATCHER_ASSIGNED,
            )
        )).scalars().all()
 
    if not orders:
        await message.answer("📭 Sizga biriktirilgan yangi buyurtmalar yo'q.")
        return
 
    for order in orders:
        kb = InlineKeyboardBuilder()
        kb.button(text="🚛 Haydovchi biriktirish", callback_data=f"find_driver_{order.id}")
        price = f"{order.cost_price:,.0f}" if order.cost_price else "0"
        await message.answer(
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Yangi buyurtma #{order.id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"🔵 <b>A nuqta (Yuklash):</b>\n   📍 {order.point_a}\n\n"
            f"🔴 <b>B nuqta (Tushirish):</b>\n   📍 {order.point_b}\n\n"
            f"📦 <b>Yuk tavsifi:</b> {order.cargo_description}\n"
            f"💸 <b>Limit:</b> {price} so'm\n"
            f"━━━━━━━━━━━━━━━━━━",
            reply_markup=kb.as_markup(), parse_mode="HTML",
        )
 
 
# ─── BUYURTMALARIM (faol + tugatilgan) ───────────────────────────────────────
@dispatcher_router.message(F.text == "📋 Buyurtmalarim")
async def dispatcher_my_orders(message: Message, user: User):
    if user.role != UserRole.DISPATCHER:
        return
    async with async_session() as session:
        active_orders = (await session.execute(
            select(Order).where(
                Order.dispatcher_id == user.telegram_id,
                Order.status.in_(ACTIVE_STATUSES),
            ).order_by(Order.id.desc())
        )).scalars().all()
 
    if not active_orders:
        await message.answer(
            "📭 Hozirda faol buyurtmalaringiz yo'q.\n\n"
            "Tugatilgan buyurtmalarni ko'rish uchun tugmani bosing 👇",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="📁 Tugatilgan buyurtmalar", callback_data="disp_done_orders_0")
            ]])
        )
        return
 
    for o in active_orders:
        status_name = STATUS_UZ.get(o.status.value, o.status.value)
        kb = InlineKeyboardBuilder()
 
        # Statusga qarab tugmalar
        if o.status == OrderStatus.DISPATCHER_ASSIGNED:
            kb.button(text="🚛 Haydovchi biriktirish", callback_data=f"find_driver_{o.id}")
        elif o.status == OrderStatus.ON_WAY:
            kb.button(text="✅ Yo'lga chiqishni tasdiq", callback_data=f"disp_confirm_onway_{o.id}")
        elif o.status == OrderStatus.ARRIVED_B:
            kb.button(text="✅ B nuqtani tasdiqlash", callback_data=f"st_arrived_b_confirm_{o.id}")
            kb.button(text="❌ Rad etish", callback_data=f"reject_b_arrival_{o.id}")
        elif o.status == OrderStatus.UNLOADED:
            kb.button(text="💳 To'lov amalga oshirildi", callback_data=f"pay_order_{o.id}")
        kb.adjust(1)
 
        await message.answer(
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Buyurtma #{o.id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"🔵 <b>A nuqta:</b> {o.point_a}\n"
            f"🔴 <b>B nuqta:</b> {o.point_b}\n\n"
            f"📦 Yuk: {o.cargo_description}\n"
            f"🚘 Mashina: {o.vehicle_number or '—'}\n\n"
            f"📊 <b>Holat: {status_name}</b>\n"
            f"━━━━━━━━━━━━━━━━━━",
            reply_markup=kb.as_markup() if kb.export() else InlineKeyboardMarkup(inline_keyboard=[]),
            parse_mode="HTML",
        )
 
    # Pastda tugatilganlarni ko'rish tugmasi
    await message.answer(
        f"📋 Jami faol: <b>{len(active_orders)} ta</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📁 Tugatilgan buyurtmalar", callback_data="disp_done_orders_0")
        ]]),
        parse_mode="HTML",
    )
 
 
# ─── TUGATILGAN BUYURTMALAR (pagination) ─────────────────────────────────────
@dispatcher_router.callback_query(F.data.startswith("disp_done_orders_"))
async def dispatcher_done_orders(callback: CallbackQuery, user: User):
    page = int(callback.data.split("_")[3])
    per_page = 5
 
    async with async_session() as session:
        all_done = (await session.execute(
            select(Order).where(
                Order.dispatcher_id == user.telegram_id,
                Order.status.in_(DONE_STATUSES),
            ).order_by(Order.id.desc())
        )).scalars().all()
 
    total = len(all_done)
    if not total:
        await callback.answer("Tugatilgan buyurtmalar yo'q!", show_alert=True)
        return
 
    start = page * per_page
    end   = start + per_page
    chunk = all_done[start:end]
 
    for o in chunk:
        status_name = STATUS_UZ.get(o.status.value, o.status.value)
        await callback.message.answer(
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Buyurtma #{o.id}</b> — {status_name}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🔵 {o.point_a} → 🔴 {o.point_b}\n"
            f"📦 {o.cargo_description}\n"
            f"━━━━━━━━━━━━━━━━━━",
            parse_mode="HTML",
        )
 
    # Pagination tugmalari
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"disp_done_orders_{page-1}"))
    if end < total:
        nav_buttons.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"disp_done_orders_{page+1}"))
 
    kb_rows = []
    if nav_buttons:
        kb_rows.append(nav_buttons)
 
    await callback.message.answer(
        f"📁 Tugatilgan: {start+1}–{min(end, total)} / {total} ta",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows) if kb_rows else None,
    )
    await callback.answer()
 
 
# ─── HAYDOVCHILAR RO'YXATI ───────────────────────────────────────────────────
@dispatcher_router.callback_query(F.data.startswith("find_driver_"))
async def list_drivers(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    async with async_session() as session:
        drivers = (await session.execute(select(User).where(User.role == UserRole.DRIVER))).scalars().all()
    if not drivers:
        await callback.answer("Bazada haydovchilar yo'q!", show_alert=True)
        return
    kb = InlineKeyboardBuilder()
    for d in drivers:
        card = f" | 💳{d.card_number}" if d.card_number else " | karta yo'q"
        kb.button(text=f"👨‍✈️ {d.full_name}{card}", callback_data=f"ask_vnum_{order_id}_{d.id}")
    kb.button(text="➕ Yangi haydovchi qo'shish", callback_data=f"add_new_driver_{order_id}")
    kb.adjust(1)
    await callback.message.edit_text(
        f"👨‍✈️ <b>#{order_id} uchun haydovchi tanlang:</b>",
        reply_markup=kb.as_markup(), parse_mode="HTML",
    )
 
 
# ─── YANGI HAYDOVCHI QO'SHISH ────────────────────────────────────────────────
@dispatcher_router.callback_query(F.data.startswith("add_new_driver_"))
async def start_add_driver(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[3])
    await state.update_data(pending_order_id=order_id, driver_reg_photos=[], driver_lic_photos=[])
    await state.set_state(DispatcherStates.waiting_for_driver_fullname)
    await callback.message.answer(
        "➕ <b>Yangi haydovchi qo'shish</b>\n\n"
        "1️⃣ Haydovchining <b>ism-familyasini</b> kiriting:\n\n"
        "<i>Misol: Karimov Jahongir</i>",
        parse_mode="HTML",
    )
 
 
@dispatcher_router.message(DispatcherStates.waiting_for_driver_fullname)
async def get_driver_fullname(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name.split()) < 2:
        await message.answer("❌ To'liq ism-familya kiriting.\n<i>Misol: Karimov Jahongir</i>", parse_mode="HTML")
        return
    await state.update_data(driver_fullname=name)
    await state.set_state(DispatcherStates.waiting_for_driver_reg_photo)
    await message.answer(
        "2️⃣ <b>Texnik pasport rasmlarini yuboring</b>\n\n"
        "📸 Minimal: 2 ta | Maksimal: 4 ta\n\n"
        "<i>Hammasi tayyor bo'lgach tugmani bosing.</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Tex pasport tayyor", callback_data="driver_reg_done")
        ]]),
        parse_mode="HTML",
    )
 
 
@dispatcher_router.message(DispatcherStates.waiting_for_driver_reg_photo, F.photo)
async def collect_reg_photos(message: Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("driver_reg_photos", [])
    if len(photos) >= 4:
        await message.answer("⚠️ Maksimal 4 ta rasm!")
        return
    photos.append(message.photo[-1].file_id)
    await state.update_data(driver_reg_photos=photos)
    remaining = 4 - len(photos)
    msg = f"Yana {remaining} ta yuborishingiz mumkin." if remaining > 0 else "To'ldi (4/4)!"
    await message.answer(f"✅ Qabul qilindi ({len(photos)}/4)\n{msg}")
 
 
@dispatcher_router.callback_query(F.data == "driver_reg_done")
async def reg_photos_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if len(data.get("driver_reg_photos", [])) < 2:
        await callback.answer("Kamida 2 ta tex pasport rasmi kerak!", show_alert=True)
        return
    await state.set_state(DispatcherStates.waiting_for_driver_lic_photo)
    await callback.message.answer(
        "3️⃣ <b>Haydovchilik guvohnomasi (Prava) rasmlarini yuboring</b>\n\n"
        "📸 Minimal: 2 ta | Maksimal: 4 ta",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Prava tayyor", callback_data="driver_lic_done")
        ]]),
        parse_mode="HTML",
    )
 
 
@dispatcher_router.message(DispatcherStates.waiting_for_driver_lic_photo, F.photo)
async def collect_lic_photos(message: Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("driver_lic_photos", [])
    if len(photos) >= 4:
        await message.answer("⚠️ Maksimal 4 ta rasm!")
        return
    photos.append(message.photo[-1].file_id)
    await state.update_data(driver_lic_photos=photos)
    remaining = 4 - len(photos)
    msg = f"Yana {remaining} ta yuborishingiz mumkin." if remaining > 0 else "To'ldi (4/4)!"
    await message.answer(f"✅ Qabul qilindi ({len(photos)}/4)\n{msg}")
 
 
@dispatcher_router.callback_query(F.data == "driver_lic_done")
async def lic_photos_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lic_photos = data.get("driver_lic_photos", [])
    if len(lic_photos) < 2:
        await callback.answer("Kamida 2 ta prava rasmi kerak!", show_alert=True)
        return
 
    fullname   = data.get("driver_fullname", "Noma'lum")
    reg_photos = data.get("driver_reg_photos", [])
 
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Qabul qilish", callback_data="confirm_new_driver")
    kb.button(text="❌ Rad etish",    callback_data="reject_new_driver_btn")
    kb.adjust(2)
 
    await callback.message.answer(
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>Yangi haydovchi ma'lumotlari:</b>\n\n"
        f"👤 Ism-familya: <b>{fullname}</b>\n"
        f"📄 Tex pasport: {len(reg_photos)} ta rasm\n"
        f"🪪 Prava: {len(lic_photos)} ta rasm\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"Qabul qilasizmi?",
        reply_markup=kb.as_markup(), parse_mode="HTML",
    )
    for fid in reg_photos:
        try: await callback.bot.send_photo(chat_id=callback.from_user.id, photo=fid)
        except Exception: pass
    for fid in lic_photos:
        try: await callback.bot.send_photo(chat_id=callback.from_user.id, photo=fid)
        except Exception: pass
 
 
@dispatcher_router.callback_query(F.data == "confirm_new_driver")
async def confirm_new_driver(callback: CallbackQuery, state: FSMContext):
    data       = await state.get_data()
    fullname   = data.get("driver_fullname", "Noma'lum")
    reg_photos = data.get("driver_reg_photos", [])
    lic_photos = data.get("driver_lic_photos", [])
 
    await callback.message.edit_text(
        f"✅ <b>{fullname}</b> qabul qilindi!\n\n"
        f"Haydovchi /start bosib botga kirsin va telefon raqamini ulashsin.\n"
        f"So'ng unga DRIVER roli beriladi.",
        parse_mode="HTML",
    )
    import os
    FOUNDER_ID = int(os.getenv("FOUNDER_ID", 0))
    try:
        await callback.bot.send_message(
            FOUNDER_ID,
            f"🚛 <b>Dispatcher yangi haydovchi qo'shdi!</b>\n\n"
            f"👤 Ism: <b>{fullname}</b>\n"
            f"📄 Tex pasport: {len(reg_photos)} ta\n"
            f"🪪 Prava: {len(lic_photos)} ta\n\n"
            f"Haydovchi botga kirganda unga <b>DRIVER</b> roli bering.",
            parse_mode="HTML",
        )
        for fid in reg_photos + lic_photos:
            await callback.bot.send_photo(FOUNDER_ID, fid)
    except Exception: pass
    await state.clear()
 
 
@dispatcher_router.callback_query(F.data == "reject_new_driver_btn")
async def reject_new_driver_btn(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ Rad etildi.")
    await state.update_data(reject_stage="new_driver")
    await state.set_state(DispatcherStates.waiting_for_rejection_reason)
    await callback.message.answer("Rad etish sababini yozing:")
 
 
# ─── MASHINA RAQAMI SO'RASH ──────────────────────────────────────────────────
@dispatcher_router.callback_query(F.data.startswith("ask_vnum_"))
async def ask_vehicle_number(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    order_id, driver_db_id = parts[2], parts[3]
    await state.update_data(temp_order_id=int(order_id), temp_driver_id=int(driver_db_id))
    await callback.message.answer(
        "🚛 <b>Mashina davlat raqamini kiriting:</b>\n\n<i>Misol: 01A777BA</i>",
        parse_mode="HTML",
    )
    await state.set_state(DispatcherStates.waiting_for_vehicle_number)
 
 
# ─── HAYDOVCHI BIRIKTIRISH ───────────────────────────────────────────────────
@dispatcher_router.message(DispatcherStates.waiting_for_vehicle_number)
async def assign_driver_to_order(message: Message, state: FSMContext):
    v_number     = message.text.upper().strip()
    data         = await state.get_data()
    order_id     = data["temp_order_id"]
    driver_db_id = data["temp_driver_id"]
 
    async with async_session() as session:
        order  = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        driver = (await session.execute(select(User).where(User.id == driver_db_id))).scalar_one()
        order.driver_id      = driver.telegram_id
        order.vehicle_number = v_number
        order.status         = OrderStatus.DRIVER_ASSIGNED
        client = (await session.execute(select(User).where(User.phone == order.client_phone))).scalar_one_or_none()
        await session.commit()
 
    await message.answer(
        f"✅ <b>#{order_id}</b> — {driver.full_name} ({v_number})ga biriktirildi!", parse_mode="HTML",
    )
 
    # Haydovchiga — chiroyli format
    try:
        a_lat = getattr(order, 'point_a_lat', None)
        a_lon = getattr(order, 'point_a_lon', None)
        b_lat = getattr(order, 'point_b_lat', None)
        b_lon = getattr(order, 'point_b_lon', None)
 
        a_loc = f"\n   🗺 https://maps.google.com/?q={a_lat},{a_lon}" if a_lat and a_lon else ""
        b_loc = f"\n   🗺 https://maps.google.com/?q={b_lat},{b_lon}" if b_lat and b_lon else ""
 
        await message.bot.send_message(
            chat_id=driver.telegram_id,
            text=(
                f"🎉 <b>Sizga yangi buyurtma biriktirildi!</b>\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📦 <b>BUYURTMA #{order_id}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"🔵 <b>A NUQTA — YUKLASH JOYI:</b>\n"
                f"   📍 Manzil: {order.point_a}\n"
                f"   🗺 Lokatsiya: {'✅ quyida yuborildi' if a_lat and a_lon else '❌ kiritilmagan'}\n\n"
                f"🔴 <b>B NUQTA — TUSHIRISH JOYI:</b>\n"
                f"   📍 Manzil: {order.point_b}\n"
                f"   🗺 Lokatsiya: {'✅ quyida yuborildi' if b_lat and b_lon else '❌ kiritilmagan'}\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📦 <b>YUK TAVSIFI:</b>\n"
                f"   {order.cargo_description}\n\n"
                f"🚘 <b>Mashina:</b> {v_number}\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"📌 A nuqtaga boring ➡️ <b>🚚 Mening yuklarim</b> ➡️ <b>✅ A nuqtaga yetib keldim</b>"
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        # A location xaritada
        if a_lat and a_lon:
            await message.bot.send_location(chat_id=driver.telegram_id, latitude=a_lat, longitude=a_lon)
            await message.bot.send_message(
                chat_id=driver.telegram_id,
                text=f"🔵 Yuqoridagi — <b>A nuqta lokatsiyasi</b>\n📍 {order.point_a}",
                parse_mode="HTML",
            )
        # B location ham berish (ma'lumot uchun)
        if b_lat and b_lon:
            await message.bot.send_location(chat_id=driver.telegram_id, latitude=b_lat, longitude=b_lon)
            await message.bot.send_message(
                chat_id=driver.telegram_id,
                text=f"🔴 Yuqoridagi — <b>B nuqta lokatsiyasi</b>\n📍 {order.point_b}\n<i>(Tushirish joyi)</i>",
                parse_mode="HTML",
            )
    except Exception: pass
 
    if client and client.telegram_id:
        try:
            await message.bot.send_message(
                chat_id=client.telegram_id,
                text=(
                    f"🚛 <b>#{order_id} buyurtmangiz uchun haydovchi biriktirildi!</b>\n\n"
                    f"🚘 Mashina: {v_number}\n"
                    f"👨‍✈️ Haydovchi: {driver.full_name}"
                ),
                parse_mode="HTML",
            )
        except Exception: pass
    await state.clear()
 
 
# ─── LOADING_A TASDIQLASH / RAD ETISH ────────────────────────────────────────
@dispatcher_router.callback_query(F.data.startswith("approve_loading_a_"))
async def approve_order_load(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[3])
    async with async_session() as session:
        order  = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        order.status = OrderStatus.LOADING
        driver = (await session.execute(select(User).where(User.telegram_id == order.driver_id))).scalar_one_or_none()
        await session.commit()
    await callback.message.edit_text(f"✅ <b>#{order_id}</b> — Yuk ortilishi tasdiqlandi.", parse_mode="HTML")
    if driver:
        try:
            await callback.bot.send_message(
                chat_id=driver.telegram_id,
                text=(
                    f"✅ <b>Dispetcher yuk ortilganini tasdiqladi!</b>\n\n"
                    f"Yo'lga chiqishingiz mumkin! 🚀\n\n"
                    f"📌 <b>Mening yuklarim</b> → <b>🚀 Yo'lga chiqdim</b>"
                ),
                parse_mode="HTML",
            )
        except Exception: pass
 
 
@dispatcher_router.callback_query(F.data.startswith("reject_loading_a_"))
async def reject_order_load(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[3])
    await state.update_data(reject_order_id=order_id, reject_stage="loading_a")
    await state.set_state(DispatcherStates.waiting_for_rejection_reason)
    await callback.message.answer("❌ <b>Rad etish sababini yozing:</b>", parse_mode="HTML")
 
 
# ─── UNLOADING_B TASDIQLASH / RAD ETISH ──────────────────────────────────────
@dispatcher_router.callback_query(F.data.startswith("approve_unloading_b_"))
async def approve_unloading_b(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[3])
    async with async_session() as session:
        order    = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        order.status = OrderStatus.UNLOADED
        driver   = (await session.execute(select(User).where(User.telegram_id == order.driver_id))).scalar_one_or_none()
        cashiers = (await session.execute(select(User).where(User.role == UserRole.CASHIER))).scalars().all()
        logist   = (await session.execute(select(User).where(User.telegram_id == order.logist_id))).scalar_one_or_none()
        client   = (await session.execute(select(User).where(User.phone == order.client_phone))).scalar_one_or_none()
        await session.commit()
 
    await callback.message.edit_text(
        f"✅ <b>#{order_id}</b> — Yuk tushirilishi tasdiqlandi. Kassirga yuborildi.", parse_mode="HTML",
    )
    if driver and driver.telegram_id:
        try:
            await callback.bot.send_message(
                chat_id=driver.telegram_id,
                text=(
                    f"✅ <b>Yuk tushirildi!</b>\n\n📦 Buyurtma: <b>#{order_id}</b>\n"
                    f"💳 Karta: <code>{driver.card_number or 'Kiritilmagan'}</code>\n\n"
                    f"💰 To'lov tez orada amalga oshiriladi."
                ),
                parse_mode="HTML",
            )
        except Exception: pass
 
    for cashier in cashiers:
        if cashier.telegram_id:
            kb = InlineKeyboardBuilder()
            kb.button(text="💵 To'lov qildim", callback_data=f"pay_order_{order_id}")
            try:
                await callback.bot.send_message(
                    chat_id=cashier.telegram_id,
                    text=(
                        f"🔔 <b>TO'LOV KERAK! #{order_id}</b>\n\n"
                        f"👨‍✈️ Haydovchi: {driver.full_name if driver else '—'}\n"
                        f"💳 Karta: <code>{driver.card_number if driver and driver.card_number else 'Kiritilmagan'}</code>\n"
                        f"💰 <b>Summa: {order.cost_price:,.0f} so'm</b>"
                    ),
                    reply_markup=kb.as_markup(), parse_mode="HTML",
                )
            except Exception: pass
 
    if logist and logist.telegram_id:
        try:
            await callback.bot.send_message(logist.telegram_id,
                f"✅ <b>#{order_id} yuk tushirildi!</b>\nTo'lov jarayoni boshlandi.", parse_mode="HTML")
        except Exception: pass
 
    if client and client.telegram_id:
        try:
            await callback.bot.send_message(client.telegram_id,
                f"🎉 <b>Yukingiz yetkazildi!</b>\nBuyurtma <b>#{order_id}</b> yakunlandi.",
                parse_mode="HTML")
        except Exception: pass
 
 
@dispatcher_router.callback_query(F.data.startswith("reject_unloading_b_"))
async def reject_unloading_b(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[3])
    await state.update_data(reject_order_id=order_id, reject_stage="unloading_b")
    await state.set_state(DispatcherStates.waiting_for_rejection_reason)
    await callback.message.answer("❌ <b>Rad etish sababini yozing:</b>", parse_mode="HTML")
 
 
# ─── RAD ETISH SABABI ────────────────────────────────────────────────────────
@dispatcher_router.message(DispatcherStates.waiting_for_rejection_reason)
async def process_rejection_reason(message: Message, state: FSMContext):
    data     = await state.get_data()
    order_id = data.get("reject_order_id")
    stage    = data.get("reject_stage")
    reason   = message.text
 
    if stage == "new_driver":
        await message.answer("✅ Qayd etildi.")
        await state.clear()
        return
 
    async with async_session() as session:
        order  = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        if stage == "loading_a":
            order.status = OrderStatus.ARRIVED_A
        elif stage == "unloading_b":
            order.status = OrderStatus.ON_WAY
        elif stage == "b_arrival":
            order.status = OrderStatus.ON_WAY
        driver = (await session.execute(select(User).where(User.telegram_id == order.driver_id))).scalar_one_or_none()
        await session.commit()
 
    await message.answer("✅ Rad etildi. Haydovchiga xabar yuborildi.")
    if driver:
        stage_text = {"loading_a": "yuk ortish", "unloading_b": "yuk tushirish", "b_arrival": "B nuqtaga kelish"}.get(stage, stage)
        try:
            await message.bot.send_message(
                chat_id=driver.telegram_id,
                text=(
                    f"❌ <b>Media rad etildi</b>\n\n"
                    f"📦 Buyurtma: #{order_id}\n"
                    f"📋 Bosqich: {stage_text}\n\n"
                    f"💬 <b>Sabab:</b> {reason}\n\n"
                    f"To'g'ri va aniq media yuborib, qayta urinib ko'ring. 📸"
                ),
                parse_mode="HTML",
            )
        except Exception: pass
    await state.clear()
 
 
# ─── YO'LGA CHIQISHNI TASDIQLASH ─────────────────────────────────────────────
@dispatcher_router.callback_query(F.data.startswith("disp_confirm_onway_"))
async def confirm_on_way(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[3])
    async with async_session() as session:
        order  = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        client = (await session.execute(select(User).where(User.phone == order.client_phone))).scalar_one_or_none()
    await callback.message.edit_text(
        f"✅ <b>#{order_id}</b> — Yo'lga chiqish tasdiqlandi.", parse_mode="HTML",
    )
    if client and client.telegram_id:
        try:
            await callback.bot.send_message(
                client.telegram_id,
                f"🚛 <b>#{order_id} yukingiz yo'lda!</b>\n\n"
                f"📍 {order.point_a} → {order.point_b}",
                parse_mode="HTML",
            )
        except Exception: pass
 
 
# ─── B NUQTANI TASDIQLASH ─────────────────────────────────────────────────────
@dispatcher_router.callback_query(F.data.startswith("st_arrived_b_confirm_"))
async def confirm_arrived_b(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[4])
    async with async_session() as session:
        order  = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        logist = (await session.execute(select(User).where(User.telegram_id == order.logist_id))).scalar_one_or_none()
        driver = (await session.execute(select(User).where(User.telegram_id == order.driver_id))).scalar_one_or_none()
        if not logist:
            await callback.answer("Logist topilmadi!", show_alert=True)
            return
        order.status = OrderStatus.ARRIVED_B
        await session.commit()
 
    await callback.message.edit_text(
        f"✅ <b>#{order_id}</b> — B nuqtaga kelgani tasdiqlandi.", parse_mode="HTML",
    )
    kb_logist = InlineKeyboardBuilder()
    kb_logist.button(text="📄 Shot-faktura yuborish", callback_data=f"send_invoice_{order_id}")
    try:
        await callback.bot.send_message(
            chat_id=logist.telegram_id,
            text=(
                f"⚡ <b>#{order_id} — Haydovchi B nuqtada!</b>\n\n"
                f"📦 {order.cargo_description}\n"
                f"🔵 {order.point_a} → 🔴 {order.point_b}\n\n"
                f"Didox tizimidan shot-fakturani yuklab, botga yuboring 👇"
            ),
            reply_markup=kb_logist.as_markup(), parse_mode="HTML",
        )
    except Exception: pass
 
    if driver and driver.telegram_id:
        try:
            await callback.bot.send_message(driver.telegram_id,
                f"⏳ <b>Tasdiqlandi!</b>\nLogist fakturani yuborishini kuting.", parse_mode="HTML")
        except Exception: pass
 
 
# ─── B NUQTAGA KELISHNI RAD ETISH ────────────────────────────────────────────
@dispatcher_router.callback_query(F.data.startswith("reject_b_arrival_"))
async def reject_b_arrival(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[3])
    await state.update_data(reject_order_id=order_id, reject_stage="b_arrival")
    await state.set_state(DispatcherStates.waiting_for_rejection_reason)
    await callback.message.answer(
        "❌ <b>Rad etish sababini yozing:</b>\n<i>(Sabab haydovchiga yuboriladi)</i>",
        parse_mode="HTML",
    )
 
 
# ─── STATISTIKA ──────────────────────────────────────────────────────────────
@dispatcher_router.message(F.text == "📊 Mening statistikam")
async def dispatcher_stats(message: Message, user: User):
    if user.role != UserRole.DISPATCHER:
        return
    async with async_session() as session:
        orders = (await session.execute(select(Order).where(Order.dispatcher_id == user.telegram_id))).scalars().all()
    total     = len(orders)
    completed = len([o for o in orders if o.status in (OrderStatus.PAID, OrderStatus.COMPLETED)])
    active    = len([o for o in orders if o.status in ACTIVE_STATUSES])
    await message.answer(
        f"📊 <b>Sizning statistikangiz:</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📋 Jami: {total} ta\n"
        f"⏳ Faol: {active} ta\n"
        f"✅ Yakunlangan: {completed} ta\n"
        f"━━━━━━━━━━━━━━━━━━",
        parse_mode="HTML",
    )