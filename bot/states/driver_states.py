from aiogram.fsm.state import StatesGroup, State

class DriverSteps(StatesGroup):
    waiting_for_media = State() # Rasm va video kutish
    waiting_for_location = State() # Lokatsiya kutish
    waiting_for_card = State() # Karta raqami kutish
