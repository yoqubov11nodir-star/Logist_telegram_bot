from aiogram.fsm.state import State, StatesGroup


class OrderCreation(StatesGroup):
    waiting_for_client_name     = State()
    waiting_for_client_phone    = State()
    waiting_for_cargo_desc      = State()

    # A nuqta: avval matn nomi, keyin location
    waiting_for_point_a_name    = State()
    waiting_for_point_a_location= State()

    # B nuqta: avval matn nomi, keyin location
    waiting_for_point_b_name    = State()
    waiting_for_point_b_location= State()

    waiting_for_sale_price      = State()
    waiting_for_cost_price      = State()
