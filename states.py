from aiogram.fsm.state import State, StatesGroup


class Registration(StatesGroup):
    waiting_bs_id = State()
    waiting_bs_nickname = State()
    waiting_tg_user = State()


class RoomCreation(StatesGroup):
    waiting_size = State()
    waiting_name = State()
    waiting_region = State()


class ModerationInput(StatesGroup):
    # админ вручную вводит эло/КД/HK по каждому игроку матча
    waiting_elo = State()
    waiting_kills = State()
    waiting_deaths = State()
    waiting_headshots = State()
