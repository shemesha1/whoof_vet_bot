"""Сквозной сценарий: покупатель проходит весь путь в боте, Telegram подменён фейком."""
import asyncio
from datetime import datetime, time, timedelta

from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot import services as svc
from bot.app import build_dispatcher
from bot.db import Booking
from bot.timeutil import to_local, utcnow

USER = User(id=777, is_bot=False, first_name="Анна", username="anna_dog")
CHAT = Chat(id=777, type="private")
ADMIN = User(id=999, is_bot=False, first_name="Админ")


class Harness:
    def __init__(self, dp, bot, tg):
        self.dp, self.bot, self.tg, self.uid = dp, bot, tg, 0

    async def text(self, text, user=USER):
        self.uid += 1
        msg = Message(message_id=self.uid, date=datetime.now(), chat=Chat(id=user.id, type="private"),
                      from_user=user, text=text)
        await self.dp.feed_update(self.bot, Update(update_id=self.uid, message=msg))
        return self.tg.calls[-1]

    async def click(self, button_text_part):
        """Нажимает кнопку из последнего сообщения с клавиатурой."""
        last = next(c for c in reversed(self.tg.calls)
                    if isinstance(c, (SendMessage, EditMessageText)) and c.reply_markup)
        btn = next(b for row in last.reply_markup.inline_keyboard for b in row if button_text_part in b.text)
        self.uid += 1
        msg = Message(message_id=1, date=datetime.now(), chat=CHAT, text=last.text)
        cq = CallbackQuery(id=str(self.uid), from_user=USER, chat_instance="x", message=msg, data=btn.callback_data)
        await self.dp.feed_update(self.bot, Update(update_id=self.uid, callback_query=cq))

    def last_text(self):
        """Последнее сообщение пользователю (уведомления в чат ветеринаров пропускаем)."""
        return [c for c in self.tg.calls if isinstance(c, (SendMessage, EditMessageText))
                and c.chat_id != -100500][-1].text


def test_full_user_journey(db, settings, fake_bot):
    bot, tg = fake_bot

    async def go():
        dp = build_dispatcher(settings, db, "whoof_vet_bot")
        h = Harness(dp, bot, tg)
        day = to_local(utcnow(), settings.timezone).date() + timedelta(days=2)

        # админ добавляет окна и создаёт приглашение прямо в боте
        await h.text(f"/slots_add {day.isoformat()} 10:00-12:00 30 Иванова", user=ADMIN)
        assert "Добавлено окон: 4" in h.last_text()
        await h.text("/invite Анна", user=ADMIN)
        token = h.last_text().split("<code>")[1].split("</code>")[0]

        # обычный пользователь не может пользоваться админ-командами
        await h.text("/stats")
        assert "Воронка" not in h.last_text()

        # покупатель переходит по deep-link
        await h.text(f"/start {token}")
        assert "Спасибо за покупку" in h.last_text()

        await h.click(f"{day:%d.%m}")          # выбирает день
        assert "Выберите время" in h.last_text()
        await h.click("10:30")                  # время
        assert "Записать вас на" in h.last_text()
        await h.click("Подтвердить")
        assert "вы записаны" in h.last_text()
        vet_msgs = [c for c in tg.calls if isinstance(c, SendMessage) and c.chat_id == settings.vet_chat_id]
        assert "Новая запись" in vet_msgs[-1].text and "@anna_dog" in vet_msgs[-1].text

        # перенос на 11:00
        await h.click("Перенести")
        await h.click(f"{day:%d.%m}")
        await h.click("11:00")
        assert "Перенести запись на" in h.last_text()
        await h.click("Подтвердить")
        assert "перенесена" in h.last_text()

        # /my показывает актуальную запись
        await h.text("/my")
        assert "11:00" in h.last_text()

        # отмена
        await h.click("Отменить")
        await h.click("Да, отменить")
        assert "отменена" in h.last_text()

        # чужой человек с тем же кодом
        stranger = User(id=1234, is_bot=False, first_name="X")
        await h.text(f"/start {token}", user=stranger)
        assert "уже активирован" in h.last_text()

        # код, введённый текстом
        async with db() as s:
            inv2, _ = await svc.create_invite(s, ttl_days=90)
            await s.commit()
        await h.text(inv2.token.lower(), user=stranger)
        assert "Спасибо за покупку" in h.last_text()

        await h.text("/stats", user=ADMIN)
        assert "Приглашений выдано: 2" in h.last_text()

        async with db() as s:
            from sqlalchemy import select
            statuses = sorted((await s.scalars(select(Booking.status))).all())
            assert statuses == ["canceled", "moved"]

    asyncio.run(go())
