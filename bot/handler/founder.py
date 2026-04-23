import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from sqlalchemy import select, update, func

from database.session import async_session
from database.models import User, UserRole, Order, OrderStatus
from bot.keyboards.founder_kb import founder_main_kb

founder_router = Router()

ROLE_NAMES = {
    "FOUNDER":    "👑 Asoschi",
    "LOGIST":     "📋 Logist",
    "DISPATCHER": "🎧 Dispetcher",
    "DRIVER":     "🚛 Haydovchi",
    "CASHIER":    "💵 Kassir",
    "CLIENT":     "👤 Mijoz",
    "PENDING":    "⏳ Kutmoqda",
}

STATUS_UZ = {
    "NEW":                 "🆕 Yangi",
    "DISPATCHER_ASSIGNED": "📋 Dispetcherda",
    "DRIVER_ASSIGNED":     "🚛 Haydovchi biriktirildi",
    "ARRIVED_A":           "📍 A nuqtada",
    "LOADING":             "📦 Ortilmoqda",
    "ON_WAY":              "🚚 Yo'lda",
    "ARRIVED_B":           "🏁 B nuqtada",
    "DIDOX_TASDIQDA":      "✅ Faktura yuborildi",
    "UNLOADED":            "📤 Tushirildi",
    "PAID":                "💰 To'langan",
    "COMPLETED":           "✅ Yakunlandi",
    "CANCELLED":           "❌ Bekor",
}


# ─── BARCHA BUYURTMALAR ───────────────────────────────────────────────────────
@founder_router.message(F.text == "📊 Barcha buyurtmalar")
async def view_all_orders(message: Message, user: User):
    if not user or user.role != UserRole.FOUNDER:
        return

    async with async_session() as session:
        try:
            orders = (
                await session.execute(select(Order).order_by(Order.id.desc()))
            ).scalars().all()

            if not orders:
                await message.answer("📭 Tizimda hali birorta ham buyurtma yaratilmagan.")
                return

            chunks  = []
            current = "📋 <b>BARCHA BUYURTMALAR:</b>\n\n"

            for o in orders:
                sale   = o.sale_price or 0
                cost   = o.cost_price or 0
                profit = sale - cost
                status = STATUS_UZ.get(o.status.value, o.status.value)

                entry = (
                    f"🆔 <b>#{o.id}</b> — {status}\n"
                    f"📍 {o.point_a} → {o.point_b}\n"
                    f"📦 {o.cargo_description}\n"
                    f"💰 Sotish: {sale:,.0f} | Xarajat: {cost:,.0f} | Foyda: {profit:,.0f}\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                )
                if len(current) + len(entry) > 3800:
                    chunks.append(current)
                    current = entry
                else:
                    current += entry

            if current:
                chunks.append(current)

            for chunk in chunks:
                await message.answer(chunk, parse_mode="HTML")

        except Exception as e:
            logging.error(f"view_all_orders xato: {e}")
            await message.answer("❌ Ma'lumotlarni yuklashda xatolik.")


# ─── FOYDA STATISTIKASI ───────────────────────────────────────────────────────
@founder_router.message(F.text.in_(["💰 Foyda statistikasi", "📊 Umumiy foyda"]))
async def show_total_profit(message: Message, user: User):
    if not user or user.role != UserRole.FOUNDER:
        return

    async with async_session() as session:
        try:
            # Yakunlangan buyurtmalar statistikasi
            stats = (
                await session.execute(
                    select(
                        func.count(Order.id).label("count"),
                        func.sum(Order.sale_price).label("income"),
                        func.sum(Order.cost_price).label("expense"),
                    ).where(Order.status.in_([OrderStatus.COMPLETED, OrderStatus.PAID]))
                )
            ).first()

            count   = stats.count   if stats and stats.count   else 0
            income  = float(stats.income)  if stats and stats.income  else 0.0
            expense = float(stats.expense) if stats and stats.expense else 0.0
            profit  = income - expense

            # Umumiy va faol
            all_count = (await session.execute(select(func.count(Order.id)))).scalar() or 0
            active_count = (
                await session.execute(
                    select(func.count(Order.id)).where(
                        Order.status.notin_([
                            OrderStatus.COMPLETED, OrderStatus.PAID, OrderStatus.CANCELLED
                        ])
                    )
                )
            ).scalar() or 0

            await message.answer(
                f"📊 <b>MOLIYAVIY HISOBOT</b>\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📋 Jami buyurtmalar: {all_count} ta\n"
                f"⏳ Faol: {active_count} ta\n"
                f"✅ Yakunlangan: {count} ta\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💵 Umumiy tushum:  {income:,.0f} so'm\n"
                f"⛽ Jami xarajat:   {expense:,.0f} so'm\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💰 <b>SOF FOYDA: {profit:,.0f} so'm</b>",
                parse_mode="HTML",
            )
        except Exception as e:
            logging.error(f"show_total_profit xato: {e}")
            await message.answer("❌ Statistikani hisoblashda xatolik.")


# ─── XODIMLAR FAOLIYATI ───────────────────────────────────────────────────────
@founder_router.message(F.text == "👥 Xodimlar faoliyati")
async def staff_activity(message: Message, user: User):
    if not user or user.role != UserRole.FOUNDER:
        return

    async with async_session() as session:
        users = (
            await session.execute(select(User).where(User.role != UserRole.PENDING))
        ).scalars().all()

    roles_count: dict = {}
    staff_lines = []

    for u in users:
        role_name = ROLE_NAMES.get(u.role.value, u.role.value)
        roles_count[role_name] = roles_count.get(role_name, 0) + 1
        staff_lines.append(f"• {u.full_name} — {role_name}")

    summary = "📊 <b>Umumiy statistika:</b>\n"
    for role, count in roles_count.items():
        summary += f"  {role}: {count} ta\n"

    staff_text = "\n".join(staff_lines) or "Xodimlar topilmadi."
    await message.answer(
        f"{summary}\n👥 <b>Xodimlar ro'yxati:</b>\n{staff_text}",
        parse_mode="HTML",
    )


# ─── ROL BERISH ───────────────────────────────────────────────────────────────
@founder_router.callback_query(F.data.startswith("set_role_"))
async def process_set_role(callback: CallbackQuery):
    try:
        parts        = callback.data.split("_")
        role_key     = parts[2]
        target_tg_id = int(parts[3])
        role_uz      = ROLE_NAMES.get(role_key, role_key)

        async with async_session() as session:
            target = (
                await session.execute(select(User).where(User.telegram_id == target_tg_id))
            ).scalar_one_or_none()

            if not target:
                await callback.answer("Foydalanuvchi topilmadi!", show_alert=True)
                return

            target.role = UserRole[role_key]
            await session.commit()

        await callback.message.edit_text(
            f"✅ <b>{target.full_name}</b> — <b>{role_uz}</b> etib tayinlandi!",
            parse_mode="HTML",
        )
        try:
            await callback.bot.send_message(
                chat_id=target_tg_id,
                text=(
                    f"🎉 <b>Rolingiz tasdiqlandi!</b>\n\n"
                    f"Sizga <b>{role_uz}</b> roli berildi.\n\n"
                    f"Botni ishlatish uchun /start bosing."
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    except Exception as e:
        logging.error(f"process_set_role xato: {e}")
        await callback.answer("Xatolik!")

