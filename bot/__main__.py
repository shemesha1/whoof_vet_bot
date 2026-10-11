"""Точка входа: python -m bot"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from .app import build_dispatcher
from .config import load_settings
from .db import init_db, make_engine, make_sessionmaker
from .reminders import reminder_loop
from .webhook import build_app, start_server


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("bot")

    settings = load_settings()
    engine = make_engine(settings.database_url)
    await init_db(engine)
    sessionmaker = make_sessionmaker(engine)

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me = await bot.get_me()
    log.info("Бот @%s запущен", me.username)
    if not settings.admin_ids:
        log.warning("ADMIN_IDS пуст: админ-команды недоступны. Узнайте свой id командой /id в боте.")

    await bot.set_my_commands([
        BotCommand(command="start", description="Записаться / моя запись"),
        BotCommand(command="my", description="Моя запись"),
        BotCommand(command="help", description="Помощь"),
    ])

    dp = build_dispatcher(settings, sessionmaker, me.username)

    runner = None
    if settings.webhook_enabled:
        runner = await start_server(build_app(sessionmaker, settings, me.username), settings.webhook_host, settings.webhook_port)

    reminders = asyncio.create_task(reminder_loop(bot, sessionmaker, settings))
    try:
        await dp.start_polling(bot)
    finally:
        reminders.cancel()
        if runner:
            await runner.cleanup()
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
