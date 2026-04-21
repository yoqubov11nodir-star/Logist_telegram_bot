from aiogram.fsm.state import StatesGroup, State


class CashierSteps(StatesGroup):
    waiting_for_receipt = State()
