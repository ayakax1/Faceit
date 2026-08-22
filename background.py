import asyncio
import logging
from datetime import datetime

from aiogram import Bot

import database as db
from config import ELO_PENALTY, BACKGROUND_CHECK_INTERVAL

log = logging.getLogger(__name__)


async def check_deadlines(bot: Bot):
    """Разово проверяет все просроченные комнаты. Вызывается в цикле и один раз при старте
    (чтобы догнать пропущенное, если процесс проспал часть времени)."""
    await _check_ready_deadlines(bot)
    await _check_screenshot_deadlines(bot)


async def _check_ready_deadlines(bot: Bot):
    rooms = await db.get_rooms_by_status("ready_check")
    now = datetime.utcnow()
    for room in rooms:
        if not room["ready_deadline"]:
            continue
        deadline = datetime.fromisoformat(room["ready_deadline"])
        if now < deadline:
            continue

        players = await db.get_room_players(room["room_id"])
        not_ready = [p["tg_id"] for p in players if p["ready"] != 1]
        if not not_ready:
            continue  # на всякий случай, вдруг все успели

        await db.set_room_status(room["room_id"], "dissolved")
        for pid in not_ready:
            await db.adjust_elo(pid, -ELO_PENALTY)
        for p in players:
            try:
                if p["tg_id"] in not_ready:
                    await bot.send_message(
                        p["tg_id"],
                        f"⏱ Комната #{room['room_id']} распущена — вы не подтвердили готовность вовремя. "
                        f"-{ELO_PENALTY} ELO.",
                    )
                else:
                    await bot.send_message(
                        p["tg_id"],
                        f"⏱ Комната #{room['room_id']} распущена — не все подтвердили готовность вовремя. "
                        "Попробуйте создать/зайти в новую комнату.",
                    )
            except Exception:
                log.exception("Не удалось уведомить игрока %s", p["tg_id"])


async def _check_screenshot_deadlines(bot: Bot):
    rooms = await db.get_rooms_by_status("in_progress")
    now = datetime.utcnow()
    for room in rooms:
        if not room["screenshot_deadline"]:
            continue
        deadline = datetime.fromisoformat(room["screenshot_deadline"])
        if now < deadline:
            continue

        await db.adjust_elo(room["leader_tg_id"], -ELO_PENALTY)
        await db.set_room_status(room["room_id"], "in_progress_penalized")
        try:
            await bot.send_message(
                room["leader_tg_id"],
                f"⏱ Вы не прислали скриншоты матча в течение часа. -{ELO_PENALTY} ELO. "
                "Скриншоты всё ещё можно прислать — они уйдут на модерацию.",
            )
        except Exception:
            log.exception("Не удалось уведомить лидера %s", room["leader_tg_id"])


async def background_loop(bot: Bot):
    while True:
        try:
            await check_deadlines(bot)
        except Exception:
            log.exception("Ошибка в фоновой проверке дедлайнов")
        await asyncio.sleep(BACKGROUND_CHECK_INTERVAL)
