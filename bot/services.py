"""Бизнес-логика: приглашения, слоты, запись. Хендлеры бота только вызывают эти функции."""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

from sqlalchemy import delete, distinct, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .db import Booking, Invite, Slot
from .timeutil import day_bounds_utc, local_to_utc, to_local, utcnow

# Без похожих символов (0/O, 1/I/L), чтобы код с карточки было легко ввести руками
TOKEN_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
TOKEN_LENGTH = 8


def new_token() -> str:
    return "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(TOKEN_LENGTH))


def normalize_token(raw: str) -> str:
    return raw.strip().upper().replace("-", "").replace(" ", "")


def looks_like_token(raw: str) -> bool:
    t = normalize_token(raw)
    return len(t) == TOKEN_LENGTH and all(c in TOKEN_ALPHABET for c in t)


def deep_link(bot_username: str, token: str) -> str:
    return f"https://t.me/{bot_username}?start={token}"


# ---------------------------------------------------------------- приглашения

async def create_invite(
    session: AsyncSession,
    *,
    ttl_days: int,
    source: str = "manual",
    external_order_id: str | None = None,
    customer_name: str | None = None,
    phone: str | None = None,
) -> tuple[Invite, bool]:
    """Создаёт приглашение. Повторный вызов с тем же external_order_id вернёт уже созданное (идемпотентность)."""
    if external_order_id:
        existing = await session.scalar(select(Invite).where(Invite.external_order_id == external_order_id))
        if existing:
            return existing, False

    token = new_token()
    while await session.scalar(select(Invite.id).where(Invite.token == token)):
        token = new_token()

    invite = Invite(
        token=token,
        source=source,
        external_order_id=external_order_id,
        customer_name=customer_name,
        phone=phone,
        expires_at=utcnow() + timedelta(days=ttl_days),
    )
    session.add(invite)
    await session.flush()
    return invite, True


class Redeem(str, Enum):
    OK = "ok"
    NOT_FOUND = "not_found"
    EXPIRED = "expired"
    TAKEN = "taken"


