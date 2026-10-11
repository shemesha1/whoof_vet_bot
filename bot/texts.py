"""Все тексты бота в одном месте, чтобы их было удобно править без лезания в логику."""
from __future__ import annotations

from html import escape

from .config import Settings
from .db import Booking
from .timeutil import fmt_dt


def welcome_new(s: Settings) -> str:
    return (
        f"Спасибо за покупку ошейника {escape(s.brand_name)}! 🐾\n\n"
        "Вам доступна <b>бесплатная онлайн-консультация ветеринара</b>: "
        "можно спросить про адаптацию к ошейнику, показатели активности, питание и здоровье питомца.\n\n"
        "Выберите удобный день:"
    )


def no_invite(s: Settings) -> str:
    text = (
        "Здравствуйте! Это бот записи на консультацию ветеринара для владельцев ошейников "
        f"{escape(s.brand_name)}.\n\n"
        "Чтобы записаться, перейдите по ссылке из письма о заказе или отправьте сюда "
        "<b>код из 8 символов</b> с карточки в коробке."
    )
    return text + support_line(s)


def support_line(s: Settings) -> str:
    return f"\n\nЕсли что-то не получается, напишите нам: {escape(s.support_contact)}" if s.support_contact else ""


NOT_FOUND = "Код не найден. Проверьте, что он введён без ошибок (8 символов, латиница и цифры)."
EXPIRED = "Срок действия этого кода истёк."
TAKEN = "Этот код уже активирован другим аккаунтом Telegram."
CHOOSE_DAY = "Выберите удобный день:"
CHOOSE_NEW_DAY = "Выберите новый день:"
SLOT_TAKEN = "Это время только что заняли. Выберите, пожалуйста, другое."
TOO_LATE = "На это время записаться уже нельзя. Выберите другое."
NO_SLOTS_DAY = "На этот день свободное время закончилось."
NOT_ACTIVE = "Эта запись уже неактуальна."


def no_free_days(s: Settings) -> str:
    return (
        "Сейчас все окна на ближайшие дни заняты 😔\n"
        "Мы уже передали это команде. Загляните через день-два и отправьте /start."
        + support_line(s)
    )


def choose_time(day_text: str, s: Settings) -> str:
    return f"<b>{day_text}</b>\nВыберите время ({s.tz_label}):"


def confirm(when: str, s: Settings, move: bool) -> str:
    verb = "Перенести запись на" if move else "Записать вас на"
    return f"{verb} <b>{when}</b> ({s.tz_label})?"


def booked(b: Booking, s: Settings, moved: bool = False) -> str:
    head = "Запись перенесена ✅" if moved else "Готово, вы записаны ✅"
    return (
        f"{head}\n\n"
        f"🗓 <b>{fmt_dt(b.slot.starts_at, s.timezone)}</b> ({s.tz_label})\n"
        f"⏱ {b.slot.duration_min} минут, онлайн по видеосвязи\n\n"
        "Напомним за сутки, а за час пришлём ссылку на звонок. "
        "Подготовьте вопросы и, если есть, данные из приложения ошейника."
    )


def booking_card(b: Booking, s: Settings) -> str:
    return (
        "У вас есть запись на консультацию:\n\n"
        f"🗓 <b>{fmt_dt(b.slot.starts_at, s.timezone)}</b> ({s.tz_label})\n"
        f"⏱ {b.slot.duration_min} минут, онлайн"
    )


def cancel_question(b: Booking, s: Settings) -> str:
    return f"Отменить запись на <b>{fmt_dt(b.slot.starts_at, s.timezone)}</b>?"


CANCELED = "Запись отменена. Если захотите записаться снова, отправьте /start."


def reminder_24h(b: Booking, s: Settings) -> str:
    return (
        "Напоминаем: завтра консультация ветеринара 🐾\n\n"
        f"🗓 <b>{fmt_dt(b.slot.starts_at, s.timezone)}</b> ({s.tz_label})\n\n"
        "Если планы изменились, перенесите или отмените запись кнопками ниже."
    )


def reminder_1h(b: Booking, s: Settings) -> str:
    link = (
        f'\n\n🔗 Ссылка на звонок: <a href="{escape(s.meeting_url, quote=True)}">подключиться</a>'
        if s.meeting_url
        else "\n\nВрач пришлёт ссылку на звонок в этот чат перед началом."
    )
    return (
        "Через час консультация ветеринара 🐾\n\n"
        f"🗓 <b>{fmt_dt(b.slot.starts_at, s.timezone)}</b> ({s.tz_label})" + link
    )


FEEDBACK = "Как прошла консультация? Оцените, пожалуйста, от 1 до 5 – это поможет нам стать лучше."
THANKS_RATING = "Спасибо за оценку! 💛"


def nudge(s: Settings) -> str:
    return (
        "Вы ещё не выбрали время для бесплатной консультации ветеринара 🐾\n"
        "Это займёт полминуты. Выберите удобный день:"
    )


HELP = (
    "Что умеет бот:\n"
    "• записать на бесплатную консультацию ветеринара после покупки ошейника\n"
    "• перенести или отменить запись\n"
    "• напомнить о консультации заранее\n\n"
    "/start – записаться или посмотреть свою запись\n"
    "/my – моя запись\n"
    "/help – эта подсказка"
)


# ----- уведомления для чата ветеринаров

def _who(b: Booking) -> str:
    inv = b.invite
    parts = [escape(inv.customer_name or "без имени")]
    if inv.phone:
        parts.append(escape(inv.phone))
    if inv.tg_username:
        parts.append(f"@{escape(inv.tg_username)}")
    parts.append(f'<a href="tg://user?id={b.tg_user_id}">профиль</a>')
    return ", ".join(parts)


def vet_new(b: Booking, s: Settings, moved: bool = False) -> str:
    title = "🔁 Перенос записи" if moved else "🆕 Новая запись"
    vet = f"\nВрач: {escape(b.slot.vet_name)}" if b.slot.vet_name else ""
    return f"{title}\n{fmt_dt(b.slot.starts_at, s.timezone)} ({s.tz_label}){vet}\nКлиент: {_who(b)}"


def vet_canceled(b: Booking, s: Settings) -> str:
    return f"✖️ Отмена записи\n{fmt_dt(b.slot.starts_at, s.timezone)}\nКлиент: {_who(b)}"


def vet_low_rating(b: Booking, s: Settings) -> str:
    return f"⚠️ Низкая оценка: {b.rating}/5\nКонсультация {fmt_dt(b.slot.starts_at, s.timezone)}\nКлиент: {_who(b)}"


def vet_no_slots(user_id: int) -> str:
    return (
        "⚠️ Покупатель хотел записаться, но свободных окон нет. "
        f'Добавьте слоты (/slots_add). <a href="tg://user?id={user_id}">Профиль</a>'
    )
