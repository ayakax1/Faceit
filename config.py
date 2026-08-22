import os
from dotenv import load_dotenv

load_dotenv()

# --- Обязательные переменные окружения (задаются на Render) ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # ваш числовой Telegram ID (не @username)
BOT_USERNAME = os.getenv("BOT_USERNAME", "BSFaceit_bot")

TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "")  # libsql://xxx.turso.io
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")

WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "")  # https://your-app.onrender.com
WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "faceit-secret")
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}" if WEBHOOK_HOST else ""

WEB_SERVER_HOST = "0.0.0.0"
WEB_SERVER_PORT = int(os.getenv("PORT", "10000"))  # Render сам подставляет PORT

# --- Игровые константы (правьте под себя) ---
START_ELO = 100
READY_TIMEOUT_SECONDS = 5 * 60       # 5 минут на подтверждение готовности
SCREENSHOT_TIMEOUT_SECONDS = 60 * 60  # 1 час на присылку скринов лидером
ELO_PENALTY = 30
BAN_DAYS = 14
ROOM_SIZE = 8
MAPS = ["Inferno", "Mirage", "Compact", "Dust", "Office"]
KILLS_TO_WIN = 50
ROUNDS = 3

BACKGROUND_CHECK_INTERVAL = 30  # сек, как часто фоновая задача проверяет дедлайны

# ELO -> Faceit LVL (проверяется от большего к меньшему)
LEVEL_THRESHOLDS = [
    (4000, 10),
    (3550, 9),
    (3100, 8),
    (2650, 7),
    (2250, 6),
    (1825, 5),
    (1350, 4),
    (1000, 3),
    (500, 2),
    (100, 1),
]
