"""Telegram bot in webhook mode.

There is deliberately no polling code path: with the webhook set, any other
process that tries ``getUpdates`` with this token gets 409 and the live bot
keeps receiving everything (one token = one consumer).
"""

from __future__ import annotations

import hashlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from synthcut_core.db import make_async_engine, make_async_sessionmaker
from synthcut_core.redis import make_async_redis
from synthcut_core.settings import Settings, get_settings
from synthcut_telemetry import setup_logging

from .handlers.commands import router as commands_router
from .keyboards.web_app import web_app_available

log = logging.getLogger("synthcut.bot")

COMMANDS = [
    BotCommand(command="start", description="SynthCut'ni ochish"),
    BotCommand(command="new", description="Yangi loyiha: /new nom"),
    BotCommand(command="projects", description="Loyihalar ro'yxati"),
    BotCommand(command="status", description="Oxirgi loyiha holati"),
    BotCommand(command="help", description="Yordam"),
]


def webhook_path(settings: Settings) -> str:
    secret = settings.telegram_webhook_secret.get_secret_value()
    return "/telegram/webhook/" + hashlib.sha256(secret.encode()).hexdigest()[:24]


def build_app(settings: Settings) -> web.Application:
    secret = settings.telegram_webhook_secret.get_secret_value()
    if len(secret) < 24:
        raise RuntimeError("TELEGRAM_WEBHOOK_SECRET must be at least 24 characters")
    bot = Bot(
        settings.telegram_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    engine = make_async_engine(settings.database_url, pool_size=3)
    redis_client = make_async_redis(settings.redis_url)
    dp = Dispatcher(settings=settings, sessionmaker=make_async_sessionmaker(engine), redis=redis_client)
    dp.include_router(commands_router)
    path = webhook_path(settings)

    async def on_startup(bot: Bot) -> None:
        url = settings.public_base_url.rstrip("/") + path
        await bot.set_webhook(
            url,
            secret_token=secret,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=False,
        )
        await bot.set_my_commands(COMMANDS)
        if web_app_available(settings.mini_app_url):
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="SynthCut", web_app=WebAppInfo(url=settings.mini_app_url))
            )
        await bot.set_my_short_description("AI post-production: xom videodan tayyor montajgacha.")
        log.info("webhook set", extra={"url_host": settings.public_base_url})

    async def on_shutdown(bot: Bot) -> None:
        # The webhook stays registered on purpose: Telegram queues updates
        # while we restart instead of a poller anywhere grabbing them.
        await redis_client.aclose()
        await engine.dispose()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret, handle_in_background=True).register(
        app, path=path
    )

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    app.router.add_get("/telegram/health", health)
    setup_application(app, dp, bot=bot)
    return app


def main() -> None:  # pragma: no cover - container entry point
    settings = get_settings()
    setup_logging("bot", settings.log_level)
    web.run_app(build_app(settings), host="0.0.0.0", port=8080, access_log=None)  # noqa: S104


if __name__ == "__main__":  # pragma: no cover
    main()
