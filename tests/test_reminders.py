import asyncio
from datetime import timedelta

from bot import reminders
from bot import services as svc
from bot.db import Booking, Slot
from bot.timeutil import utcnow


def test_reminders_feedback_and_nudge(db, settings, fake_bot):
    bot, tg = fake_bot

    async def go():
        now = utcnow()
        async with db() as s:
            slot = Slot(starts_at=now + timedelta(hours=30), duration_min=30)
            s.add(slot)
            inv, _ = await svc.create_invite(s, ttl_days=90)
            await svc.redeem_invite(s, inv.token, 11)
            await s.commit()
            _, booking = await svc.book_slot(s, 11, slot.id)
            # второй покупатель перешёл в бота, но так и не записался
            s.add(Slot(starts_at=now + timedelta(hours=50), duration_min=30))
            inv2, _ = await svc.create_invite(s, ttl_days=90)
            await svc.redeem_invite(s, inv2.token, 22)
            inv2.redeemed_at = now - timedelta(hours=25)
            await s.commit()
            bid = booking.id

        start = now + timedelta(hours=30)
        # за 23 часа до начала – напоминание за сутки (+ дожим второго покупателя)
        st = await reminders.run_once(bot, db, settings, now=start - timedelta(hours=23))
        assert st == {"r24": 1, "r1": 0, "feedback": 0, "nudge": 1}
        # повторный прогон ничего не дублирует
        st = await reminders.run_once(bot, db, settings, now=start - timedelta(hours=22))
        assert not any(st.values())
        # за 50 минут – напоминание со ссылкой на звонок
        st = await reminders.run_once(bot, db, settings, now=start - timedelta(minutes=50))
        assert st["r1"] == 1
        assert settings.meeting_url in tg.sent(11)[-1].text
        # через час после окончания – запрос оценки, запись помечена как прошедшая
        st = await reminders.run_once(bot, db, settings, now=start + timedelta(minutes=70))
        assert st["feedback"] == 1
        async with db() as s:
            assert (await s.get(Booking, bid)).status == "done"

    asyncio.run(go())
