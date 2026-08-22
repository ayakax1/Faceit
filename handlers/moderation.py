import json

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database as db
from config import ADMIN_ID
from states import ModerationInput

router = Router()


@router.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Только для администратора.", show_alert=True)
        return
    rooms = await db.get_rooms_by_status("awaiting_moderation")
    await callback.message.answer(
        f"🛡 Комнат ожидает модерации: {len(rooms)}.\n"
        "Скрины приходят сюда автоматически, когда лидер их отправляет."
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mod_reject:"))
async def mod_reject(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Только для администратора.", show_alert=True)
        return
    mod_id = int(callback.data.split(":")[1])
    entry = await db.get_moderation_entry(mod_id)
    if entry is None:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return

    await db.close_moderation_entry(mod_id, "rejected")
    await db.set_room_status(entry["room_id"], "in_progress")
    await bot.send_message(
        entry["leader_tg_id"],
        "❌ Ваши скриншоты отклонены модератором. Пришлите корректные скрины ещё раз.",
    )
    await callback.message.edit_text(callback.message.text if callback.message.text else "", reply_markup=None)
    await callback.answer("Отклонено.")


@router.callback_query(F.data.startswith("mod_accept:"))
async def mod_accept(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Только для администратора.", show_alert=True)
        return
    mod_id = int(callback.data.split(":")[1])
    entry = await db.get_moderation_entry(mod_id)
    if entry is None:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return

    room_players = await db.get_room_players(entry["room_id"])
    player_ids = [p["tg_id"] for p in room_players]

    await state.set_state(ModerationInput.waiting_elo)
    await state.update_data(
        mod_id=mod_id,
        room_id=entry["room_id"],
        player_ids=player_ids,
        current_index=0,
        results={},
    )
    await callback.message.answer(
        f"Оценка матча, комната #{entry['room_id']}.\n\n"
        f"Игрок 1/{len(player_ids)}: <code>{player_ids[0]}</code>\n"
        "Сколько ELO ему начислить? (число, можно отрицательное)"
    )
    await callback.answer()


def _current_player_prompt(data: dict) -> str:
    idx = data["current_index"]
    pid = data["player_ids"][idx]
    total = len(data["player_ids"])
    return f"Игрок {idx + 1}/{total}: <code>{pid}</code>"


@router.message(ModerationInput.waiting_elo)
async def input_elo(message: Message, state: FSMContext):
    try:
        elo_delta = int(message.text.strip())
    except ValueError:
        await message.answer("Нужно целое число. Попробуйте ещё раз.")
        return
    data = await state.get_data()
    idx = data["current_index"]
    pid = data["player_ids"][idx]
    results = data["results"]
    results[str(pid)] = {"elo": elo_delta}
    await state.update_data(results=results)
    await state.set_state(ModerationInput.waiting_kills)
    await message.answer(f"{_current_player_prompt(data)}\nСколько у него убийств (черепков) за матч?")


@router.message(ModerationInput.waiting_kills)
async def input_kills(message: Message, state: FSMContext):
    try:
        kills = int(message.text.strip())
    except ValueError:
        await message.answer("Нужно целое число. Попробуйте ещё раз.")
        return
    data = await state.get_data()
    idx = data["current_index"]
    pid = data["player_ids"][idx]
    results = data["results"]
    results[str(pid)]["kills"] = kills
    await state.update_data(results=results)
    await state.set_state(ModerationInput.waiting_deaths)
    await message.answer(f"{_current_player_prompt(data)}\nСколько смертей (могил)?")


@router.message(ModerationInput.waiting_deaths)
async def input_deaths(message: Message, state: FSMContext):
    try:
        deaths = int(message.text.strip())
    except ValueError:
        await message.answer("Нужно целое число. Попробуйте ещё раз.")
        return
    data = await state.get_data()
    idx = data["current_index"]
    pid = data["player_ids"][idx]
    results = data["results"]
    results[str(pid)]["deaths"] = deaths
    await state.update_data(results=results)
    await state.set_state(ModerationInput.waiting_headshots)
    await message.answer(f"{_current_player_prompt(data)}\nСколько из убийств в голову (хедшотов)?")


@router.message(ModerationInput.waiting_headshots)
async def input_headshots(message: Message, state: FSMContext, bot: Bot):
    try:
        headshots = int(message.text.strip())
    except ValueError:
        await message.answer("Нужно целое число. Попробуйте ещё раз.")
        return
    data = await state.get_data()
    idx = data["current_index"]
    pid = data["player_ids"][idx]
    results = data["results"]
    results[str(pid)]["headshots"] = headshots
    await state.update_data(results=results)

    next_index = idx + 1
    if next_index < len(data["player_ids"]):
        await state.update_data(current_index=next_index)
        await state.set_state(ModerationInput.waiting_elo)
        new_data = await state.get_data()
        await message.answer(f"{_current_player_prompt(new_data)}\nСколько ELO ему начислить?")
        return

    # все игроки оценены — применяем результаты
    for pid_str, r in results.items():
        pid = int(pid_str)
        await db.adjust_elo(pid, r["elo"])
        await db.add_match_stats(pid, r["kills"], r["deaths"], r["headshots"])
        try:
            await bot.send_message(
                pid,
                f"📊 Матч оценён администратором.\n"
                f"ELO: {'+' if r['elo'] >= 0 else ''}{r['elo']}\n"
                f"Убийств: {r['kills']}, смертей: {r['deaths']}, хедшотов: {r['headshots']}",
            )
        except Exception:
            pass

    await db.close_moderation_entry(data["mod_id"], "accepted")
    await db.set_room_status(data["room_id"], "completed")
    await state.clear()
    await message.answer(f"✅ Готово! Комната #{data['room_id']} закрыта, статистика обновлена.")
