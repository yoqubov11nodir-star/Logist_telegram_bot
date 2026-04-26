import asyncio
import logging

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardButton, InlineKeyboardMarkup,
    InputMediaPhoto, InputMediaVideo,
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

MEDIA_INSTRUCTION = (
    "📸 <b>Media yuborish tartibi:</b>\n\n"
    "🚗 <b>Mashinaning oldi tomoni</b> — rasm (mashina raqami ko'rinsin!)\n"
    "🚗 <b>Mashinaning orqa tomoni</b> — rasm (mashina raqami ko'rinsin!)\n"
    "📹 <b>Yuk va jarayon</b> — video\n\n"
    "⚠️ <b>Mashina davlat raqami barcha rasmlarda aniq ko'rinib turishi shart!</b>\n\n"
    "<i>Minimum: 2 ta rasm + 1 ta video</i>"
)


async def _send_media_group_safe(bot, chat_id: int, media_paths: list):
    """Media fayllarni guruhlashtirib yuboradi."""
    if not media_paths:
        return
    items = []
    for m in media_paths:
        if m["type"] == "photo":
            items.append(InputMediaPhoto(media=m["id"]))
        else:
            items.append(InputMediaVideo(media=m["id"]))

    try:
        if len(items) >= 2:
            await bot.send_media_group(chat_id=chat_id, media=items)
        else:
            m = media_paths[0]
            if m["type"] == "photo":
                await bot.send_photo(chat_id=chat_id, photo=m["id"])
            else:
                await bot.send_video(chat_id=chat_id, video=m["id"])
    except Exception as e:
        logging.error(f"Media group yuborishda xato: {e}")


