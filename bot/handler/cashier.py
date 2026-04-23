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
 
    # Bitta session ichida: orders + barcha driverlar — N+1 muammo yo'q
    async with async_session() as session:
        orders = (
            await session.execute(
                select(Order).where(Order.status == OrderStatus.UNLOADED)
            )
        ).scalars().all()
 
        if not orders:
            await message.answer("📭 Hozirda to'lov kutayotgan buyurtmalar yo'q.")
            return
 
        # Barcha driver_id larni to'plash va bitta query bilan olish
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
        card = driver.card_number if driver and driver.card_number else "Kiritilmagan"
        kb = InlineKeyboardBuilder()
        kb.button(text="💳 To'lovni amalga oshirish", callback_data=f"pay_order_{order.id}")
        await message.answer(
            f"━━━━━━━━━━━━━━━━━━\n📦 <b>Buyurtma #{order.id}</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"🚛 Haydovchi: {driver_name}\n💳 Karta: <code>{card}</code>\n"
            f"📍 {order.point_a} → {order.point_b}\n📦 Yuk: {order.cargo_description}\n"
            f"💰 To'lov summasi: <b>{order.cost_price:,.0f} so'm</b>\n━━━━━━━━━━━━━━━━━━",
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
    await state.update_data(current_order_id=order_id)
    await state.set_state(CashierSteps.waiting_for_receipt)
    await callback.message.answer(
        f"💳 <b>To'lov ma'lumotlari — #{order_id}</b>\n\n"
        f"👨‍✈️ Haydovchi: {name}\n💳 Karta: <code>{card}</code>\n"
        f"💰 Summa: <b>{order.cost_price:,.0f} so'm</b>\n\nTo'lovni bajaring va <b>chek rasmini yuboring</b>.",
        parse_mode="HTML",
    )
 
@cashier_router.message(CashierSteps.waiting_for_receipt, F.photo)
async def handle_payment_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data["current_order_id"]
    receipt_file_id = message.photo[-1].file_id
 
    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        order.status = OrderStatus.COMPLETED  # BUG TUZATILDI: bitta commit
        await session.commit()
        driver     = (await session.execute(select(User).where(User.telegram_id == order.driver_id))).scalar_one_or_none()
        logist     = (await session.execute(select(User).where(User.telegram_id == order.logist_id))).scalar_one_or_none()
        dispatcher = (await session.execute(select(User).where(User.telegram_id == order.dispatcher_id))).scalar_one_or_none()
        founder    = (await session.execute(select(User).where(User.role == UserRole.FOUNDER))).scalars().first()
        profit     = (order.sale_price or 0) - (order.cost_price or 0)
 
    await message.answer(f"✅ <b>To'lov qabul qilindi! Buyurtma #{order_id} yakunlandi.</b>", parse_mode="HTML")
 
    if driver and driver.telegram_id:
        try:
            await message.bot.send_photo(
                chat_id=driver.telegram_id, photo=receipt_file_id,
                caption=(f"💳 <b>To'lov amalga oshirildi!</b>\n\n📦 Buyurtma: #{order_id}\n"
                         f"💰 Summa: {order.cost_price:,.0f} so'm\n💳 Karta: <code>{driver.card_number or '—'}</code>\n\n"
                         f"🙏 Siz bilan ishlaganimizdan mamnunmiz!\nKeyingi safar ham kutamiz. 🚛"),
                parse_mode="HTML",
            )
        except Exception as e:
            logging.error(f"Haydovchiga chek: {e}")
 
    if dispatcher and dispatcher.telegram_id:
        try:
            await message.bot.send_message(dispatcher.telegram_id,
                f"✅ <b>#{order_id} to'liq yakunlandi!</b>\n\nKassir to'lovni amalga oshirdi.", parse_mode="HTML")
        except Exception: pass
 
    if founder and founder.telegram_id:
        try:
            await message.bot.send_message(
                founder.telegram_id,
                f"✅ <b>#{order_id} buyurtma yakunlandi!</b>\n\n━━━━━━━━━━━━━━━━━━\n"
                f"👤 Logist: {logist.full_name if logist else '—'}\n"
                f"🎧 Dispetcher: {dispatcher.full_name if dispatcher else '—'}\n"
                f"🚛 Haydovchi: {driver.full_name if driver else '—'}\n"
                f"📍 {order.point_a} → {order.point_b}\n━━━━━━━━━━━━━━━━━━\n"
                f"💵 Sotish: {order.sale_price:,.0f} so'm\n🚛 Xarajat: {order.cost_price:,.0f} so'm\n"
                f"💰 <b>Foyda: {profit:,.0f} so'm</b>",
                parse_mode="HTML",
            )
        except Exception as e:
            logging.error(f"Founderga hisobot: {e}")
 
    await state.clear()