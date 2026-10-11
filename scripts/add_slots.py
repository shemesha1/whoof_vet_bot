"""Массовое добавление расписания на период.

Пример: окна по будням с 10:00 до 18:00 по 30 минут на две недели для врача Ивановой
    python -m scripts.add_slots --from 2026-10-12 --to 2026-10-25 --hours 10:00-18:00 --step 30 --weekdays 1-5 --vet "Иванова"
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, time, timedelta

from bot import services as svc
from bot.config import load_settings
from bot.db import init_db, make_engine, make_sessionmaker


def parse_weekdays(raw: str) -> set[int]:
    """'1-5' → {0..4}; '1,3,6' → {0,2,5}. 1 = понедельник."""
    result: set[int] = set()
    for part in raw.split(","):
        if "-" in part:
            a, b = part.split("-")
            result.update(range(int(a) - 1, int(b)))
        else:
            result.add(int(part) - 1)
    return result


async def main() -> None:
    p = argparse.ArgumentParser(description="Добавить окна для записи")
    p.add_argument("--from", dest="date_from", required=True, help="первый день, YYYY-MM-DD")
    p.add_argument("--to", dest="date_to", required=True, help="последний день, YYYY-MM-DD")
    p.add_argument("--hours", required=True, help="рабочие часы, например 10:00-18:00")
    p.add_argument("--step", type=int, default=None, help="длительность окна в минутах")
    p.add_argument("--weekdays", default="1-7", help="дни недели, 1=пн: '1-5' или '1,3,5'")
    p.add_argument("--vet", default="", help="имя врача (необязательно)")
    args = p.parse_args()

    settings = load_settings(require_token=False)
    step = args.step or settings.default_slot_minutes
    start_raw, end_raw = args.hours.split("-")
    start, end = time.fromisoformat(start_raw), time.fromisoformat(end_raw)
    weekdays = parse_weekdays(args.weekdays)

    engine = make_engine(settings.database_url)
    await init_db(engine)
    sm = make_sessionmaker(engine)

    total = 0
    day = date.fromisoformat(args.date_from)
    last = date.fromisoformat(args.date_to)
    async with sm() as session:
        while day <= last:
            if day.weekday() in weekdays:
                n = await svc.add_slots(session, settings.timezone, day, start, end, step, args.vet)
                total += n
                print(f"{day}: +{n}")
            day += timedelta(days=1)
        await session.commit()
    await engine.dispose()
    print(f"Готово, добавлено окон: {total}")


if __name__ == "__main__":
    asyncio.run(main())
