"""Общие фикстуры: временная база и «ненастоящий» Telegram, который записывает все вызовы API."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiogram import Bot  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage  # noqa: E402
from aiogram.types import Chat, Message  # noqa: E402

from bot.config import Settings  # noqa: E402
from bot.db import init_db, make_engine, make_sessionmaker  # noqa: E402


def make_settings(**overrides) -> Settings:
    base = dict(
        bot_token="42:TEST",
        database_url="",
        timezone=ZoneInfo("Europe/Moscow"),
        admin_ids=(999,),
        vet_chat_id=-100500,
        meeting_url="https://telemost.yandex.ru/j/test",
        brand_name="Whoof",
        support_contact="@whoof_support",
        days_ahead=7,
        min_lead_minutes=60,
        invite_ttl_days=90,
        default_slot_minutes=30,
        webhook_enabled=False,
        webhook_host="127.0.0.1",
        webhook_port=0,
        webhook_secret="s" * 32,
    )
    base.update(overrides)
    return Settings(**base)


class FakeSession(BaseSession):
    """Перехватывает вызовы Telegram API и складывает их в список, ничего не отправляя в сеть."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list = []
        self._next_id = 1000

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            self._next_id += 1
            chat_id = method.chat_id if method.chat_id is not None else 1
            return Message(
                message_id=self._next_id,
                date=datetime.now(),
                chat=Chat(id=chat_id, type="private"),
                text=method.text,
            )
        if isinstance(method, AnswerCallbackQuery):
            return True
        return True

    async def stream_content(self, *a, **kw):  # pragma: no cover
        yield b""

    async def close(self) -> None:
        pass

    def sent(self, chat_id=None):
        return [c for c in self.calls if isinstance(c, (SendMessage, EditMessageText))
                and (chat_id is None or c.chat_id == chat_id)]


@pytest.fixture
def db(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    asyncio.run(init_db(engine))
    yield make_sessionmaker(engine)
    asyncio.run(engine.dispose())


@pytest.fixture
def settings():
    return make_settings()


@pytest.fixture
def fake_bot():
    session = FakeSession()
    bot = Bot("42:TEST", session=session, default=DefaultBotProperties(parse_mode="HTML"))
    return bot, session
