import asyncio
import logging

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardButton, InlineKeyboardMarkup,
)
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, update

from database.session import async_session
from database.models import User, UserRole, Order, OrderStatus, OrderMedia, OrderLocation
from bot.states.driver_states import DriverSteps
from bot.keyboards.driver_kb import get_driver_main_keyboard

driver_router = Router()

STATUS_UZ = {
    "NEW":                 "🆕 Yangi",
    "DISPATCHER_ASSIGNED": "📋 Dispetcherga biriktirildi",
    "DRIVER_ASSIGNED":     "🚛 Sizga biriktirildi — A nuqtaga boring",
    "ARRIVED_A":           "📍 A nuqtaga keldingiz — media yuboring",
    "LOADING":             "📦 Yuk ortildi — yo'lga chiqing",
    "ON_WAY":              "🚚 Yo'ldasiz",
    "ARRIVED_B":           "🏁 B nuqtada — dispetcher tasdiqlashini kuting",
    "DIDOX_TASDIQDA":      "✅ Ruxsat berildi — yuk tushiring",
    "UNLOADED":            "📤 Yuk tushirildi — to'lov kutilmoqda",
    "PAID":                "💰 To'lov amalga oshirildi",
    "COMPLETED":           "✅ Yakunlandi",
    "CANCELLED":           "❌ Bekor qilindi",
}


# ─── MENING YUKLARIM ─────────────────────────────────────────────────────────
@driver_router.message(F.text == "🚚 Mening yuklarim")
async def view_driver_orders(message: Message, user: User):
    async with async_session() as session:
        orders = (
            await session.execute(
                select(Order).where(
                    Order.driver_id == user.telegram_id,
                    Order.status.notin_([OrderStatus.PAID, OrderStatus.COMPLETED, OrderStatus.CANCELLED]),
                )
            )
        ).scalars().all()

    if not orders:
        await message.answer(
            "📭 Hozirda faol yukingiz yo'q.\n\n"
            "Yangi yuk biriktirilganda sizga xabar beriladi."
        )
        return

    for order in orders:
        status_name = STATUS_UZ.get(order.status.value, order.status.value)
        kb = InlineKeyboardBuilder()

        if order.status == OrderStatus.DRIVER_ASSIGNED:
            kb.button(text="✅ A nuqtaga yetib keldim", callback_data=f"st_arrived_a_{order.id}")
        elif order.status == OrderStatus.ARRIVED_A:
            kb.button(text="📸 Media yuborish (yuk ortildi)", callback_data=f"st_load_media_{order.id}")
        elif order.status == OrderStatus.LOADING:
            kb.button(text="🚀 Yo'lga chiqdim", callback_data=f"st_on_way_{order.id}")
        elif order.status == OrderStatus.ON_WAY:
            kb.button(text="🏁 B nuqtaga yetib keldim", callback_data=f"st_arrived_b_{order.id}")
        elif order.status == OrderStatus.DIDOX_TASDIQDA:
            kb.button(text="📤 Yuk tushirdim (Media yuborish)", callback_data=f"st_unload_media_{order.id}")
        kb.adjust(1)

        await message.answer(
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Buyurtma #{order.id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"🔵 <b>A NUQTA (YUKLASH):</b>\n"
            f"   📍 {order.point_a}\n\n"
            f"🔴 <b>B NUQTA (TUSHIRISH):</b>\n"
            f"   📍 {order.point_b}\n\n"
            f"📦 <b>Yuk:</b> {order.cargo_description}\n"
            f"🚘 <b>Mashina:</b> {order.vehicle_number or '—'}\n"
            f"📊 <b>Holat:</b> {status_name}\n"
            f"━━━━━━━━━━━━━━━━━━",
            reply_markup=kb.as_markup() if kb.export() else None,
            parse_mode="HTML",
        )


