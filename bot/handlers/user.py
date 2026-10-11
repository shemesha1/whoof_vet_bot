"""Сценарий покупателя: старт по ссылке/коду, выбор дня и времени, запись, перенос, отмена, оценка."""
from __future__ import annotations

from datetime import date

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from .. import services as svc
from .. import texts
from ..config import Settings
from ..db import Booking, Slot
from ..keyboards import (
    BackCB, BookingCB, ConfirmCB, DayCB, RateCB, SlotCB,
    booking_kb, cancel_confirm_kb, confirm_kb, days_kb, slots_kb,
)
from ..notify import notify_vets
from ..timeutil import fmt_day_long, fmt_dt, to_local

router = Router(name="user")


# ---------------------------------------------------------------- helpers

async def edit(cb: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            await cb.message.answer(text, reply_markup=markup)


async def days_screen(
    session: AsyncSession, settings: Settings, bot: Bot, user_id: int, header: str, move: int = 0
) -> tuple[str, InlineKeyboardMarkup | None]:
    days = await svc.free_days(session, settings.timezone, settings.days_ahead, settings.min_lead_minutes)
    if not days:
        await notify_vets(bot, settings, texts.vet_no_slots(user_id))
        markup = booking_kb(move) if move else None
        return texts.no_free_days(settings), markup
    return header, days_kb(days, move)


async def slots_screen(
    session: AsyncSession, settings: Settings, day: date, move: int
) -> tuple[str, InlineKeyboardMarkup] | None:
    slots = await svc.free_slots_on(session, settings.timezone, day, settings.min_lead_minutes)
    if not slots:
        return None
    return texts.choose_time(fmt_day_long(day), settings), slots_kb(slots, settings.timezone, move)


async def home(message: Message, session: AsyncSession, settings: Settings, bot: Bot, user_id: int) -> None:
    """Главный экран: есть запись – показываем её, есть приглашение – предлагаем дни, иначе просим код."""
    booking = await svc.get_active_booking(session, user_id)
    if booking:
        await message.answer(texts.booking_card(booking, settings), reply_markup=booking_kb(booking.id))
        return
    invite = await svc.get_usable_invite(session, user_id)
    if invite:
        text, markup = await days_screen(session, settings, bot, user_id, texts.welcome_new(settings))
        await message.answer(text, reply_markup=markup)
        return
    await message.answer(texts.no_invite(settings))


async def try_redeem(message: Message, session: AsyncSession, settings: Settings, raw: str) -> bool:
    user = message.from_user
    result, _ = await svc.redeem_invite(session, raw, user.id, user.username)
    await session.commit()
    if result is svc.Redeem.OK:
        return True
    error = {
        svc.Redeem.NOT_FOUND: texts.NOT_FOUND,
        svc.Redeem.EXPIRED: texts.EXPIRED,
        svc.Redeem.TAKEN: texts.TAKEN,
    }[result]
    await message.answer(error + texts.support_line(settings))
    return False


# ---------------------------------------------------------------- команды

@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, session: AsyncSession, settings: Settings, bot: Bot):
    if command.args:
        ok = await try_redeem(message, session, settings, command.args)
        uid = message.from_user.id
        if not ok and not (await svc.get_active_booking(session, uid) or await svc.get_usable_invite(session, uid)):
            return
    await home(message, session, settings, bot, message.from_user.id)


@router.message(Command("my"))
async def cmd_my(message: Message, session: AsyncSession, settings: Settings, bot: Bot):
    await home(message, session, settings, bot, message.from_user.id)


@router.message(Command("help"))
async def cmd_help(message: Message, settings: Settings):
    await message.answer(texts.HELP + texts.support_line(settings))


@router.message(Command("id"))
async def cmd_id(message: Message):
    await message.answer(f"Ваш user id: <code>{message.from_user.id}</code>\nchat id: <code>{message.chat.id}</code>")


@router.message(F.text & ~F.text.startswith("/"), F.chat.type == "private")
async def text_input(message: Message, session: AsyncSession, settings: Settings, bot: Bot):
    """Пользователь прислал текст: если похоже на код с карточки – активируем, иначе показываем главный экран."""
    if svc.looks_like_token(message.text):
        if await try_redeem(message, session, settings, message.text):
            await home(message, session, settings, bot, message.from_user.id)
        return
    await home(message, session, settings, bot, message.from_user.id)


@router.message(F.text.startswith("/"), F.chat.type == "private")
async def unknown_command(message: Message, settings: Settings):
    await message.answer(texts.HELP + texts.support_line(settings))


# ---------------------------------------------------------------- выбор дня и времени

@router.callback_query(DayCB.filter())
async def on_day(cb: CallbackQuery, callback_data: DayCB, session: AsyncSession, settings: Settings, bot: Bot):
    day = date.fromisoformat(callback_data.day)
    screen = await slots_screen(session, settings, day, callback_data.move)
    if screen is None:
        await cb.answer(texts.NO_SLOTS_DAY, show_alert=True)
        text, markup = await days_screen(session, settings, bot, cb.from_user.id, texts.CHOOSE_DAY, callback_data.move)
        await edit(cb, text, markup)
        return
    await edit(cb, *screen)
    await cb.answer()


