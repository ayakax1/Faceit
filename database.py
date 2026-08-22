"""
Слой доступа к базе данных (Turso / libSQL — облачный SQLite).
Всё, что боту нужно знать о хранении данных, находится здесь.
"""
import json
from datetime import datetime, timedelta
from typing import Optional

import libsql_client

from config import TURSO_DATABASE_URL, TURSO_AUTH_TOKEN, START_ELO

_client: Optional[libsql_client.Client] = None


def get_client() -> libsql_client.Client:
    global _client
    if _client is None:
        # используем HTTPS вместо WebSocket (libsql://) — надёжнее на бесплатных
        # хостингах вроде Render, где исходящий WebSocket иногда режется
        url = TURSO_DATABASE_URL
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]
        _client = libsql_client.create_client(
            url=url,
            auth_token=TURSO_AUTH_TOKEN,
        )
    return _client


async def close_client():
    global _client
    if _client is not None:
        await _client.close()
        _client = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    tg_id INTEGER PRIMARY KEY,
    tg_username TEXT,
    bs_id TEXT,
    bs_nickname TEXT,
    elo INTEGER DEFAULT 100,
    total_kills INTEGER DEFAULT 0,
    total_deaths INTEGER DEFAULT 0,
    total_headshots INTEGER DEFAULT 0,
    total_games INTEGER DEFAULT 0,
    verified INTEGER DEFAULT 0,
    banned_until TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pending_verifications (
    tg_id INTEGER PRIMARY KEY,
    bs_id TEXT,
    bs_nickname TEXT,
    tg_username TEXT,
    requested_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rooms (
    room_id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT DEFAULT 'waiting',
    leader_tg_id INTEGER,
    map TEXT,
    team_red TEXT,
    team_blue TEXT,
    ready_deadline TEXT,
    screenshot_deadline TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS room_players (
    room_id INTEGER,
    tg_id INTEGER,
    ready INTEGER DEFAULT 0,
    joined_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (room_id, tg_id)
);

CREATE TABLE IF NOT EXISTS pending_moderation (
    mod_id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER,
    leader_tg_id INTEGER,
    photo_file_ids TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now'))
);
"""


async def init_schema():
    client = get_client()
    for statement in filter(None, (s.strip() for s in SCHEMA.split(";"))):
        await client.execute(statement)

    # миграция для баз, созданных до добавления настроек комнаты
    for alter in (
        "ALTER TABLE rooms ADD COLUMN room_name TEXT",
        "ALTER TABLE rooms ADD COLUMN region TEXT",
        "ALTER TABLE rooms ADD COLUMN room_size INTEGER DEFAULT 8",
    ):
        try:
            await client.execute(alter)
        except Exception:
            pass  # колонка уже существует — это нормально


# ---------------------------------------------------------------- players --

async def get_player(tg_id: int):
    client = get_client()
    rs = await client.execute("SELECT * FROM players WHERE tg_id = ?", [tg_id])
    return rs.rows[0] if rs.rows else None


async def is_registered(tg_id: int) -> bool:
    player = await get_player(tg_id)
    return player is not None and player["verified"] == 1


async def is_banned(tg_id: int) -> Optional[str]:
    """Возвращает дату окончания бана, если игрок ещё забанен, иначе None."""
    player = await get_player(tg_id)
    if player is None or player["banned_until"] is None:
        return None
    banned_until = datetime.fromisoformat(player["banned_until"])
    if banned_until > datetime.utcnow():
        return player["banned_until"]
    return None


async def create_pending_verification(tg_id: int, bs_id: str, bs_nickname: str, tg_username: str):
    client = get_client()
    await client.execute(
        """INSERT INTO pending_verifications (tg_id, bs_id, bs_nickname, tg_username)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(tg_id) DO UPDATE SET
             bs_id=excluded.bs_id, bs_nickname=excluded.bs_nickname,
             tg_username=excluded.tg_username, requested_at=datetime('now')""",
        [tg_id, bs_id, bs_nickname, tg_username],
    )


async def get_pending_verification(tg_id: int):
    client = get_client()
    rs = await client.execute("SELECT * FROM pending_verifications WHERE tg_id = ?", [tg_id])
    return rs.rows[0] if rs.rows else None


async def approve_verification(tg_id: int):
    pending = await get_pending_verification(tg_id)
    if pending is None:
        return
    client = get_client()
    await client.execute(
        """INSERT INTO players (tg_id, tg_username, bs_id, bs_nickname, elo, verified)
           VALUES (?, ?, ?, ?, ?, 1)
           ON CONFLICT(tg_id) DO UPDATE SET
             tg_username=excluded.tg_username, bs_id=excluded.bs_id,
             bs_nickname=excluded.bs_nickname, verified=1""",
        [tg_id, pending["tg_username"], pending["bs_id"], pending["bs_nickname"], START_ELO],
    )
    await client.execute("DELETE FROM pending_verifications WHERE tg_id = ?", [tg_id])


async def ban_player(tg_id: int, days: int):
    banned_until = (datetime.utcnow() + timedelta(days=days)).isoformat()
    client = get_client()
    # если игрока ещё нет в players (забанили на этапе верификации) - создаём запись
    await client.execute(
        """INSERT INTO players (tg_id, banned_until, verified) VALUES (?, ?, 0)
           ON CONFLICT(tg_id) DO UPDATE SET banned_until=excluded.banned_until""",
        [tg_id, banned_until],
    )
    await client.execute("DELETE FROM pending_verifications WHERE tg_id = ?", [tg_id])


async def adjust_elo(tg_id: int, delta: int):
    client = get_client()
    await client.execute(
        "UPDATE players SET elo = MAX(0, elo + ?) WHERE tg_id = ?", [delta, tg_id]
    )


async def set_player_elo(tg_id: int, elo: int):
    client = get_client()
    await client.execute("UPDATE players SET elo = ? WHERE tg_id = ?", [elo, tg_id])


async def add_match_stats(tg_id: int, kills: int, deaths: int, headshots: int):
    client = get_client()
    await client.execute(
        """UPDATE players SET
             total_kills = total_kills + ?,
             total_deaths = total_deaths + ?,
             total_headshots = total_headshots + ?,
             total_games = total_games + 1
           WHERE tg_id = ?""",
        [kills, deaths, headshots, tg_id],
    )


# ------------------------------------------------------------------ rooms --

async def create_room(room_name: str, region: str, room_size: int) -> int:
    client = get_client()
    rs = await client.execute(
        "INSERT INTO rooms (room_name, region, room_size) VALUES (?, ?, ?) RETURNING room_id",
        [room_name, region, room_size],
    )
    return rs.rows[0]["room_id"]


async def get_active_room_for_player(tg_id: int):
    """Возвращает комнату, в которой игрок уже участвует и она ещё не завершена/распущена."""
    client = get_client()
    rs = await client.execute(
        """SELECT rooms.* FROM rooms
           JOIN room_players ON room_players.room_id = rooms.room_id
           WHERE room_players.tg_id = ?
             AND rooms.status NOT IN ('completed', 'dissolved')
           ORDER BY rooms.created_at DESC LIMIT 1""",
        [tg_id],
    )
    return rs.rows[0] if rs.rows else None


async def get_open_rooms_with_players():
    """Список открытых (ожидающих игроков) комнат вместе с никами уже присоединившихся."""
    client = get_client()
    rooms_rs = await client.execute(
        "SELECT * FROM rooms WHERE status = 'waiting' ORDER BY created_at DESC LIMIT 15"
    )
    result = []
    for room in rooms_rs.rows:
        players_rs = await client.execute(
            """SELECT players.bs_nickname FROM room_players
               JOIN players ON players.tg_id = room_players.tg_id
               WHERE room_players.room_id = ?
               ORDER BY room_players.joined_at""",
            [room["room_id"]],
        )
        nicknames = [p["bs_nickname"] for p in players_rs.rows]
        result.append({"room": room, "nicknames": nicknames})
    return result


async def get_room(room_id: int):
    client = get_client()
    rs = await client.execute("SELECT * FROM rooms WHERE room_id = ?", [room_id])
    return rs.rows[0] if rs.rows else None


async def get_room_players(room_id: int):
    client = get_client()
    rs = await client.execute(
        "SELECT * FROM room_players WHERE room_id = ? ORDER BY joined_at", [room_id]
    )
    return rs.rows


async def add_player_to_room(room_id: int, tg_id: int) -> bool:
    """Возвращает False, если комната закрыта/заполнена. Не проверяет, что игрок уже
    в другой активной комнате — это делает вызывающий код через get_active_room_for_player."""
    client = get_client()
    room = await get_room(room_id)
    if room is None or room["status"] != "waiting":
        return False
    existing = await get_room_players(room_id)
    if any(p["tg_id"] == tg_id for p in existing):
        return True
    room_size = room["room_size"] or 8
    if len(existing) >= room_size:
        return False
    await client.execute(
        "INSERT OR IGNORE INTO room_players (room_id, tg_id) VALUES (?, ?)", [room_id, tg_id]
    )
    return True


async def set_room_status(room_id: int, status: str):
    client = get_client()
    await client.execute("UPDATE rooms SET status = ? WHERE room_id = ?", [status, room_id])


async def set_ready_deadline(room_id: int, deadline: datetime):
    client = get_client()
    await client.execute(
        "UPDATE rooms SET ready_deadline = ? WHERE room_id = ?", [deadline.isoformat(), room_id]
    )


async def mark_player_ready(room_id: int, tg_id: int):
    client = get_client()
    await client.execute(
        "UPDATE room_players SET ready = 1 WHERE room_id = ? AND tg_id = ?", [room_id, tg_id]
    )


async def finalize_room(room_id: int, leader_id: int, game_map: str, team_red: list, team_blue: list):
    client = get_client()
    await client.execute(
        """UPDATE rooms SET status='in_progress', leader_tg_id=?, map=?,
             team_red=?, team_blue=? WHERE room_id=?""",
        [leader_id, game_map, json.dumps(team_red), json.dumps(team_blue), room_id],
    )


async def set_screenshot_deadline(room_id: int, deadline: datetime):
    client = get_client()
    await client.execute(
        "UPDATE rooms SET screenshot_deadline = ? WHERE room_id = ?",
        [deadline.isoformat(), room_id],
    )


async def get_rooms_by_status(status: str):
    client = get_client()
    rs = await client.execute("SELECT * FROM rooms WHERE status = ?", [status])
    return rs.rows


# ------------------------------------------------------------- moderation --

async def create_moderation_entry(room_id: int, leader_tg_id: int, file_ids: list) -> int:
    client = get_client()
    rs = await client.execute(
        """INSERT INTO pending_moderation (room_id, leader_tg_id, photo_file_ids)
           VALUES (?, ?, ?) RETURNING mod_id""",
        [room_id, leader_tg_id, json.dumps(file_ids)],
    )
    return rs.rows[0]["mod_id"]


async def get_moderation_entry(mod_id: int):
    client = get_client()
    rs = await client.execute("SELECT * FROM pending_moderation WHERE mod_id = ?", [mod_id])
    return rs.rows[0] if rs.rows else None


async def close_moderation_entry(mod_id: int, status: str):
    client = get_client()
    await client.execute(
        "UPDATE pending_moderation SET status = ? WHERE mod_id = ?", [status, mod_id]
    )
