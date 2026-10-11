"""Команды для администраторов (id из ADMIN_IDS): слоты, записи, приглашения, статистика."""
from __future__ import annotations

from datetime import date, time

from aiogram import Router
from aiogram.filters import Command, CommandObject, Filter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from .. import services as svc
from ..config import Settings
from ..timeutil import fmt_day_button, fmt_dt
from html import escape


class IsAdmin(Filter):
    async def __call__(self, message: Message, settings: Settings) -> bool:
        return message.from_user is not None and message.from_user.id in settings.admin_ids


router = Router(name="admin")
router.message.filter(IsAdmin())

ADMIN_HELP = (
    "<b>Команды администратора</b>\n\n"
    "/slots_add 2026-10-12 10:00-18:00 30 Иванова – нарезать окна на день "
    "(шаг в минутах и имя врача необязательны)\n"
    "/slots [дней] – сколько свободных окон по дням\n"
    "/slots_del 2026-10-12 – удалить свободные окна на день (записи не трогаются)\n"
    "/bookings – ближайшие записи\n"
    "/invite [имя клиента] – создать приглашение вручную и получить ссылку\n"
    "/stats – воронка: приглашения → активации → записи → консультации\n"
    "/id – узнать id пользователя и чата"
)


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    await message.answer(ADMIN_HELP)


@router.message(Command("slots_add"))
async def cmd_slots_add(message: Message, command: CommandObject, session: AsyncSession, settings: Settings):
    usage = "Формат: /slots_add 2026-10-12 10:00-18:00 [шаг_мин] [имя врача]"
    parts = (command.args or "").split()
    if len(parts) < 2:
        await message.answer(usage)
        return
    try:
        day = date.fromisoformat(parts[0])
        start_raw, end_raw = parts[1].split("-")
        start, end = time.fromisoformat(start_raw), time.fromisoformat(end_raw)
        step = int(parts[2]) if len(parts) > 2 else settings.default_slot_minutes
    except ValueError:
        await message.answer(usage)
        return
    vet_name = " ".join(parts[3:])
    created = await svc.add_slots(session, settings.timezone, day, start, end, step, vet_name)
    await session.commit()
    await message.answer(f"Добавлено окон: {created} на {fmt_day_button(day)} ({start:%H:%M}-{end:%H:%M}, шаг {step} мин).")


@router.message(Command("slots"))
async def cmd_slots(message: Message, command: CommandObject, session: AsyncSession, settings: Settings):
    days = int(command.args) if (command.args or "").isdigit() else 14
    summary = await svc.free_slots_summary(session, settings.timezone, days)
    if not summary:
        await message.answer(f"Свободных окон на ближайшие {days} дн. нет. Добавьте: /slots_add")
        return
    lines = [f"{fmt_day_button(d)}: {n}" for d, n in summary]
    await message.answer("<b>Свободные окна</b>\n" + "\n".join(lines))


@router.message(Command("slots_del"))
async def cmd_slots_del(message: Message, command: CommandObject, session: AsyncSession, settings: Settings):
    try:
        day = date.fromisoformat((command.args or "").strip())
    except ValueError:
        await message.answer("Формат: /slots_del 2026-10-12")
        return
    removed = await svc.delete_free_slots(session, settings.timezone, day)
    await session.commit()
    await message.answer(f"Удалено свободных окон: {removed}.")


@router.message(Command("bookings"))
async def cmd_bookings(message: Message, session: AsyncSession, settings: Settings):
    bookings = await svc.upcoming_bookings(session)
    if not bookings:
        await message.answer("Ближайших записей нет.")
        return
    lines = []
    for b in bookings:
        who = escape(b.invite.customer_name or "без имени")
        extra = f", {escape(b.invite.phone)}" if b.invite.phone else ""
        uname = f", @{escape(b.invite.tg_username)}" if b.invite.tg_username else ""
        vet = f" [{escape(b.slot.vet_name)}]" if b.slot.vet_name else ""
        lines.append(f"• {fmt_dt(b.slot.starts_at, settings.timezone)}{vet} – {who}{extra}{uname}")
    await message.answer("<b>Ближайшие записи</b>\n" + "\n".join(lines))


@router.message(Command("invite"))
async def cmd_invite(
    message: Message, command: CommandObject, session: AsyncSession, settings: Settings, bot_username: str
):
    invite, _ = await svc.create_invite(
        session, ttl_days=settings.invite_ttl_days, source="manual", customer_name=(command.args or None)
    )
    await session.commit()
    await message.answer(
        f"Приглашение создано.\nКод: <code>{invite.token}</code>\n"
        f"Ссылка: {svc.deep_link(bot_username, invite.token)}"
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message, session: AsyncSession):
    f = await svc.funnel(session)

    def pct(a: int, b: int) -> str:
        return f"{a / b * 100:.0f}%" if b else "–"

    rating = f"{f.avg_rating:.2f} (оценок: {f.ratings})" if f.avg_rating is not None else "нет оценок"
    await message.answer(
        "<b>Воронка</b>\n"
        f"Приглашений выдано: {f.invites}\n"
        f"Перешли в бота: {f.redeemed} ({pct(f.redeemed, f.invites)})\n"
        f"Записались: {f.booked} ({pct(f.booked, f.redeemed)} от перешедших)\n"
        f"Консультация прошла: {f.done}\n"
        f"Отмен: {f.canceled}\n"
        f"Средняя оценка: {rating}"
    )
