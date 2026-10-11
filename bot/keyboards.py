"""Inline-клавиатуры и данные кнопок."""
from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .db import Slot
from .timeutil import fmt_day_button, to_local


class DayCB(CallbackData, prefix="d"):
    day: str  # YYYY-MM-DD
    move: int = 0  # id записи, которую переносим (0, если запись новая)


class SlotCB(CallbackData, prefix="s"):
    slot_id: int
    move: int = 0


class ConfirmCB(CallbackData, prefix="c"):
    slot_id: int
    move: int = 0


class BackCB(CallbackData, prefix="b"):
    to: str  # days / slots
    day: str = ""
    move: int = 0


class BookingCB(CallbackData, prefix="bk"):
    action: str  # move / cancel / cancel_yes / cancel_no
    booking_id: int


class RateCB(CallbackData, prefix="r"):
    booking_id: int
    score: int


def days_kb(days: list[date], move: int = 0) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for d in days:
        kb.button(text=fmt_day_button(d), callback_data=DayCB(day=d.isoformat(), move=move))
    kb.adjust(3)
    if move:
        kb.row(*InlineKeyboardBuilder().button(
            text="« Оставить как есть", callback_data=BookingCB(action="cancel_no", booking_id=move)
        ).buttons)
    return kb.as_markup()


def slots_kb(slots: list[Slot], tz: ZoneInfo, move: int = 0) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for s in slots:
        kb.button(text=f"{to_local(s.starts_at, tz):%H:%M}", callback_data=SlotCB(slot_id=s.id, move=move))
    kb.adjust(4)
    kb.row(*InlineKeyboardBuilder().button(text="« Другой день", callback_data=BackCB(to="days", move=move)).buttons)
    return kb.as_markup()


def confirm_kb(slot_id: int, day: str, move: int = 0) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data=ConfirmCB(slot_id=slot_id, move=move))
    kb.button(text="« Другое время", callback_data=BackCB(to="slots", day=day, move=move))
    kb.adjust(1)
    return kb.as_markup()


def booking_kb(booking_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔁 Перенести", callback_data=BookingCB(action="move", booking_id=booking_id))
    kb.button(text="✖️ Отменить", callback_data=BookingCB(action="cancel", booking_id=booking_id))
    kb.adjust(2)
    return kb.as_markup()


def cancel_confirm_kb(booking_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Да, отменить", callback_data=BookingCB(action="cancel_yes", booking_id=booking_id))
    kb.button(text="Нет, оставить", callback_data=BookingCB(action="cancel_no", booking_id=booking_id))
    kb.adjust(2)
    return kb.as_markup()


def rating_kb(booking_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for score in range(1, 6):
        kb.button(text=f"{score}⭐", callback_data=RateCB(booking_id=booking_id, score=score))
    kb.adjust(5)
    return kb.as_markup()