# ─── A NUQTAGA KELDI ─────────────────────────────────────────────────────────
@driver_router.callback_query(F.data.startswith("st_arrived_a_"))
async def status_arrived_a(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[3])
    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        order.status = OrderStatus.ARRIVED_A
        await session.commit()

    kb = InlineKeyboardBuilder()
    kb.button(text="📸 Media yuborish", callback_data=f"st_load_media_{order_id}")

    await callback.message.edit_text(
        f"✅ <b>A nuqtaga yetib kelganingiz qayd etildi!</b>\n\n"
        f"Endi yuk ortib, quyidagi media yuborishingiz kerak:\n\n"
        f"📹 <b>1 ta video</b> — yuk ortilayotgani\n"
        f"🖼 <b>1 ta rasm</b> — mashinaning OLD tomoni (nomer ko'ringan)\n"
        f"🖼 <b>1 ta rasm</b> — mashinaning ORQA tomoni (nomer + yuk)\n\n"
        f"Tayyor bo'lgach tugmani bosing 👇",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


# ─── YUK ORTISH MEDIA BOSHLASH ────────────────────────────────────────────────
@driver_router.callback_query(F.data.startswith("st_load_media_"))
async def start_load_media(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[3])
    await state.update_data(
        current_order_id=order_id,
        media_paths=[],
        stage="loading_a",
        media_count={"photo": 0, "video": 0},
    )
    await state.set_state(DriverSteps.waiting_for_media)
    await callback.message.answer(
        f"📸 <b>Yuk ortilishi haqida media yuboring</b>\n\n"
        f"<b>Kerakli fayllar:</b>\n"
        f"📹 1 ta video — yuk ortilayotgani\n"
        f"🖼 1 ta rasm — OLD tomon (nomer ko'ringan)\n"
        f"🖼 1 ta rasm — ORQA tomon (nomer + yuk)\n\n"
        f"<i>Har birini alohida yuboring. Jami 3 ta fayl kerak.</i>",
        parse_mode="HTML",
    )


# ─── YUK ORTISH / TUSHIRISH MEDIA QABUL QILISH ────────────────────────────────
@driver_router.message(DriverSteps.waiting_for_media, F.photo | F.video)
async def handle_media_upload(message: Message, state: FSMContext):
    data        = await state.get_data()
    order_id    = data["current_order_id"]
    stage       = data["stage"]
    media_paths = data.get("media_paths", [])
    media_count = data.get("media_count", {"photo": 0, "video": 0})

    is_video = bool(message.video)
    file_id  = message.video.file_id if is_video else message.photo[-1].file_id
    m_type   = "video" if is_video else "photo"

    media_count[m_type] = media_count.get(m_type, 0) + 1
    media_paths.append({"id": file_id, "type": m_type})
    await state.update_data(media_paths=media_paths, media_count=media_count)

    # Minimal talablar
    min_photos = 2
    min_videos = 1
    p_ok = media_count.get("photo", 0) >= min_photos
    v_ok = media_count.get("video", 0) >= min_videos

    if not (p_ok and v_ok):
        remaining = []
        if not v_ok:
            remaining.append(f"📹 {min_videos - media_count.get('video', 0)} ta video")
        if not p_ok:
            remaining.append(f"🖼 {min_photos - media_count.get('photo', 0)} ta rasm")
        await message.answer(
            f"✅ Qabul qilindi! ({len(media_paths)} ta fayl)\n\n"
            f"📋 Hali kerak:\n" + "\n".join(remaining)
        )
        return

    # Yetarli — saqlash
    async with async_session() as session:
        for m in media_paths:
            session.add(OrderMedia(
                order_id=order_id,
                file_type=m["type"],
                file_id=m["id"],
                stage=stage,
            ))
        order      = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        disp_tg_id = order.dispatcher_id
        await session.commit()

    await message.answer(
        f"✅ <b>Barcha media qabul qilindi ({len(media_paths)} ta fayl)!</b>\n\n"
        f"⏳ Dispetcher tasdiqlashini kuting...",
        parse_mode="HTML",
    )

    if disp_tg_id:
        prefix    = "loading_a" if stage == "loading_a" else "unloading_b"
        stage_txt = "YUK ORTILDI" if stage == "loading_a" else "YUK TUSHIRILDI"
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Tasdiqlash", callback_data=f"approve_{prefix}_{order_id}")
        kb.button(text="❌ Rad etish",  callback_data=f"reject_{prefix}_{order_id}")
        kb.adjust(2)
        try:
            for m in [x for x in media_paths if x["type"] == "photo"]:
                await message.bot.send_photo(chat_id=disp_tg_id, photo=m["id"])
            for m in [x for x in media_paths if x["type"] == "video"]:
                await message.bot.send_video(chat_id=disp_tg_id, video=m["id"])
            await message.bot.send_message(
                chat_id=disp_tg_id,
                text=(
                    f"🔔 <b>#{order_id} — {stage_txt}</b>\n\n"
                    f"👨‍✈️ Haydovchi media yubordi:\n"
                    f"📹 Video: {media_count.get('video', 0)} ta\n"
                    f"🖼 Rasm: {media_count.get('photo', 0)} ta\n\n"
                    f"Tasdiqlaysizmi?"
                ),
                reply_markup=kb.as_markup(),
                parse_mode="HTML",
            )
        except Exception as e:
            logging.error(f"Dispetcherga media yuborishda xato: {e}")
    await state.clear()


# ─── YO'LGA CHIQISH ───────────────────────────────────────────────────────────
@driver_router.callback_query(F.data.startswith("st_on_way_"))
async def start_on_way(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[3])
    await state.update_data(current_order_id=order_id)
    await state.set_state(DriverSteps.waiting_for_location)
    await callback.message.answer(
        f"📍 <b>Joriy lokatsiyangizni yuboring</b>\n\n"
        f"📌 Qanday yuborish:\n"
        f"1️⃣ 📎 (qog'oz) ikonkasiga bosing\n"
        f"2️⃣ <b>Location</b> ni tanlang\n"
        f"3️⃣ <b>Send My Current Location</b> ni bosing",
        parse_mode="HTML",
    )


@driver_router.message(DriverSteps.waiting_for_location, F.location)
async def handle_location(message: Message, state: FSMContext):
    data     = await state.get_data()
    order_id = data["current_order_id"]

    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        order.status = OrderStatus.ON_WAY
        session.add(OrderLocation(
            order_id=order_id,
            latitude=message.location.latitude,
            longitude=message.location.longitude,
        ))
        disp_tg_id = order.dispatcher_id
        await session.commit()

    # Taymerni to'xtatish (agar mijoz so'ragan bo'lsa)
    from bot.handler.logist import active_location_requests
    if order_id in active_location_requests:
        active_location_requests[order_id].set()

    await message.answer(
        f"🚀 <b>Oq yo'l!</b>\n\n"
        f"📊 Holat: Yo'lda\n"
        f"🗺 {order.point_a} → {order.point_b}\n\n"
        f"B nuqtaga yetgach botdan xabar bering.",
        reply_markup=get_driver_main_keyboard(),
        parse_mode="HTML",
    )
    await state.clear()

    # Dispetcherga tasdiqlash
    if disp_tg_id:
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Tasdiqlash", callback_data=f"disp_confirm_onway_{order_id}")
        try:
            await message.bot.send_location(
                chat_id=disp_tg_id,
                latitude=message.location.latitude,
                longitude=message.location.longitude,
            )
            await message.bot.send_message(
                chat_id=disp_tg_id,
                text=f"🚀 <b>#{order_id} — Haydovchi yo'lga chiqdi!</b>\nTasdiqlaysizmi?",
                reply_markup=kb.as_markup(),
                parse_mode="HTML",
            )
        except Exception:
            pass


# ─── B NUQTAGA KELDI ─────────────────────────────────────────────────────────
@driver_router.callback_query(F.data.startswith("st_arrived_b_"))
async def status_arrived_b(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[3])
    await state.update_data(current_order_id=order_id, media_paths=[], media_count={"photo": 0, "video": 0})
    await state.set_state(DriverSteps.waiting_for_b_media)
    await callback.message.edit_text(
        f"🏁 <b>Buyurtma #{order_id} — B nuqta</b>\n\n"
        f"B nuqtaga yetganingizni tasdiqlash uchun media yuboring:\n\n"
        f"📹 1–3 ta video\n"
        f"🖼 2–4 ta rasm\n\n"
        f"Yuborib bo'lgach <b>✅ Yuborish</b> tugmasini bosing.",
        parse_mode="HTML",
    )


@driver_router.message(DriverSteps.waiting_for_b_media, F.photo | F.video)
async def handle_b_media(message: Message, state: FSMContext):
    data        = await state.get_data()
    media_paths = data.get("media_paths", [])
    media_count = data.get("media_count", {"photo": 0, "video": 0})
    order_id    = data["current_order_id"]

    is_video = bool(message.video)
    file_id  = message.video.file_id if is_video else message.photo[-1].file_id
    m_type   = "video" if is_video else "photo"
    media_count[m_type] = media_count.get(m_type, 0) + 1
    media_paths.append({"id": file_id, "type": m_type})
    await state.update_data(media_paths=media_paths, media_count=media_count)

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Hammasini Yuborish", callback_data=f"b_media_done_{order_id}")
    ]])
    await message.answer(
        f"✅ {len(media_paths)} ta fayl qabul qilindi\n"
        f"📹 Video: {media_count.get('video', 0)} ta | 🖼 Rasm: {media_count.get('photo', 0)} ta\n\n"
        f"Yana qo'shishingiz yoki yuborishingiz mumkin:",
        reply_markup=kb,
    )


