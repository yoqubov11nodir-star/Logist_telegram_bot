import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from sqlalchemy import select, update

from database.session import async_session
from database.models import User, UserRole, Order, OrderStatus, OrderMedia, OrderLocation
from bot.keyboards.dispatcher_kb import get_dispatcher_main_keyboard

dispatcher_router = Router()


class DispatcherStates(StatesGroup):
    waiting_for_vehicle_number   = State()
    waiting_for_rejection_reason = State()
    # ─── 8-BAND: Haydovchi ro'yxatdan o'tkazish ───
    waiting_for_driver_fullname  = State()
    waiting_for_driver_reg_photo = State()   # tex pasport rasmlari
    waiting_for_driver_lic_photo = State()   # prava rasmlari


# ─── /start ──────────────────────────────────────────────────────────────────
@dispatcher_router.message(Command("start"))
async def dispatcher_start(message: Message, user: User):
    if user.role == UserRole.DISPATCHER:
        await message.answer("🎧 Xush kelibsiz, Dispetcher!", reply_markup=get_dispatcher_main_keyboard())


# ─── YANGI BUYURTMALAR ───────────────────────────────────────────────────────
@dispatcher_router.message(F.text == "📥 Yangi buyurtmalar")
async def view_assigned_orders(message: Message, user: User):
    if user.role != UserRole.DISPATCHER:
        return
    async with async_session() as session:
        orders = (await session.execute(
            select(Order).where(Order.dispatcher_id == user.telegram_id, Order.status == OrderStatus.DISPATCHER_ASSIGNED)
        )).scalars().all()
    if not orders:
        await message.answer("📭 Sizga biriktirilgan yangi buyurtmalar yo'q.")
        return
    for order in orders:
        kb = InlineKeyboardBuilder()
        kb.button(text="🚛 Haydovchi biriktirish", callback_data=f"find_driver_{order.id}")
        price = f"{order.cost_price:,.0f}" if order.cost_price else "0"
        await message.answer(
            f"━━━━━━━━━━━━━━━━━━\n📦 <b>Yangi buyurtma #{order.id}</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"🔵 A nuqta: {order.point_a}\n🔴 B nuqta: {order.point_b}\n"
            f"📦 Yuk: {order.cargo_description}\n💸 Limit: {price} so'm\n━━━━━━━━━━━━━━━━━━",
            reply_markup=kb.as_markup(), parse_mode="HTML",
        )


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
        card = f" | {d.card_number}" if d.card_number else ""
        kb.button(text=f"👨‍✈️ {d.full_name}{card}", callback_data=f"ask_vnum_{order_id}_{d.id}")
    kb.button(text="➕ Yangi haydovchi qo'shish", callback_data=f"add_new_driver_{order_id}")
    kb.adjust(1)
    await callback.message.edit_text(
        f"👨‍✈️ <b>#{order_id} uchun haydovchi tanlang:</b>",
        reply_markup=kb.as_markup(), parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 8-BAND: YANGI HAYDOVCHI QO'SHISH
# ═══════════════════════════════════════════════════════════════════════════════
@dispatcher_router.callback_query(F.data.startswith("add_new_driver_"))
async def start_add_driver(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[3])
    await state.update_data(
        pending_order_id=order_id,
        driver_reg_photos=[],
        driver_lic_photos=[],
    )
    await state.set_state(DispatcherStates.waiting_for_driver_fullname)
    await callback.message.answer(
        "➕ <b>Yangi haydovchi qo'shish</b>\n\n"
        "1️⃣ Haydovchining <b>ism-familyasini</b> kiriting:\n\n"
        "<i>Misol: Karimov Jahongir Aliyevich</i>",
        parse_mode="HTML",
    )


@dispatcher_router.message(DispatcherStates.waiting_for_driver_fullname)
async def get_driver_fullname(message: Message, state: FSMContext):
    await state.update_data(driver_fullname=message.text.strip())
    await state.set_state(DispatcherStates.waiting_for_driver_reg_photo)
    await message.answer(
        "2️⃣ <b>Texnik pasport rasmlarini yuboring</b>\n\n"
        "📸 Minimal: 2 ta | Maksimal: 4 ta rasm\n\n"
        "<i>Har birini alohida yuboring. Hammasi tayyor bo'lgach quyidagi tugmani bosing.</i>",
        reply_markup=__import__('aiogram').types.InlineKeyboardMarkup(inline_keyboard=[[
            __import__('aiogram').types.InlineKeyboardButton(text="✅ Tex pasport tayyor", callback_data="driver_reg_done")
        ]]),
        parse_mode="HTML",
    )

@dispatcher_router.message(DispatcherStates.waiting_for_driver_reg_photo, F.photo)
async def collect_reg_photos(message: Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("driver_reg_photos", [])
    if len(photos) >= 4:
        await message.answer("⚠️ Maksimal 4 ta rasm yuborishingiz mumkin.")
        return
    photos.append(message.photo[-1].file_id)
    await state.update_data(driver_reg_photos=photos)
    remaining = 4 - len(photos)
    msg = f"Yana {remaining} ta yuborishingiz mumkin." if remaining > 0 else "To'ldi (4/4)!"
    await message.answer(f"✅ Qabul qilindi ({len(photos)}/4)\n{msg}\nTayyor bo'lsa tugmani bosing.")

@dispatcher_router.callback_query(F.data == "driver_reg_done")
async def reg_photos_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    photos = data.get("driver_reg_photos", [])
    if len(photos) < 2:
        await callback.answer("Kamida 2 ta tex pasport rasmi kerak!", show_alert=True)
        return
    await state.set_state(DispatcherStates.waiting_for_driver_lic_photo)
    await callback.message.answer(
        "3️⃣ <b>Haydovchilik guvohnomasi (Prava) rasmlarini yuboring</b>\n\n"
        "📸 Minimal: 2 ta | Maksimal: 4 ta rasm\n\n"
        "<i>Har birini alohida yuboring.</i>",
        reply_markup=__import__('aiogram').types.InlineKeyboardMarkup(inline_keyboard=[[
            __import__('aiogram').types.InlineKeyboardButton(text="✅ Prava tayyor", callback_data="driver_lic_done")
        ]]),
        parse_mode="HTML",
    )


@dispatcher_router.message(DispatcherStates.waiting_for_driver_lic_photo, F.photo)
async def collect_lic_photos(message: Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("driver_lic_photos", [])
    if len(photos) >= 4:
        await message.answer("⚠️ Maksimal 4 ta rasm yuborishingiz mumkin.")
        return
    photos.append(message.photo[-1].file_id)
    await state.update_data(driver_lic_photos=photos)
    remaining = 4 - len(photos)
    msg = f"Yana {remaining} ta yuborishingiz mumkin." if remaining > 0 else "To'ldi (4/4)!"
    await message.answer(f"✅ Qabul qilindi ({len(photos)}/4)\n{msg}\nTayyor bo'lsa tugmani bosing.")


@dispatcher_router.callback_query(F.data == "driver_lic_done")
async def lic_photos_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lic_photos = data.get("driver_lic_photos", [])
    if len(lic_photos) < 2:
        await callback.answer("Kamida 2 ta prava rasmi kerak!", show_alert=True)
        return

    fullname    = data.get("driver_fullname", "Noma'lum")
    reg_photos  = data.get("driver_reg_photos", [])
    pending_oid = data.get("pending_order_id")

    # Dispatcher o'ziga ko'rsatib tasdiqlash/rad etish tugmalari
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Qabul qilish", callback_data="confirm_new_driver")
    kb.button(text="❌ Rad etish",    callback_data="reject_new_driver")
    kb.adjust(2)

    # Rasmlarni dispatcherga ko'rsatish
    await callback.message.answer(
        f"📋 <b>Yangi haydovchi ma'lumotlari:</b>\n\n"
        f"👤 Ism-familya: <b>{fullname}</b>\n"
        f"📄 Tex pasport: {len(reg_photos)} ta rasm\n"
        f"🪪 Prava: {len(lic_photos)} ta rasm\n\n"
        f"Qabul qilasizmi?",
        reply_markup=kb.as_markup(), parse_mode="HTML",
    )
    # Rasmlarni yuborish
    for fid in reg_photos:
        try:
            await callback.bot.send_photo(chat_id=callback.from_user.id, photo=fid)
        except Exception: pass
    for fid in lic_photos:
        try:
            await callback.bot.send_photo(chat_id=callback.from_user.id, photo=fid)
        except Exception: pass


@dispatcher_router.callback_query(F.data == "confirm_new_driver")
async def confirm_new_driver(callback: CallbackQuery, state: FSMContext):
    data        = await state.get_data()
    fullname    = data.get("driver_fullname", "Noma'lum")
    reg_photos  = data.get("driver_reg_photos", [])
    lic_photos  = data.get("driver_lic_photos", [])
    pending_oid = data.get("pending_order_id")

    await callback.message.edit_text(
        f"✅ <b>{fullname}</b> bazaga qo'shildi!\n\n"
        f"Endi haydovchi /start bosib botga kirsin va telefon raqamini ulashsin.\n"
        f"So'ng unga DRIVER roli beriladi.",
        parse_mode="HTML",
    )
    # Foundерga xabar — yangi haydovchi hujjatlari
    from bot.keyboards.admin_kb import get_admin_approve_keyboard
    import os
    FOUNDER_ID = int(os.getenv("FOUNDER_ID", 0))
    try:
        note = (
            f"🚛 <b>Dispatcher yangi haydovchi qo'shdi!</b>\n\n"
            f"👤 Ism: <b>{fullname}</b>\n"
            f"📄 Tex pasport: {len(reg_photos)} ta rasm\n"
            f"🪪 Prava: {len(lic_photos)} ta rasm\n\n"
            f"Haydovchi botga kirganda unga rol bering."
        )
        await callback.bot.send_message(FOUNDER_ID, note, parse_mode="HTML")
        for fid in reg_photos + lic_photos:
            await callback.bot.send_photo(FOUNDER_ID, fid)
    except Exception: pass

    await state.clear()


@dispatcher_router.callback_query(F.data == "reject_new_driver")
async def reject_new_driver(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "❌ Rad etildi. Sabab yozing (haydovchiga xabar yuborilmaydi):"
    )
    await state.update_data(reject_stage="new_driver")
    await state.set_state(DispatcherStates.waiting_for_rejection_reason)


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
    v_number = message.text.upper().strip()
    data = await state.get_data()
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

    # Haydovchiga to'liq ma'lumot
    try:
        await message.bot.send_message(
            chat_id=driver.telegram_id,
            text=(
                f"🎉 <b>Sizga yangi buyurtma biriktirildi!</b>\n\n"
                f"━━━━━━━━━━━━━━━━━━\n📦 <b>Buyurtma #{order_id}</b>\n━━━━━━━━━━━━━━━━━━\n\n"
                f"🔵 <b>A NUQTA (YUKLASH):</b>\n   📍 {order.point_a}\n\n"
                f"🔴 <b>B NUQTA (TUSHIRISH):</b>\n   📍 {order.point_b}\n\n"
                f"📦 <b>YUK:</b> {order.cargo_description}\n"
                f"🚘 <b>Mashina:</b> {v_number}\n━━━━━━━━━━━━━━━━━━\n\n"
                f"📌 <b>Keyingi qadam:</b>\n"
                f"A nuqtaga boring → <b>🚚 Mening yuklarim</b> → <b>✅ A nuqtaga yetib keldim</b>"
            ),
            parse_mode="HTML",
        )
    except Exception: pass

    if client and client.telegram_id:
        try:
            await message.bot.send_message(
                chat_id=client.telegram_id,
                text=(f"🚛 <b>#{order_id} buyurtmangiz uchun haydovchi biriktirildi!</b>\n\n"
                      f"🚘 Mashina: {v_number}\n👨‍✈️ Haydovchi: {driver.full_name}"),
                parse_mode="HTML",
            )
        except Exception: pass
    await state.clear()


# ─── LOADING_A TASDIQLASH ─────────────────────────────────────────────────────
@dispatcher_router.callback_query(F.data.startswith("approve_loading_a_"))
async def approve_order_load(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[3])
    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        order.status = OrderStatus.LOADING
        driver = (await session.execute(select(User).where(User.telegram_id == order.driver_id))).scalar_one_or_none()
        await session.commit()
    await callback.message.edit_text(f"✅ <b>#{order_id}</b> — Yuk ortilishi tasdiqlandi.", parse_mode="HTML")
    if driver:
        try:
            await callback.bot.send_message(
                chat_id=driver.telegram_id,
                text=(f"✅ <b>Dispetcher yuk ortilganini tasdiqladi!</b>\n\nEndi yo'lga chiqishingiz mumkin.\n\n"
                      f"📌 <b>🚚 Mening yuklarim</b> → <b>🚀 Yo'lga chiqdim</b>"),
                parse_mode="HTML",
            )
        except Exception: pass


# ─── LOADING_A RAD ETISH ──────────────────────────────────────────────────────
@dispatcher_router.callback_query(F.data.startswith("reject_loading_a_"))
async def reject_order_load(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[3])
    await state.update_data(reject_order_id=order_id, reject_stage="loading_a")
    await state.set_state(DispatcherStates.waiting_for_rejection_reason)
    await callback.message.answer("❌ <b>Rad etish sababini yozing:</b>", parse_mode="HTML")


# ─── UNLOADING_B TASDIQLASH ───────────────────────────────────────────────────
@dispatcher_router.callback_query(F.data.startswith("approve_unloading_b_"))
async def approve_unloading_b(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[3])
    async with async_session() as session:
        order      = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        order.status = OrderStatus.UNLOADED
        driver     = (await session.execute(select(User).where(User.telegram_id == order.driver_id))).scalar_one_or_none()
        cashiers   = (await session.execute(select(User).where(User.role == UserRole.CASHIER))).scalars().all()
        logist     = (await session.execute(select(User).where(User.telegram_id == order.logist_id))).scalar_one_or_none()
        client     = (await session.execute(select(User).where(User.phone == order.client_phone))).scalar_one_or_none()
        await session.commit()

    await callback.message.edit_text(
        f"✅ <b>#{order_id}</b> — Yuk tushirilishi tasdiqlandi. Kassirga yuborildi.", parse_mode="HTML",
    )
    if driver and driver.telegram_id:
        try:
            await callback.bot.send_message(
                chat_id=driver.telegram_id,
                text=(f"✅ <b>Yuk muvaffaqiyatli tushirildi!</b>\n\nBuyurtma <b>#{order_id}</b>\n"
                      f"💳 Karta: <code>{driver.card_number or 'Kiritilmagan'}</code>\n\nTo'lov tez orada amalga oshiriladi."),
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
                    text=(f"🔔 <b>TO'LOV KERAK! #{order_id}</b>\n\n"
                          f"👨‍✈️ Haydovchi: {driver.full_name if driver else 'Noma\'lum'}\n"
                          f"💳 Karta: <code>{driver.card_number if driver and driver.card_number else 'Kiritilmagan'}</code>\n"
                          f"💰 Summa: <b>{order.cost_price:,.0f} so'm</b>"),
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
                f"🎉 <b>Yukingiz yetkazildi!</b>\n\nBuyurtma <b>#{order_id}</b> muvaffaqiyatli yakunlandi.",
                parse_mode="HTML")
        except Exception: pass


# ─── UNLOADING_B RAD ETISH ────────────────────────────────────────────────────
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
        order.status = OrderStatus.ARRIVED_A if stage == "loading_a" else OrderStatus.ON_WAY
        driver = (await session.execute(select(User).where(User.telegram_id == order.driver_id))).scalar_one_or_none()
        await session.commit()

    await message.answer("✅ Rad etildi. Haydovchiga xabar yuborildi.")
    if driver:
        stage_text = "yuk ortish" if stage == "loading_a" else "yuk tushirish"
        try:
            await message.bot.send_message(
                chat_id=driver.telegram_id,
                text=(f"❌ <b>Media rad etildi</b>\n\n📦 Buyurtma: #{order_id}\n📋 Bosqich: {stage_text}\n\n"
                      f"💬 <b>Sabab:</b> {reason}\n\nTo'g'ri va aniq media yuborib, qayta urinib ko'ring."),
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
    await callback.message.edit_text(f"✅ <b>#{order_id}</b> — Yo'lga chiqish tasdiqlandi.", parse_mode="HTML")
    if client and client.telegram_id:
        try:
            await callback.bot.send_message(client.telegram_id,
                f"🚛 <b>#{order_id} yukingiz yo'lda!</b>\n\nMarshrut: {order.point_a} → {order.point_b}",
                parse_mode="HTML")
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
        f"✅ <b>#{order_id}</b> — B nuqtaga kelgani tasdiqlandi. Logistga so'rov ketdi.", parse_mode="HTML",
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="📄 Shot-faktura yuborish", callback_data=f"send_invoice_{order_id}")
    try:
        await callback.bot.send_message(
            chat_id=logist.telegram_id,
            text=(f"⚡ <b>#{order_id} — Haydovchi B nuqtada!</b>\n\n"
                  f"Iltimos, Didox tizimidan shot-fakturani yuklab, botga yuboring.\n\n👇 Tugmani bosing:"),
            reply_markup=kb.as_markup(), parse_mode="HTML",
        )
    except Exception: pass

    if driver and driver.telegram_id:
        try:
            await callback.bot.send_message(driver.telegram_id,
                "⏳ <b>Tasdiqlandi!</b>\nLogist fakturani yuborishini kuting.", parse_mode="HTML")
        except Exception: pass


# ─── B NUQTAGA KELISHNI RAD ETISH ────────────────────────────────────────────
@dispatcher_router.callback_query(F.data.startswith("reject_b_arrival_"))
async def reject_b_arrival(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[3])
    await state.update_data(reject_order_id=order_id, reject_stage="b_arrival")
    await state.set_state(DispatcherStates.waiting_for_rejection_reason)
    await callback.message.answer("❌ Rad etish sababini yozing:")


# ─── LOKATSIYANI MIJOZGA YUBORISH ─────────────────────────────────────────────
@dispatcher_router.callback_query(F.data.startswith("send_loc_to_client_"))
async def approve_location_to_client(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[4])
    async with async_session() as session:
        order    = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        client   = (await session.execute(select(User).where(User.phone == order.client_phone))).scalar_one_or_none()
        last_loc = (await session.execute(
            select(OrderLocation).where(OrderLocation.order_id == order_id).order_by(OrderLocation.id.desc())
        )).scalars().first()

    if not client or not client.telegram_id:
        await callback.answer("Mijoz botdan ro'yxatdan o'tmagan!", show_alert=True)
        return
    try:
        if last_loc:
            await callback.bot.send_location(chat_id=client.telegram_id,
                latitude=last_loc.latitude, longitude=last_loc.longitude)
        await callback.bot.send_message(client.telegram_id,
            f"📍 <b>#{order_id} — Yukingizning joriy joylashuvi</b>", parse_mode="HTML")
        await callback.message.answer("✅ Joylashuv mijozga yuborildi.")
    except Exception as e:
        await callback.answer(f"Xato: {e}", show_alert=True)


# ─── STATISTIKA ──────────────────────────────────────────────────────────────
@dispatcher_router.message(F.text == "📊 Mening statistikam")
async def dispatcher_stats(message: Message, user: User):
    if user.role != UserRole.DISPATCHER:
        return
    async with async_session() as session:
        orders = (await session.execute(select(Order).where(Order.dispatcher_id == user.telegram_id))).scalars().all()
    total     = len(orders)
    completed = len([o for o in orders if o.status in (OrderStatus.PAID, OrderStatus.COMPLETED)])
    active    = total - completed
    await message.answer(
        f"📊 <b>Sizning statistikangiz:</b>\n\n📋 Jami: {total} ta\n⏳ Faol: {active} ta\n✅ Yakunlangan: {completed} ta",
        parse_mode="HTML",
    )