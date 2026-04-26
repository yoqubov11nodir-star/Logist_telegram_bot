from aiogram.fsm.state import StatesGroup, State


class LogistSteps(StatesGroup):
    waiting_for_invoice = State()

    edit_select_field     = State()
    edit_point_a_name     = State()
    edit_point_a_location = State()
    edit_point_b_name     = State()
    edit_point_b_location = State()
    edit_cargo            = State()
    edit_sale_price       = State()
    edit_cost_price       = State()
    edit_client_phone     = State()
    edit_client_name      = State()