# ─── MENING YUKLARIM ─────────────────────────────────────────────────────────
@driver_router.message(F.text == "🚚 Mening yuklarim")
async def view_driver_orders(message: Message, user: User):
    if user.role != UserRole.DRIVER:
        return
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
            "📭 <b>Hozirda faol yukingiz yo'q.</b>\n\n"
            "Yangi yuk biriktirilganda sizga xabar beriladi. 🔔",
            parse_mode="HTML",
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

        a_lat = getattr(order, 'point_a_lat', None)
        a_lon = getattr(order, 'point_a_lon', None)
        b_lat = getattr(order, 'point_b_lat', None)
        b_lon = getattr(order, 'point_b_lon', None)

        a_loc_line = f"\n   🗺 <a href='https://maps.google.com/?q={a_lat},{a_lon}'>Xaritada ochish</a>" if a_lat and a_lon else ""
        b_loc_line = f"\n   🗺 <a href='https://maps.google.com/?q={b_lat},{b_lon}'>Xaritada ochish</a>" if b_lat and b_lon else ""

        await message.answer(
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Buyurtma #{order.id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"🔵 <b>A NUQTA — YUKLASH JOYI:</b>\n"
            f"   📍 {order.point_a}{a_loc_line}\n\n"
            f"🔴 <b>B NUQTA — TUSHIRISH JOYI:</b>\n"
            f"   📍 {order.point_b}{b_loc_line}\n\n"
            f"📦 <b>Yuk tavsifi:</b> {order.cargo_description}\n"
            f"🚘 <b>Mashina:</b> {order.vehicle_number or '—'}\n\n"
            f"📊 <b>Holat:</b> {status_name}\n"
            f"━━━━━━━━━━━━━━━━━━",
            reply_markup=kb.as_markup() if kb.export() else None,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


# ─── A NUQTAGA KELDI ─────────────────────────────────────────────────────────
@driver_router.callback_query(F.data.startswith("st_arrived_a_"))
async def status_arrived_a(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[3])
    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
        if not order:
            await callback.answer("Buyurtma topilmadi!", show_alert=True)
            return
        disp_tg_id = order.dispatcher_id
        point_a    = order.point_a
        cargo      = order.cargo_description
        v_num      = order.vehicle_number or "—"
        driver     = (await session.execute(select(User).where(User.telegram_id == order.driver_id))).scalar_one_or_none()
        order.status = OrderStatus.ARRIVED_A
        await session.commit()

    kb = InlineKeyboardBuilder()
    kb.button(text="📸 Media yuborish (yuk ortildi)", callback_data=f"st_load_media_{order_id}")

    await callback.message.edit_text(
        f"✅ <b>A nuqtaga yetib kelganingiz qayd etildi!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📸 <b>Endi quyidagi medialarni yuboring:</b>\n\n"
        f"{MEDIA_INSTRUCTION}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"Tayyor bo'lgach <b>📸 Media yuborish</b> tugmasini bosing 👇",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )

    if disp_tg_id:
        drv_name  = driver.full_name if driver else "—"
        drv_phone = driver.phone if driver and driver.phone else "—"
        try:
            await callback.bot.send_message(
                chat_id=disp_tg_id,
                text=(
                    f"📍 <b>#{order_id} — Haydovchi A nuqtaga yetdi!</b>\n\n"
                    f"👤 Haydovchi: {drv_name}\n"
                    f"📱 Tel: {drv_phone}\n"
                    f"🚘 Mashina: {v_num}\n"
                    f"📦 Yuk: {cargo}\n"
                    f"🔵 {point_a}\n\n"
                    f"Yuk ortilganini kutmoqda."
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass


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
        f"📸 <b>Yuk ortilishi — media yuborish</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{MEDIA_INSTRUCTION}\n"
        f"━━━━━━━━━━━━━━━━━━",
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

    if m_type == "video" and media_count.get("video", 0) >= 4:
        await message.answer("⚠️ Ko'pi bilan 4 ta video yuborishingiz mumkin!")
        return
    if m_type == "photo" and media_count.get("photo", 0) >= 4:
        await message.answer("⚠️ Ko'pi bilan 4 ta rasm yuborishingiz mumkin!")
        return

    media_count[m_type] = media_count.get(m_type, 0) + 1
    media_paths.append({"id": file_id, "type": m_type})
    await state.update_data(media_paths=media_paths, media_count=media_count)

    min_photos = 2
    min_videos = 1
    p_ok  = media_count.get("photo", 0) >= min_photos
    v_ok  = media_count.get("video", 0) >= min_videos
    total = len(media_paths)
    p_cnt = media_count.get("photo", 0)
    v_cnt = media_count.get("video", 0)

    if not (p_ok and v_ok):
        remaining = []
        if not v_ok:
            remaining.append(f"📹 yana {min_videos - v_cnt} ta video")
        if not p_ok:
            remaining.append(f"🖼 yana {min_photos - p_cnt} ta rasm")
        await message.answer(
            f"✅ Qabul qilindi! (Jami: {total} ta)\n"
            f"📹 Video: {v_cnt} ta | 🖼 Rasm: {p_cnt} ta\n\n"
            f"📋 <b>Hali kerak:</b>\n" + "\n".join(remaining),
            parse_mode="HTML",
        )
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"✅ Hammasini Yuborish ({total} ta)", callback_data=f"media_done_{stage}_{order_id}")
    ]])
    await message.answer(
        f"✅ Minimum talablar bajarildi!\n"
        f"📹 Video: {v_cnt} ta | 🖼 Rasm: {p_cnt} ta\n\n"
        f"Yana qo'shishingiz yoki tasdiqlashingiz mumkin 👇",
        reply_markup=kb,
    )


