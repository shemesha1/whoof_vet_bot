"""Работа со временем. В базе всё хранится в UTC (без tzinfo), пользователю показывается локальное время."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
WEEKDAYS_LOWER = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MONTHS_GEN = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_local(dt_utc: datetime, tz: ZoneInfo) -> datetime:
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(tz)


def local_to_utc(dt_local: datetime, tz: ZoneInfo) -> datetime:
    return dt_local.replace(tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)


def day_bounds_utc(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = local_to_utc(datetime.combine(day, time.min), tz)
    end = local_to_utc(datetime.combine(day + timedelta(days=1), time.min), tz)
    return start, end


def fmt_day_button(day: date) -> str:
    return f"{WEEKDAYS_SHORT[day.weekday()]} {day:%d.%m}"


def fmt_day_long(day: date) -> str:
    return f"{WEEKDAYS_LOWER[day.weekday()]}, {day.day} {MONTHS_GEN[day.month - 1]}"


def fmt_dt(dt_utc: datetime, tz: ZoneInfo) -> str:
    local = to_local(dt_utc, tz)
    return f"{fmt_day_long(local.date())}, {local:%H:%M}"
