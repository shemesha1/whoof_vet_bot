"""Сборка диспетчера. Вынесено отдельно, чтобы тесты могли собрать бота без запуска."""
from __future__ import annotations

from aiogram import Dispatcher
from sqlalchemy.ext.asyncio import async_sessionmaker

from .config import Settings
from .handlers import admin, user
from .middlewares import DbSessionMiddleware


def build_dispatcher(settings: Settings, sessionmaker: async_sessionmaker, bot_username: str) -> Dispatcher:
    dp = Dispatcher(settings=settings, sessionmaker=sessionmaker, bot_username=bot_username)
    dp.update.middleware(DbSessionMiddleware(sessionmaker))
    # админский роутер первым: его команды перехватываются только для ADMIN_IDS
    dp.include_routers(admin.router, user.router)
    return dp