async def redeem_invite(
    session: AsyncSession, raw_token: str, tg_user_id: int, tg_username: str | None = None
) -> tuple[Redeem, Invite | None]:
    """Привязывает приглашение к Telegram-аккаунту. Один код = один аккаунт."""
    token = normalize_token(raw_token)
    invite = await session.scalar(select(Invite).where(Invite.token == token))
    if invite is None:
        return Redeem.NOT_FOUND, None
    if invite.tg_user_id == tg_user_id:
        return Redeem.OK, invite
    if invite.tg_user_id is not None:
        return Redeem.TAKEN, invite
    if invite.expires_at < utcnow():
        return Redeem.EXPIRED, invite

    # атомарно: привязываем только если код ещё никем не занят
    result = await session.execute(
        update(Invite)
        .where(Invite.id == invite.id, Invite.tg_user_id.is_(None))
        .values(tg_user_id=tg_user_id, tg_username=tg_username, redeemed_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        return Redeem.TAKEN, invite
    await session.refresh(invite)
    return Redeem.OK, invite


async def get_usable_invite(session: AsyncSession, tg_user_id: int) -> Invite | None:
    """Приглашение пользователя, по которому ещё можно записаться (нет активной или прошедшей записи)."""
    used = select(Booking.invite_id).where(Booking.status.in_(("active", "done")))
    return await session.scalar(
        select(Invite)
        .where(Invite.tg_user_id == tg_user_id, Invite.id.not_in(used), Invite.expires_at > utcnow())
        .order_by(Invite.redeemed_at)
        .limit(1)
    )


# ---------------------------------------------------------------- слоты

async def free_days(session: AsyncSession, tz: ZoneInfo, days_ahead: int, min_lead_minutes: int) -> list[date]:
    """Дни ближайшей недели (или days_ahead), где есть хотя бы один свободный слот."""
    now = utcnow()
    today_local = to_local(now, tz).date()
    _, end = day_bounds_utc(today_local + timedelta(days=days_ahead - 1), tz)
    rows = await session.scalars(
        select(Slot.starts_at)
        .where(Slot.status == "free", Slot.starts_at >= now + timedelta(minutes=min_lead_minutes), Slot.starts_at < end)
        .order_by(Slot.starts_at)
    )
    days: list[date] = []
    for dt in rows:
        d = to_local(dt, tz).date()
        if not days or days[-1] != d:
            days.append(d)
    return days


async def free_slots_on(session: AsyncSession, tz: ZoneInfo, day: date, min_lead_minutes: int) -> list[Slot]:
    """Свободные слоты на день. Если в одно время свободны несколько врачей, показываем время один раз."""
    start, end = day_bounds_utc(day, tz)
    start = max(start, utcnow() + timedelta(minutes=min_lead_minutes))
    slots = await session.scalars(
        select(Slot)
        .where(Slot.status == "free", Slot.starts_at >= start, Slot.starts_at < end)
        .order_by(Slot.starts_at, Slot.id)
    )
    unique: list[Slot] = []
    for s in slots:
        if not unique or unique[-1].starts_at != s.starts_at:
            unique.append(s)
    return unique


async def add_slots(
    session: AsyncSession,
    tz: ZoneInfo,
    day: date,
    start: time,
    end: time,
    step_minutes: int,
    vet_name: str = "",
) -> int:
    """Нарезает окна с start до end с шагом step_minutes. Уже существующие пропускает. Возвращает число новых."""
    created = 0
    cur = datetime.combine(day, start)
    last = datetime.combine(day, end)
    while cur + timedelta(minutes=step_minutes) <= last:
        starts_utc = local_to_utc(cur, tz)
        exists = await session.scalar(
            select(Slot.id).where(Slot.starts_at == starts_utc, Slot.vet_name == vet_name)
        )
        if not exists:
            session.add(Slot(starts_at=starts_utc, duration_min=step_minutes, vet_name=vet_name))
            created += 1
        cur += timedelta(minutes=step_minutes)
    await session.flush()
    return created


async def delete_free_slots(session: AsyncSession, tz: ZoneInfo, day: date) -> int:
    start, end = day_bounds_utc(day, tz)
    result = await session.execute(
        delete(Slot).where(Slot.status == "free", Slot.starts_at >= start, Slot.starts_at < end)
    )
    return result.rowcount or 0


# ---------------------------------------------------------------- запись

class Book(str, Enum):
    OK = "ok"
    SLOT_TAKEN = "slot_taken"
    NO_INVITE = "no_invite"
    TOO_LATE = "too_late"
    NOT_FOUND = "not_found"


async def get_active_booking(session: AsyncSession, tg_user_id: int) -> Booking | None:
    return await session.scalar(
        select(Booking)
        .join(Slot, Slot.id == Booking.slot_id)
        .where(Booking.tg_user_id == tg_user_id, Booking.status == "active")
        .order_by(Slot.starts_at)
        .limit(1)
    )


async def book_slot(
    session: AsyncSession,
    tg_user_id: int,
    slot_id: int,
    *,
    min_lead_minutes: int = 0,
    move_booking_id: int = 0,
) -> tuple[Book, Booking | None]:
    """Записывает на слот. Если move_booking_id задан, переносит существующую запись.

    Бронь атомарная: UPDATE ... WHERE status='free' сработает только для одного из
    двух одновременных запросов, второй получит SLOT_TAKEN.
    """
    old: Booking | None = None
    if move_booking_id:
        old = await session.scalar(
            select(Booking).where(
                Booking.id == move_booking_id, Booking.tg_user_id == tg_user_id, Booking.status == "active"
            )
        )
        if old is None:
            return Book.NOT_FOUND, None
        invite = old.invite
    else:
        invite = await get_usable_invite(session, tg_user_id)
        if invite is None:
            return Book.NO_INVITE, None

    slot = await session.get(Slot, slot_id)
    if slot is None:
        return Book.NOT_FOUND, None
    if slot.starts_at < utcnow() + timedelta(minutes=min_lead_minutes):
        return Book.TOO_LATE, None

    claimed = await session.execute(
        update(Slot).where(Slot.id == slot_id, Slot.status == "free").values(status="booked")
    )
    if claimed.rowcount != 1:
        return Book.SLOT_TAKEN, None

    if old is not None:
        await session.execute(update(Slot).where(Slot.id == old.slot_id).values(status="free"))
        old.status = "moved"

    booking = Booking(invite=invite, slot=slot, tg_user_id=tg_user_id)
    # если до консультации меньше суток, «напоминание за сутки» не нужно
    if slot.starts_at - utcnow() <= timedelta(hours=24):
        booking.reminded_24h = True
    session.add(booking)
    await session.flush()
    return Book.OK, booking


async def cancel_booking(session: AsyncSession, booking_id: int, tg_user_id: int | None = None) -> Booking | None:
    query = select(Booking).where(Booking.id == booking_id, Booking.status == "active")
    if tg_user_id is not None:
        query = query.where(Booking.tg_user_id == tg_user_id)
    booking = await session.scalar(query)
    if booking is None:
        return None
    booking.status = "canceled"
    await session.execute(update(Slot).where(Slot.id == booking.slot_id).values(status="free"))
    await session.flush()
    return booking


async def set_rating(session: AsyncSession, booking_id: int, tg_user_id: int, score: int) -> Booking | None:
    booking = await session.scalar(
        select(Booking).where(Booking.id == booking_id, Booking.tg_user_id == tg_user_id)
    )
    if booking is None or not 1 <= score <= 5:
        return None
    booking.rating = score
    await session.flush()
    return booking


# ---------------------------------------------------------------- админка

async def upcoming_bookings(session: AsyncSession, limit: int = 30) -> list[Booking]:
    rows = await session.scalars(
        select(Booking)
        .join(Slot, Slot.id == Booking.slot_id)
        .where(Booking.status == "active", Slot.starts_at >= utcnow() - timedelta(hours=1))
        .order_by(Slot.starts_at)
        .limit(limit)
    )
    return list(rows)


async def free_slots_summary(session: AsyncSession, tz: ZoneInfo, days: int) -> list[tuple[date, int]]:
    now = utcnow()
    _, end = day_bounds_utc(to_local(now, tz).date() + timedelta(days=days - 1), tz)
    rows = await session.scalars(
        select(Slot.starts_at).where(Slot.status == "free", Slot.starts_at >= now, Slot.starts_at < end)
    )
    counter: dict[date, int] = {}
    for dt in rows:
        d = to_local(dt, tz).date()
        counter[d] = counter.get(d, 0) + 1
    return sorted(counter.items())


@dataclass
class Funnel:
    invites: int
    redeemed: int
    booked: int
    done: int
    canceled: int
    avg_rating: float | None
    ratings: int


async def funnel(session: AsyncSession) -> Funnel:
    invites = await session.scalar(select(func.count(Invite.id))) or 0
    redeemed = await session.scalar(select(func.count(Invite.id)).where(Invite.tg_user_id.is_not(None))) or 0
    booked = await session.scalar(
        select(func.count(distinct(Booking.invite_id))).where(Booking.status.in_(("active", "done")))
    ) or 0
    done = await session.scalar(select(func.count(Booking.id)).where(Booking.status == "done")) or 0
    canceled = await session.scalar(select(func.count(Booking.id)).where(Booking.status == "canceled")) or 0
    avg = await session.scalar(select(func.avg(Booking.rating)).where(Booking.rating.is_not(None)))
    ratings = await session.scalar(select(func.count(Booking.id)).where(Booking.rating.is_not(None))) or 0
    return Funnel(invites, redeemed, booked, done, canceled, float(avg) if avg is not None else None, ratings)
