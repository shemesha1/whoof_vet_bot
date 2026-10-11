"""Модели базы данных (SQLAlchemy 2.0, async)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, SmallInteger, String, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .timeutil import utcnow


class Base(DeclarativeBase):
    pass


class Invite(Base):
    """Приглашение на консультацию. Создаётся на каждый оплаченный заказ (или печатается на вкладыше)."""

    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    external_order_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")  # site / marketplace / manual
    customer_name: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    # заполняется, когда покупатель нажал «Старт» по ссылке или ввёл код
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    tg_username: Mapped[str | None] = mapped_column(String(64))
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime)
    nudge_sent: Mapped[bool] = mapped_column(default=False)


class Slot(Base):
    """Свободное окно в расписании ветеринара."""

    __tablename__ = "slots"
    __table_args__ = (UniqueConstraint("starts_at", "vet_name", name="uq_slot_time_vet"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC
    duration_min: Mapped[int] = mapped_column(default=30)
    vet_name: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(10), default="free", index=True)  # free / booked


class Booking(Base):
    """Запись пользователя на конкретный слот."""

    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    invite_id: Mapped[int] = mapped_column(ForeignKey("invites.id"), index=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("slots.id"), index=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # active / moved / canceled / done
    status: Mapped[str] = mapped_column(String(10), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    reminded_24h: Mapped[bool] = mapped_column(default=False)
    reminded_1h: Mapped[bool] = mapped_column(default=False)
    feedback_sent: Mapped[bool] = mapped_column(default=False)
    rating: Mapped[int | None] = mapped_column(SmallInteger)

    slot: Mapped[Slot] = relationship(lazy="joined")
    invite: Mapped[Invite] = relationship(lazy="joined")


def make_engine(url: str) -> AsyncEngine:
    if url.startswith("sqlite"):
        # создаём папку под файл базы, если её нет
        import os

        path = url.split("///", 1)[-1]
        if path and path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        return create_async_engine(url, connect_args={"timeout": 15})
    return create_async_engine(url, pool_pre_ping=True)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