@driver_router.callback_query(F.data.startswith("b_media_done_"))
async def finalize_b_media(callback: CallbackQuery, state: FSMContext):
    data        = await state.get_data()
    order_id    = int(callback.data.split("_")[3])
    media_paths = data.get("media_paths", [])

    if not media_paths:
        await callback.answer("Hech qanday media yuborilmadi!", show_alert=True)
        return

    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        order.status = OrderStatus.ARRIVED_B
        for m in media_paths:
            session.add(OrderMedia(order_id=order_id, file_type=m["type"], file_id=m["id"], stage="arrived_b"))
        disp_tg_id = order.dispatcher_id
        await session.commit()

    await callback.message.edit_text(
        f"✅ <b>Media yuborildi!</b>\n\nDispetcher tasdiqlashini kuting.",
        parse_mode="HTML",
    )
    await state.clear()

    if disp_tg_id:
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ B nuqtani tasdiqlash", callback_data=f"st_arrived_b_confirm_{order_id}")
        kb.button(text="❌ Rad etish",            callback_data=f"reject_b_arrival_{order_id}")
        kb.adjust(1)
        try:
            for m in [x for x in media_paths if x["type"] == "photo"]:
                await callback.bot.send_photo(chat_id=disp_tg_id, photo=m["id"])
            for m in [x for x in media_paths if x["type"] == "video"]:
                await callback.bot.send_video(chat_id=disp_tg_id, video=m["id"])
            await callback.bot.send_message(
                chat_id=disp_tg_id,
                text=(
                    f"🏁 <b>#{order_id} — Haydovchi B nuqtaga yetdi!</b>\n\n"
                    f"👤 {callback.from_user.full_name}\n"
                    f"📸 Media: {len(media_paths)} ta\n\n"
                    f"Tasdiqlaysizmi?"
                ),
                reply_markup=kb.as_markup(),
                parse_mode="HTML",
            )
        except Exception as e:
            logging.error(f"B media dispetcherga: {e}")


