"""Фоновые задачи: напоминания за 24 ч и за 1 ч, запрос оценки, «дожим» тех, кто не записался."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from . import services as svc
from . import texts
from .config import Settings
from .db import Booking, Invite
from .keyboards import booking_kb, days_kb, rating_kb
from .notify import safe_send
from .timeutil import utcnow

log = logging.getLogger(__name__)

FEEDBACK_DELAY = timedelta(minutes=30)  # через сколько после конца консультации просить оценку
NUDGE_AFTER = timedelta(hours=24)       # через сколько напомнить тем, кто перешёл, но не записался


async def run_once(bot: Bot, sessionmaker: async_sessionmaker, settings: Settings, now: datetime | None = None) -> dict:
    now = now or utcnow()
    stats = {"r24": 0, "r1": 0, "feedback": 0, "nudge": 0}
    async with sessionmaker() as session:
        bookings = (await session.scalars(select(Booking).where(Booking.status == "active"))).all()
        for b in bookings:
            until = b.slot.starts_at - now
            end = b.slot.starts_at + timedelta(minutes=b.slot.duration_min)

            if now >= end + FEEDBACK_DELAY:
                b.status = "done"
                if not b.feedback_sent:
                    b.feedback_sent = True
                    await safe_send(bot, b.tg_user_id, texts.FEEDBACK, rating_kb(b.id))
                    stats["feedback"] += 1
            elif not b.reminded_1h and timedelta(0) < until <= timedelta(hours=1):
                b.reminded_1h = b.reminded_24h = True
                await safe_send(bot, b.tg_user_id, texts.reminder_1h(b, settings))
                stats["r1"] += 1
            elif not b.reminded_24h and timedelta(hours=1) < until <= timedelta(hours=24):
                b.reminded_24h = True
                await safe_send(bot, b.tg_user_id, texts.reminder_24h(b, settings), booking_kb(b.id))
                stats["r24"] += 1
            await session.commit()  # фиксируем после каждой отправки, чтобы не дублировать при сбое

        has_booking = select(Booking.invite_id)
        invites = (await session.scalars(
            select(Invite).where(
                Invite.redeemed_at.is_not(None),
                Invite.redeemed_at <= now - NUDGE_AFTER,
                Invite.nudge_sent.is_(False),
                Invite.expires_at > now,
                Invite.id.not_in(has_booking),
            )
        )).all()
        for inv in invites:
            inv.nudge_sent = True
            await session.commit()
            days = await svc.free_days(session, settings.timezone, settings.days_ahead, settings.min_lead_minutes)
            if days:
                await safe_send(bot, inv.tg_user_id, texts.nudge(settings), days_kb(days))
                stats["nudge"] += 1
    return stats


async def reminder_loop(bot: Bot, sessionmaker: async_sessionmaker, settings: Settings, interval: int = 60) -> None:
    log.info("Планировщик напоминаний запущен (каждые %s с)", interval)
    while True:
        try:
            stats = await run_once(bot, sessionmaker, settings)
            if any(stats.values()):
                log.info("Напоминания: %s", stats)
        except Exception:  # noqa: BLE001 – цикл не должен падать
            log.exception("Ошибка в цикле напоминаний")
        await asyncio.sleep(interval)
