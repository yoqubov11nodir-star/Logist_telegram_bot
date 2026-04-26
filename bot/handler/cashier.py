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

        driver_ids = [o.driver_id for o in orders if o.driver_id]
        drivers_map: dict = {}
        if driver_ids:
            drivers_list = (
                await session.execute(
                    select(User).where(User.telegram_id.in_(driver_ids))
                )
            ).scalars().all()
            drivers_map = {d.telegram_id: d for d in drivers_list}

    for order in orders:
        driver = drivers_map.get(order.driver_id)
        driver_name = driver.full_name if driver else "Noma'lum"
        driver_phone = driver.phone if driver and driver.phone else "—"
        card = driver.card_number if driver and driver.card_number else "Kiritilmagan"
        kb = InlineKeyboardBuilder()
        kb.button(text="💳 To'lovni amalga oshirish", callback_data=f"pay_order_{order.id}")
        await message.answer(
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Buyurtma #{order.id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🚛 Haydovchi: <b>{driver_name}</b>\n"
            f"📱 Tel: {driver_phone}\n"
            f"💳 Karta: <code>{card}</code>\n"
            f"📍 {order.point_a} → {order.point_b}\n"
            f"📦 Yuk: {order.cargo_description}\n"
            f"🚘 Mashina: {order.vehicle_number or '—'}\n"
            f"💰 To'lov summasi: <b>{order.cost_price:,.0f} so'm</b>\n"
            f"━━━━━━━━━━━━━━━━━━",
            reply_markup=kb.as_markup(), parse_mode="HTML",
        )


@cashier_router.callback_query(F.data.startswith("pay_order_"))
async def process_payment_start(callback: CallbackQuery, state: FSMContext, user: User):
    if user.role != UserRole.CASHIER:
        await callback.answer("Bu amal faqat kassir uchun!", show_alert=True)
        return
    order_id = int(callback.data.split("_")[2])
    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
        if not order:
            await callback.answer("Buyurtma topilmadi!", show_alert=True)
            return
        driver = (await session.execute(select(User).where(User.telegram_id == order.driver_id))).scalar_one_or_none()
    card = driver.card_number if driver and driver.card_number else "Kiritilmagan"
    name = driver.full_name if driver else "Noma'lum"
    phone = driver.phone if driver and driver.phone else "—"
    await state.update_data(current_order_id=order_id)
    await state.set_state(CashierSteps.waiting_for_receipt)
    await callback.message.answer(
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💳 <b>To'lov ma'lumotlari — #{order_id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👨‍✈️ Haydovchi: <b>{name}</b>\n"
        f"📱 Tel: {phone}\n"
        f"💳 Karta: <code>{card}</code>\n"
        f"💰 Summa: <b>{order.cost_price:,.0f} so'm</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"To'lovni bajaring va <b>chek rasmini</b> yoki <b>PDF faylini</b> yuboring.",
        parse_mode="HTML",
    )


async def _process_receipt(message: Message, state: FSMContext, receipt_file_id: str, is_document: bool):
    data = await state.get_data()
    order_id = data["current_order_id"]

    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
        if not order:
            await message.answer("❌ Buyurtma topilmadi.")
            await state.clear()
            return
        order.status = OrderStatus.COMPLETED
        await session.commit()
        driver     = (await session.execute(select(User).where(User.telegram_id == order.driver_id))).scalar_one_or_none()
        logist     = (await session.execute(select(User).where(User.telegram_id == order.logist_id))).scalar_one_or_none()
        dispatcher = (await session.execute(select(User).where(User.telegram_id == order.dispatcher_id))).scalar_one_or_none()
        founder    = (await session.execute(select(User).where(User.role == UserRole.FOUNDER))).scalars().first()
        profit     = (order.sale_price or 0) - (order.cost_price or 0)

    await message.answer(
        f"✅ <b>To'lov qabul qilindi! Buyurtma #{order_id} yakunlandi.</b>",
        reply_markup=get_cashier_main_keyboard(),
        parse_mode="HTML",
    )

    caption_driver = (
        f"💳 <b>To'lov amalga oshirildi!</b>\n\n"
        f"📦 Buyurtma: #{order_id}\n"
        f"💰 Summa: {order.cost_price:,.0f} so'm\n"
        f"💳 Karta: <code>{driver.card_number if driver else '—'}</code>\n\n"
        f"🙏 Siz bilan ishlaganimizdan mamnunmiz! Keyingi safar ham kutamiz. 🚛"
    )

    if driver and driver.telegram_id:
        try:
            if is_document:
                await message.bot.send_document(
                    chat_id=driver.telegram_id,
                    document=receipt_file_id,
                    caption=caption_driver,
                    parse_mode="HTML",
                )
            else:
                await message.bot.send_photo(
                    chat_id=driver.telegram_id,
                    photo=receipt_file_id,
                    caption=caption_driver,
                    parse_mode="HTML",
                )
        except Exception as e:
            logging.error(f"Haydovchiga chek: {e}")

    if dispatcher and dispatcher.telegram_id:
        try:
            await message.bot.send_message(
                dispatcher.telegram_id,
                f"✅ <b>#{order_id} to'liq yakunlandi!</b>\n\nKassir to'lovni amalga oshirdi.",
                parse_mode="HTML",
            )
        except Exception:
            pass

    if founder and founder.telegram_id:
        try:
            await message.bot.send_message(
                founder.telegram_id,
                f"✅ <b>#{order_id} buyurtma yakunlandi!</b>\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"👤 Logist: {logist.full_name if logist else '—'} | {logist.phone if logist and logist.phone else '—'}\n"
                f"🎧 Dispetcher: {dispatcher.full_name if dispatcher else '—'} | {dispatcher.phone if dispatcher and dispatcher.phone else '—'}\n"
                f"🚛 Haydovchi: {driver.full_name if driver else '—'} | {driver.phone if driver and driver.phone else '—'}\n"
                f"🚘 Mashina: {order.vehicle_number or '—'}\n"
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


@cashier_router.message(CashierSteps.waiting_for_receipt, F.photo)
async def handle_payment_receipt_photo(message: Message, state: FSMContext):
    await _process_receipt(message, state, message.photo[-1].file_id, is_document=False)


@cashier_router.message(CashierSteps.waiting_for_receipt, F.document)
async def handle_payment_receipt_document(message: Message, state: FSMContext):
    await _process_receipt(message, state, message.document.file_id, is_document=True)
