from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_ID


def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🎮 Создать комнату", callback_data="create_room")
    b.button(text="🖥 Сервера", callback_data="servers_list")
    b.button(text="👤 Профиль", callback_data="profile")
    if is_admin:
        b.button(text="🛡 Модерация", callback_data="admin_panel")
    b.adjust(1)
    return b.as_markup()


def room_size_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for size in (2, 4, 6, 8, 10):
        b.button(text=str(size), callback_data=f"room_size:{size}")
    b.adjust(5)
    return b.as_markup()


def verification_review_kb(tg_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Пропустить", callback_data=f"verify_ok:{tg_id}")
    b.button(text="🚫 Бан на 14 дней", callback_data=f"verify_ban:{tg_id}")
    b.adjust(2)
    return b.as_markup()


def ready_kb(room_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Я готов", callback_data=f"ready:{room_id}")
    return b.as_markup()


def moderation_decision_kb(mod_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Похоже на игру — оценить матч", callback_data=f"mod_accept:{mod_id}")
    b.button(text="❌ Отклонить", callback_data=f"mod_reject:{mod_id}")
    b.adjust(1)
    return b.as_markup()


def no_show_kb(room_id: int, player_ids: list[int]) -> InlineKeyboardMarkup:
    """Для лидера: отметить, кто не пришёл на игру."""
    b = InlineKeyboardBuilder()
    for pid in player_ids:
        b.button(text=f"Не пришёл: {pid}", callback_data=f"noshow:{room_id}:{pid}")
    b.adjust(1)
    return b.as_markup()
