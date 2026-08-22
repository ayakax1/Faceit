import random

from config import LEVEL_THRESHOLDS, BOT_USERNAME, MAPS


def elo_to_level(elo: int) -> int:
    for threshold, level in LEVEL_THRESHOLDS:
        if elo >= threshold:
            return level
    return 1


def room_link(room_id: int) -> str:
    """Настоящая рабочая Telegram deep-ссылка (открывает бота и сразу подключает к комнате)."""
    return f"https://t.me/{BOT_USERNAME}?start=room_{room_id}"


def assign_teams_and_map(player_ids: list[int]):
    """Случайно выбирает лидера, карту и делит игроков пополам на 2 команды."""
    shuffled = player_ids[:]
    random.shuffle(shuffled)
    leader_id = random.choice(player_ids)
    game_map = random.choice(MAPS)
    half = len(shuffled) // 2
    team_red = shuffled[:half]
    team_blue = shuffled[half:]
    return leader_id, game_map, team_red, team_blue


def kd_ratio(kills: int, deaths: int) -> float:
    if deaths == 0:
        return float(kills)
    return round(kills / deaths, 2)


def hk_ratio(headshots: int, kills: int) -> float:
    if kills == 0:
        return 0.0
    return round(headshots / kills * 100, 1)
