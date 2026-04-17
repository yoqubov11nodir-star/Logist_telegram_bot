from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select, func
from database.session import async_session
from database.models import User, UserRole, Order, OrderStatus
import logging

founder_router = Router()

# 1. Barcha buyurtmalar ro'yxati
@founder_router.message(F.text == "📊 Barcha buyurtmalar")
async def view_all_orders(message: Message, user: User):
    if not user or user.role != UserRole.FOUNDER:
        return

    async with async_session() as session:
        try:
            result = await session.execute(select(Order).order_by(Order.id.desc()))
            orders = result.scalars().all()

            if not orders:
                await message.answer("📭 Tizimda hali birorta ham buyurtma yaratilmagan.")
                return

            response = "📋 **BARCHA BUYURTMALAR RO'YXATI:**\n\n"
            for order in orders:
                sale = order.sale_price or 0
                cost = order.cost_price or 0
                profit = sale - cost
                
                response += (
                    f"🆔 **ID: {order.id}**\n"
                    f"📦 Yuk: {order.cargo_description}\n"
                    f"💰 Sotish: {sale:,.0f} so'm\n"
                    f"🚛 Xarajat: {cost:,.0f} so'm\n"
                    f"💎 Foyda: {profit:,.0f} so'm\n"
                    f"📍 Status: {order.status.value}\n"
                    f"--------------------------\n"
                )

            # Telegram xabar limiti (4096 belgi) uchun split
            if len(response) > 4000:
                for x in range(0, len(response), 4000):
                    await message.answer(response[x:x+4000])
            else:
                await message.answer(response)
        except Exception as e:
            logging.error(f"Error viewing orders: {e}")
            await message.answer("❌ Ma'lumotlarni yuklashda xatolik.")

# 2. Xodimlar faoliyati
@founder_router.message(F.text == "👥 Xodimlar faoliyati")
async def staff_activity(message: Message, user: User):
    if not user or user.role != UserRole.FOUNDER:
        return

    async with async_session() as session:
        result = await session.execute(select(User).where(User.role != UserRole.PENDING))
        users = result.scalars().all()

        staff_list = "👥 **XODIMLAR RO'YXATI:**\n\n"
        roles_count = {}

        for u in users:
            role_name = u.role.value
            roles_count[role_name] = roles_count.get(role_name, 0) + 1
            staff_list += f"👤 {u.full_name} — **{role_name}**\n"

        summary = "📊 **Umumiy statistika:**\n"
        for role, count in roles_count.items():
            summary += f"▫️ {role}: {count} ta\n"

        await message.answer(summary + "\n" + staff_list)

# 3. Moliyaviy hisobot (Umumiy foyda)
@founder_router.message(F.text == "💰 Foyda statistikasi")
@founder_router.message(F.text == "📊 Umumiy foyda")
async def show_total_profit(message: Message, user: User):
    if not user or user.role != UserRole.FOUNDER:
        return

    async with async_session() as session:
        try:
            result = await session.execute(
                select(
                    func.count(Order.id).label("count"),
                    func.sum(Order.sale_price).label("income"),
                    func.sum(Order.cost_price).label("expense")
                ).where(Order.status.in_([OrderStatus.COMPLETED, OrderStatus.PAID]))
            )
            stats = result.one()
            
            # XATONI OLDINI OLISH: Agar None kelsa 0 deb olamiz
            count = stats.count or 0
            income = stats.income or 0
            expense = stats.expense or 0
            profit = income - expense

            await message.answer(
                f"📊 **KOMPANIYA MOLIYAVIY HISOBOTI**\n\n"
                f"✅ Yopilgan buyurtmalar: {count} ta\n"
                f"💵 Umumiy tushum: {income:,.0f} so'm\n"
                f"⛽️ Jami xarajat: {expense:,.0f} so'm\n"
                f"---------------------------\n"
                f"💰 **SOF FOYDA: {profit:,.0f} so'm**"
            )
        except Exception as e:
            logging.error(f"Profit stats error: {e}")
            await message.answer("❌ Statistikani hisoblashda xatolik yuz berdi.")

# 4. Yangi xodimlarga rol berish
@founder_router.callback_query(F.data.startswith("set_role_"))
async def process_set_role(callback: CallbackQuery):
    try:
        data = callback.data.split("_")
        role_key = data[2]   # Masalan: DRIVER
        target_tg_id = int(data[3]) 
        
        async with async_session() as session:
            res = await session.execute(select(User).where(User.telegram_id == target_tg_id))
            target_user = res.scalar_one_or_none()

            if target_user:
                target_user.role = UserRole[role_key]
                await session.commit()
                
                await callback.message.edit_text(f"✅ {target_user.full_name} — **{role_key}** etib tayinlandi!")
                
                try:
                    await callback.bot.send_message(
                        chat_id=target_tg_id,
                        text=f"🎉 Rolingiz tasdiqlandi: **{role_key}**\nBotni qayta ishga tushiring: /start"
                    )
                except: pass
            else:
                await callback.answer("Foydalanuvchi topilmadi!", show_alert=True)
                
    except Exception as e:
        logging.error(f"Set role error: {e}")
        await callback.answer("Xatolik!")