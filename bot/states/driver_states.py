from aiogram.fsm.state import State, StatesGroup


class DriverSteps(StatesGroup):
    waiting_for_media      = State()   # A nuqta yoki tushirish mediasi
    waiting_for_b_media    = State()   # B nuqtaga kelish mediasi
    waiting_for_location   = State()   # Yo'lga chiqish / mijoz so'rovi lokatsiyasi
    waiting_for_first_name = State()   # Ism kiritish (alohida)
    waiting_for_last_name  = State()   # Familya kiritish (alohida)
    waiting_for_card       = State()   # Karta raqami kiritish
