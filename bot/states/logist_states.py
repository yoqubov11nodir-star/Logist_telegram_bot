from aiogram.fsm.state import StatesGroup, State

class LogistSteps(StatesGroup):
    waiting_for_invoice = State() # Didox PDF fakturasini kutish
