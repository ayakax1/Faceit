from datetime import datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, FSInputFile
from aiogram.fsm.context import FSMContext

import database as db
import keyboards as kb
from config import (
    ADMIN_ID, READY_TIMEOUT_SECONDS, SCREENSHOT_TIMEOUT_SECONDS,
    ELO_PENALTY, KILLS_TO_WIN, ROUNDS,
)
from states import RoomCreation
from utils import room_link, assign_teams_and_map

router = Router()

BANNER_CREATE_ROOM = "assets/banner_create_room.png"
BANNER_SERVERS = "assets/banner_servers.png"

# буфер скриншотов от лидера, пока он не нажмёт "отправить на модерацию"
# { leader_tg_id: {"room_id": int, "file_ids": [str, ...]} }
pending_screenshots: dict[int, dict] = {}


# ------------------------------------------------------------- создание ----

@router.callback_query(F.data == "create_room")
async def create_room_start(callback: CallbackQuery, state: FSMContext):
    player = await db.get_player(callback.from_user.id)
    if player is None or player["verified"] != 1:
        await callback.answer("Сначала пройдите верификацию (/start).", show_alert=True)
        return

    # фикс бага: нельзя создать новую комнату, уже находясь в активной
    active_room = await db.get_active_room_for_player(callback.from_user.id)
    if active_room is not None:
        await callback.answer(
            f"Вы уже участвуете в комнате #{active_room['room_id']} — сначала завершите её.",
            show_alert=True,
        )
        return

    await state.set_state(RoomCreation.waiting_size)
    await callback.message.answer_photo(
        FSInputFile(BANNER_CREATE_ROOM), caption="Создание комнаты"
    )
    await callback.message.answer(
        "На сколько игроков создать комнату?", reply_markup=kb.room_size_kb()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("room_size:"), RoomCreation.waiting_size)
async def create_room_size(callback: CallbackQuery, state: FSMContext):
    size = int(callback.data.split(":")[1])
    await state.update_data(room_size=size)
    await state.set_state(RoomCreation.waiting_name)
    await callback.message.answer("Введите название комнаты (например: Вечерний кубок).")
    await callback.answer()


@router.message(RoomCreation.waiting_name)
async def create_room_name(message: Message, state: FSMContext):
    await state.update_data(room_name=message.text.strip())
    await state.set_state(RoomCreation.waiting_region)
    await message.answer("Укажите регион сервера (например: Нидерланды).")


@router.message(RoomCreation.waiting_region)
async def create_room_region(message: Message, state: FSMContext):
    data = await state.get_data()
    region = message.text.strip()
    room_size = data["room_size"]
    room_name = data["room_name"]
    await state.clear()

    room_id = await db.create_room(room_name=room_name, region=region, room_size=room_size)
    await db.add_player_to_room(room_id, message.from_user.id)

    link = room_link(room_id)
    await message.answer(
        f"Комната создана!\n\n"
        f"📛 Название: {room_name}\n"
        f"🌍 Регион: {region}\n"
        f"👥 Размер: {room_size}\n\n"
        f"Ссылка для игроков:\n{link}\n\n"
        f"Ждём ещё {room_size - 1} игрока(ов). Как только наберётся {room_size} — "
        "ссылка закроется и начнётся подтверждение готовности."
    )


async def handle_room_join_by_id(message: Message, room_id: int):
    room = await db.get_room(room_id)
    if room is None:
        await message.answer("Такой комнаты не существует.")
        return
    if room["status"] != "waiting":
        await message.answer("Эта комната уже закрыта (набор завершён или комната распущена).")
        return

    # фикс бага: нельзя вступить в другую комнату, уже находясь в активной
    active_room = await db.get_active_room_for_player(message.from_user.id)
    if active_room is not None and active_room["room_id"] != room_id:
        await message.answer(
            f"Вы уже участвуете в комнате #{active_room['room_id']} — сначала завершите её."
        )
        return

    ok = await db.add_player_to_room(room_id, message.from_user.id)
    if not ok:
        await message.answer("Не удалось присоединиться — комната уже заполнена или закрыта.")
        return

    players = await db.get_room_players(room_id)
    count = len(players)
    room_size = room["room_size"] or 8
    await message.answer(f"Вы в комнате #{room_id}. Игроков: {count}/{room_size}.")

    if count >= room_size:
        await _start_ready_check(message.bot, room_id, players)


# ------------------------------------------------------------- сервера ----

@router.callback_query(F.data == "servers_list")
async def servers_list(callback: CallbackQuery):
    await callback.message.answer_photo(FSInputFile(BANNER_SERVERS), caption="Сервера")

    open_rooms = await db.get_open_rooms_with_players()
    if not open_rooms:
        await callback.message.answer("Сейчас нет открытых комнат. Создайте свою!")
        await callback.answer()
        return

    lines = []
    for entry in open_rooms:
        room = entry["room"]
        nicknames = entry["nicknames"]
        size = room["room_size"] or 8
        players_text = ", ".join(nicknames) if nicknames else "пока никого"
        lines.append(
            f"#{room['room_id']} «{room['room_name'] or 'без названия'}» "
            f"— {room['region'] or '—'} — {len(nicknames)}/{size}\n"
            f"Игроки: {players_text}\n"
            f"{room_link(room['room_id'])}"
        )
    await callback.message.answer("\n\n".join(lines))
    await callback.answer()