# ─── YUK TUSHIRISH MEDIA BOSHLASH ─────────────────────────────────────────────
@driver_router.callback_query(F.data.startswith("st_unload_media_"))
async def start_unload_media(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[3])
    await state.update_data(
        current_order_id=order_id,
        media_paths=[],
        stage="unloading_b",
        media_count={"photo": 0, "video": 0},
    )
    await state.set_state(DriverSteps.waiting_for_media)
    await callback.message.answer(
        f"📤 <b>Yuk tushirilishi haqida media yuboring</b>\n\n"
        f"<b>Kerakli fayllar:</b>\n"
        f"📹 1 ta video — tushirilayotgan jarayon\n"
        f"🖼 2 ta rasm — mashina OLD va ORQA tomoni\n\n"
        f"<i>Jami 3 ta fayl kerak.</i>",
        parse_mode="HTML",
    )


# ─── MIJOZ SO'ROVIGA LOKATSIYA YUBORISH ──────────────────────────────────────
@driver_router.callback_query(F.data.startswith("act_on_way_"))
async def driver_send_current_loc(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[3])
    await state.update_data(current_order_id=order_id)
    await state.set_state(DriverSteps.waiting_for_location)
    await callback.message.answer(
        f"📍 <b>Lokatsiyangizni yuboring</b>\n\n"
        f"Mijoz sizning qayerdaligingizni so'ramoqda.\n\n"
        f"📌 Qanday yuborish:\n"
        f"1️⃣ 📎 ikonkasiga bosing\n"
        f"2️⃣ <b>Location</b> → <b>Send My Current Location</b>",
        parse_mode="HTML",
    )