# ─── MEDIA TASDIQLASH ─────────────────────────────────────────────────────────
@driver_router.callback_query(F.data.startswith("media_done_"))
async def finalize_media(callback: CallbackQuery, state: FSMContext):
    parts    = callback.data.split("_")
    order_id = int(parts[-1])
    stage    = "_".join(parts[2:-1])

    data        = await state.get_data()
    media_paths = data.get("media_paths", [])
    media_count = data.get("media_count", {"photo": 0, "video": 0})

    if not media_paths:
        await callback.answer("Hech qanday media yuborilmadi!", show_alert=True)
        return

    async with async_session() as session:
        for m in media_paths:
            session.add(OrderMedia(
                order_id=order_id,
                file_type=m["type"],
                file_id=m["id"],
                stage=stage,
            ))
        order      = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
        if not order:
            await callback.answer("Buyurtma topilmadi!", show_alert=True)
            return
        disp_tg_id = order.dispatcher_id
        cargo      = order.cargo_description
        point_a    = order.point_a
        point_b    = order.point_b
        v_num      = order.vehicle_number or "—"
        drv_obj    = (await session.execute(select(User).where(User.telegram_id == order.driver_id))).scalar_one_or_none()
        cashiers   = []
        if stage == "unloading_b":
            cashiers = (await session.execute(
                select(User).where(User.role == UserRole.CASHIER)
            )).scalars().all()
        await session.commit()

    await callback.message.edit_text(
        f"✅ <b>Barcha media yuborildi ({len(media_paths)} ta fayl)!</b>\n\n"
        f"⏳ Dispetcher tasdiqlashini kuting...",
        parse_mode="HTML",
    )
    await state.clear()

    stage_txt  = "YUK ORTILDI ✅" if stage == "loading_a" else "YUK TUSHIRILDI ✅"
    v_cnt      = media_count.get("video", 0)
    p_cnt      = media_count.get("photo", 0)
    drv_name   = drv_obj.full_name if drv_obj else "—"
    drv_phone  = drv_obj.phone if drv_obj and drv_obj.phone else "—"

    if disp_tg_id:
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Tasdiqlash", callback_data=f"approve_{stage}_{order_id}")
        kb.button(text="❌ Rad etish",  callback_data=f"reject_{stage}_{order_id}")
        kb.adjust(2)
        try:
            await _send_media_group_safe(callback.bot, disp_tg_id, media_paths)
            await callback.bot.send_message(
                chat_id=disp_tg_id,
                text=(
                    f"🔔 <b>#{order_id} — {stage_txt}</b>\n\n"
                    f"👤 Haydovchi: {drv_name}\n"
                    f"📱 Tel: {drv_phone}\n"
                    f"🚘 Mashina: {v_num}\n"
                    f"📦 Yuk: {cargo}\n"
                    f"🔵 {point_a} → 🔴 {point_b}\n\n"
                    f"📹 Video: {v_cnt} ta | 🖼 Rasm: {p_cnt} ta\n\n"
                    f"Tasdiqlaysizmi?"
                ),
                reply_markup=kb.as_markup(),
                parse_mode="HTML",
            )
        except Exception as e:
            logging.error(f"Dispetcherga media: {e}")

    # Yuk tushirishda kassirga ham xabar + media
    if stage == "unloading_b":
        for cashier in cashiers:
            if cashier.telegram_id:
                try:
                    await _send_media_group_safe(callback.bot, cashier.telegram_id, media_paths)
                    await callback.bot.send_message(
                        chat_id=cashier.telegram_id,
                        text=(
                            f"📦 <b>#{order_id} — Haydovchi yuk tushirayotir!</b>\n\n"
                            f"👤 Haydovchi: {drv_name}\n"
                            f"📱 Tel: {drv_phone}\n"
                            f"🚘 Mashina: {v_num}\n"
                            f"📦 Yuk: {cargo}\n"
                            f"🔵 {point_a} → 🔴 {point_b}\n\n"
                            f"📹 Video: {v_cnt} ta | 🖼 Rasm: {p_cnt} ta\n\n"
                            f"⏳ Dispetcher tasdiqlashini kuting."
                        ),
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logging.error(f"Kassirga media: {e}")


# ─── YO'LGA CHIQISH ───────────────────────────────────────────────────────────
@driver_router.callback_query(F.data.startswith("st_on_way_"))
async def start_on_way(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[3])
    await state.update_data(current_order_id=order_id)
    await state.set_state(DriverSteps.waiting_for_location)
    await callback.message.answer(
        f"🚀 <b>Yo'lga chiqyapsiz!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📍 <b>Hozirgi joylashuvingizni yuboring:</b>\n\n"
        f"1️⃣ 📎 ikonkasiga bosing\n"
        f"2️⃣ <b>Location</b> ni tanlang\n"
        f"3️⃣ <b>Send My Current Location</b> ni bosing\n"
        f"━━━━━━━━━━━━━━━━━━",
        parse_mode="HTML",
    )


@driver_router.message(DriverSteps.waiting_for_location, F.location)
async def handle_location(message: Message, state: FSMContext, user: User):
    data     = await state.get_data()
    order_id = data["current_order_id"]

    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
        if not order:
            await message.answer("❌ Buyurtma topilmadi.")
            await state.clear()
            return
        prev_status = order.status

        session.add(OrderLocation(
            order_id=order_id,
            latitude=message.location.latitude,
            longitude=message.location.longitude,
        ))

        # Faqat LOADING → ON_WAY ga o'tkazamiz
        if prev_status == OrderStatus.LOADING:
            order.status = OrderStatus.ON_WAY

        disp_tg_id = order.dispatcher_id
        point_a    = order.point_a
        point_b    = order.point_b
        cargo      = order.cargo_description
        v_num      = order.vehicle_number or "—"
        await session.commit()

    from bot.handler.logist import active_location_requests
    if order_id in active_location_requests:
        active_location_requests[order_id].set()

    driver_name = user.full_name if user else "Haydovchi"

    if prev_status == OrderStatus.LOADING:
        # "Yo'lga chiqdim" oqimi
        await message.answer(
            f"🚀 <b>Oq yo'l! Yo'lga chiqdingiz!</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📦 Buyurtma: <b>#{order_id}</b>\n"
            f"🔵 {point_a} → 🔴 {point_b}\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"B nuqtaga yetgach botdan xabar bering.",
            reply_markup=get_driver_main_keyboard(),
            parse_mode="HTML",
        )
        await state.clear()

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
                    text=(
                        f"🚀 <b>#{order_id} — Haydovchi yo'lga chiqdi!</b>\n\n"
                        f"👤 Haydovchi: {driver_name}\n"
                        f"📱 Tel: {user.phone if user and user.phone else '—'}\n"
                        f"🚘 Mashina: {v_num}\n"
                        f"📦 Yuk: {cargo}\n"
                        f"🔵 {point_a} → 🔴 {point_b}\n\n"
                        f"Tasdiqlaysizmi?"
                    ),
                    reply_markup=kb.as_markup(),
                    parse_mode="HTML",
                )
            except Exception:
                pass

    else:
        # Mijoz so'roviga javob — lokatsiya dispetcherga + "Clientga yuborish" tugmasi
        await message.answer(
            f"✅ <b>Lokatsiyangiz yuborildi!</b>\n\n"
            f"Dispetcher mijozga yetkazadi.",
            parse_mode="HTML",
        )
        await state.clear()

        if disp_tg_id:
            kb = InlineKeyboardBuilder()
            kb.button(text="📍 Clientga yuborish", callback_data=f"send_loc_to_client_{order_id}")
            try:
                await message.bot.send_location(
                    chat_id=disp_tg_id,
                    latitude=message.location.latitude,
                    longitude=message.location.longitude,
                )
                await message.bot.send_message(
                    chat_id=disp_tg_id,
                    text=(
                        f"📍 <b>#{order_id} — Haydovchi lokatsiyasi</b>\n\n"
                        f"👤 Haydovchi: {driver_name}\n"
                        f"📱 Tel: {user.phone if user and user.phone else '—'}\n"
                        f"🚘 Mashina: {v_num}\n"
                        f"📦 Yuk: {cargo}\n"
                        f"🔵 {point_a} → 🔴 {point_b}\n\n"
                        f"Mijozga yuborasizmi?"
                    ),
                    reply_markup=kb.as_markup(),
                    parse_mode="HTML",
                )
            except Exception:
                pass