async def _start_ready_check(bot: Bot, room_id: int, players):
    await db.set_room_status(room_id, "ready_check")
    deadline = datetime.utcnow() + timedelta(seconds=READY_TIMEOUT_SECONDS)
    await db.set_ready_deadline(room_id, deadline)
    room_size = len(players)

    for p in players:
        try:
            await bot.send_message(
                p["tg_id"],
                f"Комната #{room_id} набрана полностью ({room_size}/{room_size})!\n\n"
                "Подтвердите, что вы на месте и готовы играть. "
                "На это даётся 5 минут — если не успеете, комната распустится, "
                f"а вам будет начислено -{ELO_PENALTY} ELO.",
                reply_markup=kb.ready_kb(room_id),
            )
        except Exception:
            pass


# --------------------------------------------------------- готовность ----

@router.callback_query(F.data.startswith("ready:"))
async def player_ready(callback: CallbackQuery, bot: Bot):
    room_id = int(callback.data.split(":")[1])
    room = await db.get_room(room_id)
    if room is None or room["status"] != "ready_check":
        await callback.answer("Этот запрос на готовность больше не активен.", show_alert=True)
        return

    await db.mark_player_ready(room_id, callback.from_user.id)
    await callback.message.edit_text(callback.message.text + "\n\n✅ Готовность подтверждена.")
    await callback.answer()

    players = await db.get_room_players(room_id)
    if all(p["ready"] == 1 for p in players):
        await _finalize_room(bot, room_id, players)


async def _finalize_room(bot: Bot, room_id: int, players):
    player_ids = [p["tg_id"] for p in players]
    leader_id, game_map, team_red, team_blue = assign_teams_and_map(player_ids)
    await db.finalize_room(room_id, leader_id, game_map, team_red, team_blue)

    deadline = datetime.utcnow() + timedelta(seconds=SCREENSHOT_TIMEOUT_SECONDS)
    await db.set_screenshot_deadline(room_id, deadline)

    ids_text = ", ".join(str(pid) for pid in player_ids)
    team_red_text = ", ".join(str(pid) for pid in team_red)
    team_blue_text = ", ".join(str(pid) for pid in team_blue)

    common_text = (
        f"🎲 Все готовы! Комната #{room_id}\n\n"
        f"🗺 Карта: <b>{game_map}</b>\n"
        f"🔴 Команда красных: {team_red_text}\n"
        f"🔵 Команда синих: {team_blue_text}\n\n"
        f"Игра ведётся строго {ROUNDS} раунда, цель — {KILLS_TO_WIN} убийств.\n"
        "Отправьте всем запросы в друзья в игре (после матча можно удалить)."
    )

    for pid in player_ids:
        try:
            text = common_text
            if pid == leader_id:
                text += (
                    "\n\n👑 <b>Вы выбраны лидером!</b> Создайте лобби, пригласите всех "
                    f"({ids_text}), настройте {ROUNDS} раунда и {KILLS_TO_WIN} убийств до победы.\n\n"
                    "После каждого раунда фотографируйте экран лобби и присылайте сюда, мне в бота. "
                    "У вас есть 1 час на присылку скриншотов — иначе -30 ELO."
                )
            await bot.send_message(pid, text)
        except Exception:
            pass


# --------------------------------------------------------- скриншоты ----

@router.message(F.photo)
async def collect_leader_screenshot(message: Message, bot: Bot):
    leader_id = message.from_user.id
    rooms = await db.get_rooms_by_status("in_progress") + await db.get_rooms_by_status("in_progress_penalized")
    room = next((r for r in rooms if r["leader_tg_id"] == leader_id), None)
    if room is None:
        return  # фото не по теме — игнорируем

    buf = pending_screenshots.setdefault(leader_id, {"room_id": room["room_id"], "file_ids": []})
    buf["file_ids"].append(message.photo[-1].file_id)

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    b = InlineKeyboardBuilder()
    b.button(text="📨 Отправить на модерацию", callback_data=f"submit_screens:{room['room_id']}")
    await message.answer(
        f"Скриншот принят ({len(buf['file_ids'])}). Пришлите остальные раунды, "
        "затем нажмите кнопку ниже.",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data.startswith("submit_screens:"))
async def submit_screens(callback: CallbackQuery, bot: Bot):
    leader_id = callback.from_user.id
    buf = pending_screenshots.get(leader_id)
    room_id = int(callback.data.split(":")[1])
    if not buf or buf["room_id"] != room_id or not buf["file_ids"]:
        await callback.answer("Сначала пришлите хотя бы один скриншот.", show_alert=True)
        return

    from aiogram.types import InputMediaPhoto

    mod_id = await db.create_moderation_entry(room_id, leader_id, buf["file_ids"])
    await db.set_room_status(room_id, "awaiting_moderation")

    media = [InputMediaPhoto(media=fid) for fid in buf["file_ids"]]
    media[0].caption = f"🕵️ Скрины на модерацию — комната #{room_id}, лидер {leader_id}"
    await bot.send_media_group(ADMIN_ID, media)
    await bot.send_message(ADMIN_ID, "Похоже ли это на игру Block Strike?", reply_markup=kb.moderation_decision_kb(mod_id))

    del pending_screenshots[leader_id]
    await callback.message.edit_text("Скрины отправлены администратору на модерацию. Ожидайте начисления ELO.")
    await callback.answer()
