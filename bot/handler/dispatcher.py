import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from sqlalchemy import select

from database.session import async_session
from database.models import User, UserRole, Order, OrderStatus, OrderMedia, OrderLocation
from bot.keyboards.dispatcher_kb import get_dispatcher_main_keyboard

dispatcher_router = Router()


class DispatcherStates(StatesGroup):
    waiting_for_vehicle_number  = State()
    waiting_for_rejection_reason = State()


# ─── /start ──────────────────────────────────────────────────────────────────
@dispatcher_router.message(Command("start"))
async def dispatcher_start(message: Message, user: User):
    if user.role == UserRole.DISPATCHER:
        await message.answer(
            "🎧 Xush kelibsiz, Dispetcher!",
            reply_markup=get_dispatcher_main_keyboard(),
        )


# ─── YANGI BUYURTMALAR ───────────────────────────────────────────────────────
@dispatcher_router.message(F.text == "📥 Yangi buyurtmalar")
async def view_assigned_orders(message: Message, user: User):
    if user.role != UserRole.DISPATCHER:
        return

    async with async_session() as session:
        orders = (
            await session.execute(
                select(Order).where(
                    Order.dispatcher_id == user.telegram_id,
                    Order.status == OrderStatus.DISPATCHER_ASSIGNED,
                )
            )
        ).scalars().all()

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
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🔵 A nuqta: {order.point_a}\n"
            f"🔴 B nuqta: {order.point_b}\n"
            f"📦 Yuk: {order.cargo_description}\n"
            f"💸 Limit: {price} so'm\n"
            f"━━━━━━━━━━━━━━━━━━",
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )


