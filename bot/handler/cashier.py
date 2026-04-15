from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from database.session import async_session
from database.models import User, UserRole, Order, OrderStatus, OrderMedia # Payment modeli bazada bo'lsa qo'shing
from bot.states.cashier_states import CashierSteps

cashier_router = Router()

# 1. Kassir "To'lov qildim" tugmasini bosganda
@cashier_router.callback_query(F.data.startswith("pay_order_"))
async def process_payment_start(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[2])
    
    await state.update_data(current_order_id=order_id)
    await state.set_state(CashierSteps.waiting_for_receipt)
    
    await callback.message.answer(
        f"💳 #{order_id}-buyurtma uchun to'lov bajarildimi?\n"
        f"Iltimos, to'lov cheki (skrinshot/rasm)ni yuboring."
    )

# 2. Kassir chek rasmini yuborganda
@cashier_router.message(CashierSteps.waiting_for_receipt, F.photo)
async def handle_payment_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data['current_order_id']
    receipt_file_id = message.photo[-1].file_id

    async with async_session() as session:
        # Buyurtmani olish
        order_res = await session.execute(
            select(Order).where(Order.id == order_id)
        )
        order = order_res.scalar_one()
        
        # Statusni yakunlash
        order.status = OrderStatus.COMPLETED # YAKUNLANDI
        
        # Haydovchi va Logistni olish
        driver_res = await session.execute(select(User).where(User.id == order.driver_id))
        driver = driver_res.scalar_one()
        
        logist_res = await session.execute(select(User).where(User.id == order.logist_id))
        logist = logist_res.scalar_one()
        
        # Founder (Asoschi)ni topish
        founder_res = await session.execute(select(User).where(User.role == UserRole.FOUNDER))
        founder = founder_res.scalars().first()
        
        # To'lovni saqlash (Agar Payment modeli bo'lsa ishlaydi, bo'lmasa bu qismni o'chirib turing)
        # new_payment = Payment(
        #     order_id=order_id,
        #     receipt_path=receipt_file_id
        # )
        # session.add(new_payment)
        
        # Foyda hisobi (Modelsda sale_price deb yozilgan edi)
        profit = order.sale_price - order.cost_price
        
        await session.commit()

    await message.answer("✅ To'lov muvaffaqiyatli saqlandi. Buyurtma yopildi.")

    # 🔔 Haydovchiga chek va xabar
    try:
        await message.bot.send_photo(
            chat_id=driver.telegram_id,
            photo=receipt_file_id,
            caption=f"✅ Buyurtma #{order_id} yopildi. To'lov kartangizga o'tkazildi.\nRahmat!"
        )
    except Exception as e:
        print(f"Haydovchiga yuborishda xato: {e}")

    # 🔔 Founderga (Asoschi) HISOBOT
    if founder:
        report_text = (
            f"📊 **YAKUNIY HISOBOT (Order #{order_id})**\n\n"
            f"👤 **Logist:** {logist.full_name}\n"
            f"🚚 **Haydovchi:** {driver.full_name}\n"
            f"💰 **Sotildi:** {order.sale_price:,.0f} so'm\n"
            f"💸 **Xarajat:** {order.cost_price:,.0f} so'm\n"
            f"📈 **SOF FOYDA: {profit:,.0f} so'm**"
        )
        try:
            await message.bot.send_message(chat_id=founder.telegram_id, text=report_text, parse_mode="Markdown")
        except Exception as e:
            print(f"Founderga yuborishda xato: {e}")
    
    await state.clear()