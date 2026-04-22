import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from database.session import async_session
from database.models import User, UserRole, Order, OrderStatus
from bot.states.cashier_states import CashierSteps
from bot.keyboards.cashier_kb import get_cashier_main_keyboard

from aiogram.utils.keyboard import InlineKeyboardBuilder

cashier_router = Router()

@cashier_router.message(F.text == "💰 To'lov kutilayotganlar")
async def view_unloaded_orders(message: Message, user: User):
    if user.role != UserRole.CASHIER:
        return

    async with async_session() as session:
        orders = (
            await session.execute(
                select(Order).where(Order.status == OrderStatus.UNLOADED)
            )
        ).scalars().all()

    if not orders:
        await message.answer("📭 Hozirda to'lov kutayotgan buyurtmalar yo'q.")
        return

    for order in orders:
        async with async_session() as session:
            driver = (
                await session.execute(select(User).where(User.telegram_id == order.driver_id))
            ).scalar_one_or_none()

        driver_name = driver.full_name if driver else "Noma'lum"
        card = driver.card_number if driver and driver.card_number else "Kiritilmagan"

        kb = InlineKeyboardBuilder()
        kb.button(text="💳 To'lovni amalga oshirish", callback_data=f"pay_order_{order.id}")
        kb.adjust(1)

        await message.answer(
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Buyurtma #{order.id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🚛 Haydovchi: {driver_name}\n"
            f"💳 Karta: <code>{card}</code>\n"
            f"📍 {order.point_a} → {order.point_b}\n"
            f"💰 To'lov summasi: <b>{order.cost_price:,.0f} so'm</b>\n"
            f"━━━━━━━━━━━━━━━━━━",
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )

# ─── TO'LOV BOSHLASH ─────────────────────────────────────────────────────────
@cashier_router.callback_query(F.data.startswith("pay_order_"))
async def process_payment_start(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[2])

    async with async_session() as session:
        order  = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
        if not order:
            await callback.answer("Buyurtma topilmadi!", show_alert=True)
            return
        driver = (await session.execute(select(User).where(User.telegram_id == order.driver_id))).scalar_one_or_none()

    card = driver.card_number if driver and driver.card_number else "Kiritilmagan"
    name = driver.full_name   if driver else "Noma'lum"

    await state.update_data(current_order_id=order_id)
    await state.set_state(CashierSteps.waiting_for_receipt)

    await callback.message.answer(
        f"💳 <b>To'lov ma'lumotlari — #{order_id}</b>\n\n"
        f"👨‍✈️ Haydovchi: {name}\n"
        f"💳 Karta: <code>{card}</code>\n"
        f"💰 Summa: <b>{order.cost_price:,.0f} so'm</b>\n\n"
        f"To'lovni bajaring va <b>chek rasmini yuboring</b>.",
        parse_mode="HTML",
    )


# ─── CHEK QABUL QILISH ────────────────────────────────────────────────────────
@cashier_router.message(CashierSteps.waiting_for_receipt, F.photo)
async def handle_payment_receipt(message: Message, state: FSMContext):
    data             = await state.get_data()
    order_id         = data["current_order_id"]
    receipt_file_id  = message.photo[-1].file_id

    async with async_session() as session:
        order      = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        
        order.status = OrderStatus.PAID
        await session.commit()

        order.status = OrderStatus.COMPLETED
        await session.commit()

        driver     = (await session.execute(select(User).where(User.telegram_id == order.driver_id))).scalar_one_or_none()
        logist     = (await session.execute(select(User).where(User.telegram_id == order.logist_id))).scalar_one_or_none()
        dispatcher = (await session.execute(select(User).where(User.telegram_id == order.dispatcher_id))).scalar_one_or_none()
        founder    = (await session.execute(select(User).where(User.role == UserRole.FOUNDER))).scalars().first()
        client     = (await session.execute(select(User).where(User.phone == order.client_phone))).scalar_one_or_none()
        profit     = (order.sale_price or 0) - (order.cost_price or 0)
        await session.commit()

    await message.answer(
        f"✅ <b>To'lov qabul qilindi! Buyurtma #{order_id} yakunlandi.</b>",
        parse_mode="HTML",
    )

    # Haydovchiga — chek + xayrli so'z
    if driver and driver.telegram_id:
        try:
            await message.bot.send_photo(
                chat_id=driver.telegram_id,
                photo=receipt_file_id,
                caption=(
                    f"💳 <b>To'lov amalga oshirildi!</b>\n\n"
                    f"📦 Buyurtma: #{order_id}\n"
                    f"💰 Summa: {order.cost_price:,.0f} so'm\n"
                    f"💳 Karta: <code>{driver.card_number or '—'}</code>\n\n"
                    f"🙏 Siz bilan ishlaganimizdan mamnunmiz!\n"
                    f"Keyingi safar ham kutamiz. 🚛"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logging.error(f"Haydovchiga chek: {e}")

    # Dispetcherga
    if dispatcher and dispatcher.telegram_id:
        try:
            await message.bot.send_message(
                dispatcher.telegram_id,
                f"✅ <b>#{order_id} to'liq yakunlandi!</b>\n\nKassir to'lovni amalga oshirdi.",
                parse_mode="HTML",
            )
        except Exception:
            pass

    # Founderga — to'liq hisobot
    if founder and founder.telegram_id:
        try:
            await message.bot.send_message(
                founder.telegram_id,
                f"✅ <b>#{order_id} buyurtma yakunlandi!</b>\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"👤 Logist: {logist.full_name if logist else '—'}\n"
                f"🎧 Dispetcher: {dispatcher.full_name if dispatcher else '—'}\n"
                f"🚛 Haydovchi: {driver.full_name if driver else '—'}\n"
                f"📍 {order.point_a} → {order.point_b}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💵 Sotish: {order.sale_price:,.0f} so'm\n"
                f"🚛 Xarajat: {order.cost_price:,.0f} so'm\n"
                f"💰 <b>Foyda: {profit:,.0f} so'm</b>",
                parse_mode="HTML",
            )
        except Exception as e:
            logging.error(f"Founderga hisobot: {e}")

    await state.clear()