# ─── KARTA VA MA'LUMOTLAR ─────────────────────────────────────────────────────
@driver_router.message(F.text == "💳 Karta va ma'lumotlarim")
async def show_card_info(message: Message, user: User):
    card = user.card_number or "Kiritilmagan"
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Ma'lumotlarni yangilash", callback_data="update_driver_info")
    await message.answer(
        f"👤 <b>Sizning ma'lumotlaringiz:</b>\n\n"
        f"📛 Ism-familya: <b>{user.full_name}</b>\n"
        f"💳 Karta raqami: <code>{card}</code>\n\n"
        f"Ma'lumotlarni yangilash uchun bosing:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@driver_router.callback_query(F.data == "update_driver_info")
async def request_driver_info_update(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DriverSteps.waiting_for_full_name)
    await callback.message.answer(
        "📝 <b>Ism-familyangizni kiriting:</b>\n\n<i>Misol: Karimov Jahongir</i>",
        parse_mode="HTML",
    )


@driver_router.message(DriverSteps.waiting_for_full_name)
async def save_full_name(message: Message, state: FSMContext):
    await state.update_data(new_full_name=message.text.strip())
    await state.set_state(DriverSteps.waiting_for_card)
    await message.answer(
        "💳 <b>Karta raqamingizni kiriting:</b>\n\n<i>Misol: 8600 1234 5678 9012</i>",
        parse_mode="HTML",
    )


@driver_router.message(DriverSteps.waiting_for_card)
async def save_card(message: Message, state: FSMContext, user: User):
    data     = await state.get_data()
    new_name = data.get("new_full_name", user.full_name)
    card     = message.text.strip()

    async with async_session() as session:
        await session.execute(
            update(User)
            .where(User.telegram_id == user.telegram_id)
            .values(card_number=card, full_name=new_name)
        )
        await session.commit()

    await message.answer(
        f"✅ <b>Ma'lumotlar saqlandi!</b>\n\n"
        f"📛 Ism-familya: {new_name}\n"
        f"💳 Karta: <code>{card}</code>",
        reply_markup=get_driver_main_keyboard(),
        parse_mode="HTML",
    )
    await state.clear()
