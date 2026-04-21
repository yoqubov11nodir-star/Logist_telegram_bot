from aiogram.fsm.state import State, StatesGroup


class OrderCreation(StatesGroup):
    waiting_for_client_name  = State()
    waiting_for_client_phone = State()
    waiting_for_cargo_desc   = State()
    waiting_for_point_a      = State()
    waiting_for_point_b      = State()
    waiting_for_sale_price   = State()
    waiting_for_cost_price   = State()
