import asyncio
import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from database.session import async_session
from database.models import User, Order, OrderStatus, UserRole
from bot.keyboards.client_kb import get_client_main_keyboard

client_router = Router()

STATUS_UZ = {
    "NEW":                 "🆕 Yangi",
    "DISPATCHER_ASSIGNED": "📋 Dispetcherga biriktirildi",
    "DRIVER_ASSIGNED":     "🚛 Haydovchi biriktirildi",
    "ARRIVED_A":           "📍 Yuk ortish joyida",
    "LOADING":             "📦 Yuk ortilmoqda",
    "ON_WAY":              "🚚 Yo'lda",
    "ARRIVED_B":           "🏁 Manzilga yetdi",
    "DIDOX_TASDIQDA":      "📄 Hujjat rasmiylashtirilyapti",
    "UNLOADED":            "📤 Yuk tushirildi",
    "PAID":                "💰 To'langan",
    "COMPLETED":           "✅ Yakunlandi",
    "CANCELLED":           "❌ Bekor qilindi",
}


# ─── BUYURTMALARIM ───────────────────────────────────────────────────────────
@client_router.message(F.text == "📦 Buyurtmalarim")
async def client_orders_list(message: Message, user: User):
    if user.role != UserRole.CLIENT:
        return
    async with async_session() as session:
        orders = (
            await session.execute(
                select(Order)
                .where(Order.client_phone == user.phone)
                .order_by(Order.id.desc())
            )
        ).scalars().all()

    if not orders:
        await message.answer("📭 Sizda hozircha buyurtmalar mavjud emas.")
        return

    for o in orders:
        status_name = STATUS_UZ.get(o.status.value, o.status.value)
        kb = InlineKeyboardBuilder()

        if o.status == OrderStatus.ON_WAY:
            kb.button(text="📍 Yukingiz qayerda?", callback_data=f"ask_driver_loc_{o.id}")

        markup = kb.as_markup() if kb.export() else None
        await message.answer(
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Buyurtma #{o.id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📦 Yuk: {o.cargo_description}\n"
            f"🔵 Yuklash: {o.point_a}\n"
            f"🔴 Tushirish: {o.point_b}\n"
            f"🚘 Mashina: {o.vehicle_number or '—'}\n"
            f"📊 <b>Holat: {status_name}</b>\n"
            f"━━━━━━━━━━━━━━━━━━",
            reply_markup=markup,
            parse_mode="HTML",
        )


# ─── YUKIM QAYERDA (menu tugmasi) ────────────────────────────────────────────
@client_router.message(F.text == "📍 Yukim qayerda?")
async def where_is_my_cargo_general(message: Message, user: User):
    if user.role != UserRole.CLIENT:
        return
    async with async_session() as session:
        orders = (
            await session.execute(
                select(Order).where(
                    Order.client_phone == user.phone,
                    Order.status == OrderStatus.ON_WAY,
                )
            )
        ).scalars().all()

    if not orders:
        await message.answer(
            "🚫 Hozirda yo'lda bo'lgan yukingiz topilmadi.\n\n"
            "📦 <b>Buyurtmalarim</b> bo'limidan barcha buyurtmalarni ko'rishingiz mumkin.",
            parse_mode="HTML",
        )
        return

    for o in orders:
        kb = InlineKeyboardBuilder()
        kb.button(text="📍 Lokatsiyani so'rash", callback_data=f"ask_driver_loc_{o.id}")
        await message.answer(
            f"🚚 <b>#{o.id} buyurtma yo'lda</b>\n\n"
            f"📦 Yuk: {o.cargo_description}\n"
            f"🔵 {o.point_a} → 🔴 {o.point_b}\n"
            f"🚘 Mashina: {o.vehicle_number or '—'}\n\n"
            f"Lokatsiyani so'rash uchun bosing 👇\n\n"
            f"<i>⏱ 15 daqiqa ichida aloqaga chiqiladi.</i>",
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )


# ─── LOKATSIYA SO'RASH (callback) ────────────────────────────────────────────
@client_router.callback_query(F.data.startswith("ask_driver_loc_"))
async def client_trigger_location(callback: CallbackQuery, user: User):
    from bot.handler.logist import location_timer_logic

    order_id = int(callback.data.split("_")[3])

    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
        if not order:
            await callback.answer("Buyurtma topilmadi!", show_alert=True)
            return
        driver = (await session.execute(select(User).where(User.telegram_id == order.driver_id))).scalar_one_or_none()
        logist = (await session.execute(select(User).where(User.telegram_id == order.logist_id))).scalar_one_or_none()
        disp   = (await session.execute(select(User).where(User.telegram_id == order.dispatcher_id))).scalar_one_or_none()

    if logist and logist.telegram_id:
        try:
            await callback.bot.send_message(
                logist.telegram_id,
                f"⚡ <b>Mijoz #{order_id} yukining qayerdaligini so'radi</b>\n"
                f"👤 Mijoz: {user.full_name or user.phone}\n"
                f"📦 Yuk: {order.cargo_description}\n"
                f"🔵 {order.point_a} → 🔴 {order.point_b}",
                parse_mode="HTML",
            )
        except Exception:
            pass

    if disp and disp.telegram_id:
        try:
            await callback.bot.send_message(
                disp.telegram_id,
                f"⚡ <b>Mijoz #{order_id} yukining qayerdaligini so'radi</b>\n"
                f"👤 Mijoz: {user.full_name or user.phone}\n"
                f"📦 Yuk: {order.cargo_description}\n"
                f"🔵 {order.point_a} → 🔴 {order.point_b}\n\n"
                f"Haydovchiga lokatsiya yuborishni so'rang.",
                parse_mode="HTML",
            )
        except Exception:
            pass

    if driver and driver.telegram_id:
        kb = InlineKeyboardBuilder()
        kb.button(text="📍 Lokatsiyamni yuborish", callback_data=f"act_on_way_{order_id}")
        try:
            await callback.bot.send_message(
                driver.telegram_id,
                f"📣 <b>DIQQAT! Mijoz qayerdaligingizni bilmoqchi!</b>\n\n"
                f"📦 Buyurtma: <b>#{order_id}</b>\n"
                f"🔵 {order.point_a} → 🔴 {order.point_b}\n"
                f"📦 Yuk: {order.cargo_description}\n\n"
                f"⬇️ Lokatsiyangizni yuboring:",
                reply_markup=kb.as_markup(),
                parse_mode="HTML",
            )
        except Exception:
            pass

        if logist and disp:
            asyncio.create_task(location_timer_logic(
                order_id, callback.bot,
                driver.full_name, disp.telegram_id, logist.telegram_id,
            ))

    await callback.answer("✅ Haydovchidan lokatsiya so'raldi.")
    try:
        await callback.message.answer(
            f"⏳ <b>Lokatsiya so'raldi!</b>\n\n"
            f"Haydovchi lokatsiyasini yuborgach, dispetcher sizga yuboradi.\n"
            f"<i>15 daqiqa ichida aloqaga chiqiladi.</i>",
            parse_mode="HTML",
        )
    except Exception:
        pass
