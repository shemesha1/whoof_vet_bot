"""Настройки бота. Все значения берутся из переменных окружения (файл .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _int_list(raw: str) -> tuple[int, ...]:
    return tuple(int(x) for x in raw.replace(" ", "").split(",") if x)


def _bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on", "да"}


@dataclass(frozen=True)
class Settings:
    bot_token: str
    database_url: str
    timezone: ZoneInfo
    admin_ids: tuple[int, ...]
    vet_chat_id: int | None
    meeting_url: str
    brand_name: str
    support_contact: str
    days_ahead: int
    min_lead_minutes: int
    invite_ttl_days: int
    default_slot_minutes: int
    webhook_enabled: bool
    webhook_host: str
    webhook_port: int
    webhook_secret: str

    @property
    def tz_label(self) -> str:
        return "по МСК" if self.timezone.key == "Europe/Moscow" else f"({self.timezone.key})"


def load_settings(require_token: bool = True) -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if require_token and not token:
        raise RuntimeError("Не задан BOT_TOKEN. Скопируйте .env.example в .env и впишите токен от @BotFather.")

    vet_chat = os.getenv("VET_CHAT_ID", "").strip()
    settings = Settings(
        bot_token=token,
        database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/whoof.db"),
        timezone=ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow")),
        admin_ids=_int_list(os.getenv("ADMIN_IDS", "")),
        vet_chat_id=int(vet_chat) if vet_chat else None,
        meeting_url=os.getenv("MEETING_URL", "").strip(),
        brand_name=os.getenv("BRAND_NAME", "Whoof"),
        support_contact=os.getenv("SUPPORT_CONTACT", "").strip(),
        days_ahead=int(os.getenv("DAYS_AHEAD", "7")),
        min_lead_minutes=int(os.getenv("MIN_LEAD_MINUTES", "60")),
        invite_ttl_days=int(os.getenv("INVITE_TTL_DAYS", "90")),
        default_slot_minutes=int(os.getenv("SLOT_MINUTES", "30")),
        webhook_enabled=_bool(os.getenv("WEBHOOK_ENABLED", "false")),
        webhook_host=os.getenv("WEBHOOK_HOST", "0.0.0.0"),
        webhook_port=int(os.getenv("WEBHOOK_PORT", "8080")),
        webhook_secret=os.getenv("WEBHOOK_SECRET", "").strip(),
    )
    if settings.webhook_enabled and len(settings.webhook_secret) < 16:
        raise RuntimeError("WEBHOOK_ENABLED=true, но WEBHOOK_SECRET пустой или короче 16 символов.")
    return settings