# ─── HAYDOVCHILAR RO'YXATI ───────────────────────────────────────────────────
@dispatcher_router.callback_query(F.data.startswith("find_driver_"))
async def list_drivers(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    async with async_session() as session:
        drivers = (
            await session.execute(select(User).where(User.role == UserRole.DRIVER))
        ).scalars().all()

    if not drivers:
        await callback.answer("Bazada haydovchilar yo'q!", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    for d in drivers:
        card = f" | {d.card_number}" if d.card_number else ""
        kb.button(text=f"👨‍✈️ {d.full_name}{card}", callback_data=f"ask_vnum_{order_id}_{d.id}")
    kb.adjust(1)
    await callback.message.edit_text(
        f"👨‍✈️ <b>#{order_id} uchun haydovchi tanlang:</b>",
        reply_markup=kb.as_markup(), parse_mode="HTML",
    )


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
    order_id    = data["temp_order_id"]
    driver_db_id = data["temp_driver_id"]

    async with async_session() as session:
        order  = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        driver = (await session.execute(select(User).where(User.id == driver_db_id))).scalar_one()

        order.driver_id     = driver.telegram_id
        order.vehicle_number = v_number
        order.status        = OrderStatus.DRIVER_ASSIGNED

        client = (
            await session.execute(select(User).where(User.phone == order.client_phone))
        ).scalar_one_or_none()
        await session.commit()

    await message.answer(
        f"✅ <b>#{order_id}</b> — {driver.full_name} ({v_number})ga biriktirildi!",
        parse_mode="HTML",
    )

    # Haydovchiga to'liq ma'lumot
    try:
        await message.bot.send_message(
            chat_id=driver.telegram_id,
            text=(
                f"🎉 <b>Sizga yangi buyurtma biriktirildi!</b>\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📦 <b>Buyurtma #{order_id}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"🔵 <b>A NUQTA (YUKLASH):</b>\n"
                f"   📍 {order.point_a}\n\n"
                f"🔴 <b>B NUQTA (TUSHIRISH):</b>\n"
                f"   📍 {order.point_b}\n\n"
                f"📦 <b>YUK:</b> {order.cargo_description}\n"
                f"🚘 <b>Mashina:</b> {v_number}\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"📌 <b>Keyingi qadam:</b>\n"
                f"A nuqtaga boring → <b>🚚 Mening yuklarim</b> → "
                f"<b>✅ A nuqtaga yetib keldim</b>"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass

    # Mijozga xabar
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
        except Exception:
            pass

    await state.clear()


# ─── LOADING_A TASDIQLASH ─────────────────────────────────────────────────────
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
                    f"Endi yo'lga chiqishingiz mumkin.\n\n"
                    f"📌 <b>🚚 Mening yuklarim</b> → <b>🚀 Yo'lga chiqdim</b>"
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass


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
        f"✅ <b>#{order_id}</b> — Yuk tushirilishi tasdiqlandi. Kassirga yuborildi.",
        parse_mode="HTML",
    )

    # Haydovchiga
    if driver and driver.telegram_id:
        try:
            await callback.bot.send_message(
                chat_id=driver.telegram_id,
                text=(
                    f"✅ <b>Yuk muvaffaqiyatli tushirildi!</b>\n\n"
                    f"Buyurtma <b>#{order_id}</b>\n"
                    f"💳 Karta: <code>{driver.card_number or 'Kiritilmagan'}</code>\n\n"
                    f"To'lov tez orada amalga oshiriladi."
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    # Kassirga
    for cashier in cashiers:
        if cashier.telegram_id:
            kb = InlineKeyboardBuilder()
            kb.button(text="💵 To'lov qildim", callback_data=f"pay_order_{order_id}")
            try:
                await callback.bot.send_message(
                    chat_id=cashier.telegram_id,
                    text=(
                        f"🔔 <b>TO'LOV KERAK! #{order_id}</b>\n\n"
                        f"👨‍✈️ Haydovchi: {driver.full_name if driver else 'Noma\'lum'}\n"
                        f"💳 Karta: <code>{driver.card_number if driver and driver.card_number else 'Kiritilmagan'}</code>\n"
                        f"💰 Summa: <b>{order.cost_price:,.0f} so'm</b>"
                    ),
                    reply_markup=kb.as_markup(),
                    parse_mode="HTML",
                )
            except Exception:
                pass

    # Logistga
    if logist and logist.telegram_id:
        try:
            await callback.bot.send_message(
                logist.telegram_id,
                f"✅ <b>#{order_id} yuk tushirildi!</b>\nTo'lov jarayoni boshlandi.",
                parse_mode="HTML",
            )
        except Exception:
            pass

    # Mijozga
    if client and client.telegram_id:
        try:
            await callback.bot.send_message(
                client.telegram_id,
                f"🎉 <b>Yukingiz yetkazildi!</b>\n\nBuyurtma <b>#{order_id}</b> muvaffaqiyatli yakunlandi.",
                parse_mode="HTML",
            )
        except Exception:
            pass


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
    order_id = data["reject_order_id"]
    stage    = data["reject_stage"]
    reason   = message.text

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
                text=(
                    f"❌ <b>Media rad etildi</b>\n\n"
                    f"📦 Buyurtma: #{order_id}\n"
                    f"📋 Bosqich: {stage_text}\n\n"
                    f"💬 <b>Sabab:</b> {reason}\n\n"
                    f"To'g'ri va aniq media yuborib, qayta urinib ko'ring."
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass
    await state.clear()


# ─── YO'LGA CHIQISHNI TASDIQLASH ─────────────────────────────────────────────
@dispatcher_router.callback_query(F.data.startswith("disp_confirm_onway_"))
async def confirm_on_way(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[3])
    async with async_session() as session:
        order  = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        client = (await session.execute(select(User).where(User.phone == order.client_phone))).scalar_one_or_none()

    await callback.message.edit_text(
        f"✅ <b>#{order_id}</b> — Yo'lga chiqish tasdiqlandi.", parse_mode="HTML"
    )
    if client and client.telegram_id:
        try:
            await callback.bot.send_message(
                client.telegram_id,
                f"🚛 <b>#{order_id} yukingiz yo'lda!</b>\n\n"
                f"Marshrut: {order.point_a} → {order.point_b}",
                parse_mode="HTML",
            )
        except Exception:
            pass


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
        f"✅ <b>#{order_id}</b> — B nuqtaga kelgani tasdiqlandi. Logistga so'rov ketdi.",
        parse_mode="HTML",
    )

    # Logistga shot-faktura so'rash
    kb = InlineKeyboardBuilder()
    kb.button(text="📄 Shot-faktura yuborish", callback_data=f"send_invoice_{order_id}")
    try:
        await callback.bot.send_message(
            chat_id=logist.telegram_id,
            text=(
                f"⚡ <b>#{order_id} — Haydovchi B nuqtada!</b>\n\n"
                f"Iltimos, Didox tizimidan shot-fakturani yuklab, botga yuboring.\n\n"
                f"👇 Tugmani bosing:"
            ),
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )
    except Exception:
        pass

    # Haydovchiga kutishni aytish
    if driver and driver.telegram_id:
        try:
            await callback.bot.send_message(
                driver.telegram_id,
                "⏳ <b>Tasdiqlandi!</b>\nLogist fakturani yuborishini kuting.",
                parse_mode="HTML",
            )
        except Exception:
            pass


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
        order   = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        client  = (await session.execute(select(User).where(User.phone == order.client_phone))).scalar_one_or_none()
        last_loc = (
            await session.execute(
                select(OrderLocation)
                .where(OrderLocation.order_id == order_id)
                .order_by(OrderLocation.id.desc())
            )
        ).scalars().first()

    if not client or not client.telegram_id:
        await callback.answer("Mijoz botdan ro'yxatdan o'tmagan!", show_alert=True)
        return

    try:
        if last_loc:
            await callback.bot.send_location(
                chat_id=client.telegram_id,
                latitude=last_loc.latitude,
                longitude=last_loc.longitude,
            )
        await callback.bot.send_message(
            client.telegram_id,
            f"📍 <b>#{order_id} — Yukingizning joriy joylashuvi</b>",
            parse_mode="HTML",
        )
        await callback.message.answer("✅ Joylashuv mijozga yuborildi.")
    except Exception as e:
        await callback.answer(f"Xato: {e}", show_alert=True)


# ─── STATISTIKA ──────────────────────────────────────────────────────────────
@dispatcher_router.message(F.text == "📊 Mening statistikam")
async def dispatcher_stats(message: Message, user: User):
    if user.role != UserRole.DISPATCHER:
        return
    async with async_session() as session:
        orders = (
            await session.execute(select(Order).where(Order.dispatcher_id == user.telegram_id))
        ).scalars().all()

    total     = len(orders)
    completed = len([o for o in orders if o.status in (OrderStatus.PAID, OrderStatus.COMPLETED)])
    active    = total - completed

    await message.answer(
        f"📊 <b>Sizning statistikangiz:</b>\n\n"
        f"📋 Jami: {total} ta\n"
        f"⏳ Faol: {active} ta\n"
        f"✅ Yakunlangan: {completed} ta",
        parse_mode="HTML",
    )
