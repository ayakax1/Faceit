from aiogram import Router, F
from aiogram.types import CallbackQuery, FSInputFile

import database as db
from utils import elo_to_level, kd_ratio, hk_ratio

router = Router()

BANNER_PROFILE = "assets/banner_profile.png"


@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    player = await db.get_player(callback.from_user.id)
    if player is None or player["verified"] != 1:
        await callback.answer("Вы ещё не прошли верификацию.", show_alert=True)
        return

    await callback.message.answer_photo(FSInputFile(BANNER_PROFILE), caption="Профиль")

    level = elo_to_level(player["elo"])
    kd = kd_ratio(player["total_kills"], player["total_deaths"])
    hk = hk_ratio(player["total_headshots"], player["total_kills"])

    text = (
        f"<b>BS nickname:</b> {player['bs_nickname']}\n"
        f"<b>BS ID:</b> {player['bs_id']}\n\n"
        f"<b>ELO:</b> {player['elo']}\n"
        f"<b>Faceit LVL:</b> {level}\n\n"
        f"<b>Faceit K/D:</b> {kd}\n"
        f"<b>Faceit H/K:</b> {hk}%\n"
        f"<b>Всего сыграно игр:</b> {player['total_games']}"
    )
    await callback.message.answer(text)
    await callback.answer()
