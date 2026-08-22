import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

import database as db
from background import background_loop, check_deadlines
from config import (
    BOT_TOKEN, WEBHOOK_URL, WEBHOOK_PATH, WEBHOOK_SECRET,
    WEB_SERVER_HOST, WEB_SERVER_PORT,
)
from handlers import registration, menu, room, moderation

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


async def on_startup(bot: Bot):
    await db.init_schema()
    if WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL, secret_token=WEBHOOK_SECRET, drop_pending_updates=True)
        log.info("Webhook установлен: %s", WEBHOOK_URL)
    else:
        log.warning("WEBHOOK_HOST не задан — бот не сможет принимать апдейты в этом режиме.")

    # догоняем дедлайны, которые могли истечь, пока сервис спал
    await check_deadlines(bot)
    asyncio.create_task(background_loop(bot))


async def on_shutdown(bot: Bot):
    # НЕ удаляем вебхук здесь: при передеплое старый и новый процесс какое-то
    # время сосуществуют, и удаление вебхука из старого процесса стирало бы
    # вебхук, только что установленный новым. Просто закрываем соединение с БД.
    await db.close_client()


async def healthcheck(request: web.Request):
    # этот же эндпоинт пингует UptimeRobot, чтобы бот не засыпал днём
    return web.Response(text="ok")


def create_app() -> web.Application:
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    dp.include_router(registration.router)
    dp.include_router(menu.router)
    dp.include_router(room.router)
    dp.include_router(moderation.router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/", healthcheck)
    app.router.add_get("/healthz", healthcheck)

    webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET)
    webhook_handler.register(app, path=WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host=WEB_SERVER_HOST, port=WEB_SERVER_PORT)