# ─── HAYDOVCHI YO'LDA LOKATSIYA YUBORSA — DISPETCHERGA ────────────────────────
@driver_router.message(F.location)
async def driver_location_update(message: Message, user: User, state: FSMContext):
    if user.role != UserRole.DRIVER:
        return
    current_state = await state.get_state()
    if current_state:
        return

    async with async_session() as session:
        orders = (
            await session.execute(
                select(Order).where(
                    Order.driver_id == user.telegram_id,
                    Order.status == OrderStatus.ON_WAY,
                )
            )
        ).scalars().all()

    if not orders:
        return

    async with async_session() as s2:
        for order in orders:
            s2.add(OrderLocation(
                order_id=order.id,
                latitude=message.location.latitude,
                longitude=message.location.longitude,
            ))
        await s2.commit()

    for order in orders:
        if order.dispatcher_id:
            try:
                await message.bot.send_location(
                    chat_id=order.dispatcher_id,
                    latitude=message.location.latitude,
                    longitude=message.location.longitude,
                )
                await message.bot.send_message(
                    chat_id=order.dispatcher_id,
                    text=(
                        f"📍 <b>Haydovchi lokatsiyasi — #{order.id}</b>\n"
                        f"👨‍✈️ {user.full_name} | 📱{user.phone or '—'}\n"
                        f"🚘 {order.vehicle_number or '—'}\n"
                        f"🔵 {order.point_a} → 🔴 {order.point_b}"
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass

    await message.answer("✅ Lokatsiyangiz dispetcherga yuborildi.")


# ─── B NUQTAGA KELDI ─────────────────────────────────────────────────────────
@driver_router.callback_query(F.data.startswith("st_arrived_b_"))
async def status_arrived_b(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[3])
    await state.update_data(
        current_order_id=order_id,
        media_paths=[],
        media_count={"photo": 0, "video": 0},
    )
    await state.set_state(DriverSteps.waiting_for_b_media)
    await callback.message.edit_text(
        f"🏁 <b>Buyurtma #{order_id} — B nuqtaga yetdingiz!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{MEDIA_INSTRUCTION}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
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

    if m_type == "video" and media_count.get("video", 0) >= 3:
        await message.answer("⚠️ Ko'pi bilan 3 ta video yuborishingiz mumkin!")
        return
    if m_type == "photo" and media_count.get("photo", 0) >= 4:
        await message.answer("⚠️ Ko'pi bilan 4 ta rasm yuborishingiz mumkin!")
        return

    media_count[m_type] = media_count.get(m_type, 0) + 1
    media_paths.append({"id": file_id, "type": m_type})
    await state.update_data(media_paths=media_paths, media_count=media_count)

    min_photos = 2
    min_videos = 1
    p_ok  = media_count.get("photo", 0) >= min_photos
    v_ok  = media_count.get("video", 0) >= min_videos
    total = len(media_paths)
    p_cnt = media_count.get("photo", 0)
    v_cnt = media_count.get("video", 0)

    if not (p_ok and v_ok):
        remaining = []
        if not v_ok:
            remaining.append(f"📹 yana {min_videos - v_cnt} ta video")
        if not p_ok:
            remaining.append(f"🖼 yana {min_photos - p_cnt} ta rasm")
        await message.answer(
            f"✅ Qabul qilindi! (Jami: {total} ta)\n"
            f"📹 Video: {v_cnt} ta | 🖼 Rasm: {p_cnt} ta\n\n"
            f"📋 <b>Hali kerak:</b>\n" + "\n".join(remaining),
            parse_mode="HTML",
        )
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"✅ Hammasini Yuborish ({total} ta)", callback_data=f"b_media_done_{order_id}")
    ]])
    await message.answer(
        f"✅ Minimum talablar bajarildi!\n"
        f"📹 Video: {v_cnt} ta | 🖼 Rasm: {p_cnt} ta\n\n"
        f"Yana qo'shishingiz yoki tasdiqlashingiz mumkin 👇",
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
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
        if not order:
            await callback.answer("Buyurtma topilmadi!", show_alert=True)
            return
        order.status = OrderStatus.ARRIVED_B
        for m in media_paths:
            session.add(OrderMedia(order_id=order_id, file_type=m["type"], file_id=m["id"], stage="arrived_b"))
        disp_tg_id  = order.dispatcher_id
        cargo       = order.cargo_description
        point_a     = order.point_a
        point_b     = order.point_b
        v_num       = order.vehicle_number or "—"
        drv_b       = (await session.execute(select(User).where(User.telegram_id == order.driver_id))).scalar_one_or_none()
        driver_name = drv_b.full_name if drv_b else callback.from_user.full_name
        driver_phone= drv_b.phone if drv_b and drv_b.phone else "—"
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
            await _send_media_group_safe(callback.bot, disp_tg_id, media_paths)
            await callback.bot.send_message(
                chat_id=disp_tg_id,
                text=(
                    f"🏁 <b>#{order_id} — Haydovchi B nuqtaga yetdi!</b>\n\n"
                    f"👤 Haydovchi: {driver_name}\n"
                    f"📱 Tel: {driver_phone}\n"
                    f"🚘 Mashina: {v_num}\n"
                    f"📦 Yuk: {cargo}\n"
                    f"🔵 {point_a} → 🔴 {point_b}\n\n"
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
        f"📤 <b>Yuk tushirilishi — media yuborish</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{MEDIA_INSTRUCTION}\n"
        f"━━━━━━━━━━━━━━━━━━",
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
        f"1️⃣ 📎 ikonkasiga bosing\n"
        f"2️⃣ <b>Location</b> → <b>Send My Current Location</b>",
        parse_mode="HTML",
    )


# ─── KARTA VA MA'LUMOTLAR ─────────────────────────────────────────────────────
@driver_router.message(F.text == "💳 Karta va ma'lumotlarim")
async def show_card_info(message: Message, user: User):
    if user.role != UserRole.DRIVER:
        return
    card = user.card_number or "❌ Kiritilmagan"
    name = user.full_name or "❌ Kiritilmagan"
    phone = user.phone or "❌ Kiritilmagan"
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Ma'lumotlarni yangilash", callback_data="update_driver_info")
    await message.answer(
        f"👤 <b>Sizning ma'lumotlaringiz:</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📛 Ism-familya: <b>{name}</b>\n"
        f"📱 Telefon: <b>{phone}</b>\n"
        f"💳 Karta raqami: <code>{card}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"Ma'lumotlarni yangilash uchun bosing 👇",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@driver_router.callback_query(F.data == "update_driver_info")
async def request_driver_info_update(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DriverSteps.waiting_for_first_name)
    await callback.message.answer(
        "📝 <b>Ismingizni kiriting:</b>\n\n<i>Misol: Jahongir</i>",
        parse_mode="HTML",
    )


@driver_router.message(DriverSteps.waiting_for_first_name)
async def save_first_name(message: Message, state: FSMContext):
    first_name = message.text.strip()
    if not first_name or len(first_name) < 2:
        await message.answer("❌ Iltimos, to'g'ri ism kiriting.\n<i>Misol: Jahongir</i>", parse_mode="HTML")
        return
    await state.update_data(first_name=first_name)
    await state.set_state(DriverSteps.waiting_for_last_name)
    await message.answer(
        f"✅ Ism: <b>{first_name}</b>\n\n📝 <b>Familyangizni kiriting:</b>\n\n<i>Misol: Karimov</i>",
        parse_mode="HTML",
    )


@driver_router.message(DriverSteps.waiting_for_last_name)
async def save_last_name(message: Message, state: FSMContext):
    last_name = message.text.strip()
    if not last_name or len(last_name) < 2:
        await message.answer("❌ Iltimos, to'g'ri familya kiriting.\n<i>Misol: Karimov</i>", parse_mode="HTML")
        return
    data       = await state.get_data()
    first_name = data.get("first_name", "")
    full_name  = f"{first_name} {last_name}"
    await state.update_data(full_name=full_name)
    await state.set_state(DriverSteps.waiting_for_card)
    await message.answer(
        f"✅ Ism-familya: <b>{full_name}</b>\n\n"
        f"💳 <b>Karta raqamingizni kiriting:</b>\n\n"
        f"<i>Misol: 8600 1234 5678 9012</i>\n\n"
        f"⚠️ 16 ta raqam bo'lishi shart",
        parse_mode="HTML",
    )


@driver_router.message(DriverSteps.waiting_for_card)
async def save_card(message: Message, state: FSMContext, user: User):
    data     = await state.get_data()
    new_name = data.get("full_name", user.full_name)

    raw_card = message.text.strip().replace(" ", "").replace("-", "")
    if not raw_card.isdigit() or len(raw_card) != 16:
        await message.answer(
            "❌ <b>Noto'g'ri karta raqami!</b>\n\n"
            "Karta raqami aniq <b>16 ta raqam</b>dan iborat bo'lishi kerak.\n\n"
            "<i>Misol: 8600 1234 5678 9012</i>\n\nQaytadan kiriting:",
            parse_mode="HTML",
        )
        return

    formatted_card = " ".join([raw_card[i:i+4] for i in range(0, 16, 4)])

    async with async_session() as session:
        await session.execute(
            update(User)
            .where(User.telegram_id == user.telegram_id)
            .values(card_number=formatted_card, full_name=new_name)
        )
        await session.commit()

    await message.answer(
        f"✅ <b>Ma'lumotlar muvaffaqiyatli saqlandi!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📛 Ism-familya: <b>{new_name}</b>\n"
        f"💳 Karta: <code>{formatted_card}</code>\n"
        f"━━━━━━━━━━━━━━━━━━",
        reply_markup=get_driver_main_keyboard(),
        parse_mode="HTML",
    )
    await state.clear()
