"""Пачка приглашений для печати на вкладышах в коробку (маркетплейсы, офлайн-продажи).

Создаёт N кодов в базе, CSV-файл и PNG с QR-кодом на каждый код.
    python -m scripts.make_invites --count 500 --bot whoof_vet_bot --source marketplace --out out/batch_2026_10
"""
from __future__ import annotations

import argparse
import asyncio
import csv
from pathlib import Path

import qrcode

from bot import services as svc
from bot.config import load_settings
from bot.db import init_db, make_engine, make_sessionmaker


async def main() -> None:
    p = argparse.ArgumentParser(description="Сгенерировать коды и QR для вкладышей")
    p.add_argument("--count", type=int, required=True)
    p.add_argument("--bot", required=True, help="username бота без @")
    p.add_argument("--source", default="marketplace")
    p.add_argument("--ttl-days", type=int, default=365, help="срок действия кода, дней (для коробок берите с запасом)")
    p.add_argument("--out", default="out/invites")
    p.add_argument("--no-qr", action="store_true", help="только CSV, без картинок")
    args = p.parse_args()

    settings = load_settings(require_token=False)
    out = Path(args.out)
    (out / "qr").mkdir(parents=True, exist_ok=True)

    engine = make_engine(settings.database_url)
    await init_db(engine)
    sm = make_sessionmaker(engine)

    rows = []
    async with sm() as session:
        for _ in range(args.count):
            invite, _ = await svc.create_invite(session, ttl_days=args.ttl_days, source=args.source)
            rows.append((invite.token, svc.deep_link(args.bot, invite.token)))
        await session.commit()
    await engine.dispose()

    with open(out / "invites.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["code", "link", "qr_file"])
        for token, link in rows:
            qr_file = f"qr/{token}.png"
            if not args.no_qr:
                qrcode.make(link, box_size=10, border=2).save(out / qr_file)
            writer.writerow([token, link, "" if args.no_qr else qr_file])

    print(f"Создано {len(rows)} кодов → {out / 'invites.csv'}")


if __name__ == "__main__":
    asyncio.run(main())