@router.callback_query(SlotCB.filter())
async def on_slot(cb: CallbackQuery, callback_data: SlotCB, session: AsyncSession, settings: Settings):
    slot = await session.get(Slot, callback_data.slot_id)
    if slot is None or slot.status != "free":
        await cb.answer(texts.SLOT_TAKEN, show_alert=True)
        return
    day = to_local(slot.starts_at, settings.timezone).date().isoformat()
    text = texts.confirm(fmt_dt(slot.starts_at, settings.timezone), settings, bool(callback_data.move))
    await edit(cb, text, confirm_kb(slot.id, day, callback_data.move))
    await cb.answer()


@router.callback_query(BackCB.filter())
async def on_back(cb: CallbackQuery, callback_data: BackCB, session: AsyncSession, settings: Settings, bot: Bot):
    move = callback_data.move
    if callback_data.to == "slots" and callback_data.day:
        screen = await slots_screen(session, settings, date.fromisoformat(callback_data.day), move)
        if screen:
            await edit(cb, *screen)
            await cb.answer()
            return
    header = texts.CHOOSE_NEW_DAY if move else texts.CHOOSE_DAY
    text, markup = await days_screen(session, settings, bot, cb.from_user.id, header, move)
    await edit(cb, text, markup)
    await cb.answer()


@router.callback_query(ConfirmCB.filter())
async def on_confirm(cb: CallbackQuery, callback_data: ConfirmCB, session: AsyncSession, settings: Settings, bot: Bot):
    result, booking = await svc.book_slot(
        session,
        cb.from_user.id,
        callback_data.slot_id,
        min_lead_minutes=settings.min_lead_minutes,
        move_booking_id=callback_data.move,
    )
    await session.commit()

    if result is svc.Book.OK:
        moved = bool(callback_data.move)
        await edit(cb, texts.booked(booking, settings, moved), booking_kb(booking.id))
        await cb.answer("Записали!")
        await notify_vets(bot, settings, texts.vet_new(booking, settings, moved))
        return

    if result in (svc.Book.SLOT_TAKEN, svc.Book.TOO_LATE):
        await cb.answer(texts.SLOT_TAKEN if result is svc.Book.SLOT_TAKEN else texts.TOO_LATE, show_alert=True)
        header = texts.CHOOSE_NEW_DAY if callback_data.move else texts.CHOOSE_DAY
        text, markup = await days_screen(session, settings, bot, cb.from_user.id, header, callback_data.move)
        await edit(cb, text, markup)
        return

    # NO_INVITE / NOT_FOUND: показываем актуальное состояние
    await cb.answer()
    await home(cb.message, session, settings, bot, cb.from_user.id)


# ---------------------------------------------------------------- перенос и отмена

async def _own_active(session: AsyncSession, booking_id: int, user_id: int) -> Booking | None:
    booking = await session.get(Booking, booking_id)
    if booking is None or booking.tg_user_id != user_id or booking.status != "active":
        return None
    return booking


@router.callback_query(BookingCB.filter())
async def on_booking_action(
    cb: CallbackQuery, callback_data: BookingCB, session: AsyncSession, settings: Settings, bot: Bot
):
    booking = await _own_active(session, callback_data.booking_id, cb.from_user.id)
    if booking is None:
        await cb.answer(texts.NOT_ACTIVE, show_alert=True)
        await home(cb.message, session, settings, bot, cb.from_user.id)
        return

    action = callback_data.action
    if action == "move":
        text, markup = await days_screen(session, settings, bot, cb.from_user.id, texts.CHOOSE_NEW_DAY, booking.id)
        await edit(cb, text, markup)
    elif action == "cancel":
        await edit(cb, texts.cancel_question(booking, settings), cancel_confirm_kb(booking.id))
    elif action == "cancel_yes":
        canceled = await svc.cancel_booking(session, booking.id, cb.from_user.id)
        await session.commit()
        if canceled:
            await edit(cb, texts.CANCELED)
            await notify_vets(bot, settings, texts.vet_canceled(canceled, settings))
    else:  # cancel_no
        await edit(cb, texts.booking_card(booking, settings), booking_kb(booking.id))
    await cb.answer()


@router.callback_query(RateCB.filter())
async def on_rate(cb: CallbackQuery, callback_data: RateCB, session: AsyncSession, settings: Settings, bot: Bot):
    booking = await svc.set_rating(session, callback_data.booking_id, cb.from_user.id, callback_data.score)
    await session.commit()
    if booking is None:
        await cb.answer()
        return
    await edit(cb, f"{texts.THANKS_RATING}\nВаша оценка: {booking.rating}/5")
    await cb.answer()
    if booking.rating <= 3:
        await notify_vets(bot, settings, texts.vet_low_rating(booking, settings))
