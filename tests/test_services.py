import asyncio
from datetime import timedelta

from bot import services as svc
from bot.db import Booking, Slot
from bot.timeutil import to_local, utcnow


def run(coro):
    return asyncio.run(coro)


def tomorrow(settings):
    return to_local(utcnow(), settings.timezone).date() + timedelta(days=1)


def test_token_format():
    t = svc.new_token()
    assert len(t) == 8 and svc.looks_like_token(t)
    assert svc.looks_like_token(t.lower()[:4] + "-" + t.lower()[4:])
    assert not svc.looks_like_token("привет")


def test_invite_idempotent_and_redeem(db, settings):
    async def go():
        async with db() as s:
            a, created_a = await svc.create_invite(s, ttl_days=90, external_order_id="A-1")
            b, created_b = await svc.create_invite(s, ttl_days=90, external_order_id="A-1")
            await s.commit()
            assert created_a and not created_b and a.token == b.token

            res, _ = await svc.redeem_invite(s, a.token.lower(), tg_user_id=1)
            assert res is svc.Redeem.OK
            res, _ = await svc.redeem_invite(s, a.token, tg_user_id=1)
            assert res is svc.Redeem.OK  # повторный вход того же человека
            res, _ = await svc.redeem_invite(s, a.token, tg_user_id=2)
            assert res is svc.Redeem.TAKEN
            res, _ = await svc.redeem_invite(s, "ZZZZZZZZ", tg_user_id=2)
            assert res is svc.Redeem.NOT_FOUND

            c, _ = await svc.create_invite(s, ttl_days=-1)
            res, _ = await svc.redeem_invite(s, c.token, tg_user_id=3)
            assert res is svc.Redeem.EXPIRED
    run(go())


def test_slots_and_double_booking(db, settings):
    """Два покупателя жмут на одно и то же время: записаться должен только один."""
    async def go():
        day = tomorrow(settings)
        async with db() as s:
            from datetime import time
            n = await svc.add_slots(s, settings.timezone, day, time(10), time(12), 30)
            assert n == 4
            assert await svc.add_slots(s, settings.timezone, day, time(10), time(12), 30) == 0  # без дублей
            for uid in (1, 2):
                inv, _ = await svc.create_invite(s, ttl_days=90)
                await svc.redeem_invite(s, inv.token, uid)
            await s.commit()

            days = await svc.free_days(s, settings.timezone, 7, 60)
            assert day in days
            slot = (await svc.free_slots_on(s, settings.timezone, day, 60))[0]
            assert f"{to_local(slot.starts_at, settings.timezone):%H:%M}" == "10:00"

        async def attempt(uid):
            async with db() as s:
                res, _ = await svc.book_slot(s, uid, slot.id, min_lead_minutes=60)
                await s.commit()
                return res

        results = await asyncio.gather(attempt(1), attempt(2))
        assert sorted(r.value for r in results) == ["ok", "slot_taken"]
        async with db() as s:
            assert len(await svc.free_slots_on(s, settings.timezone, day, 60)) == 3
    run(go())


def test_move_cancel_and_reuse(db, settings):
    async def go():
        from datetime import time
        day = tomorrow(settings)
        async with db() as s:
            await svc.add_slots(s, settings.timezone, day, time(10), time(11), 30)
            inv, _ = await svc.create_invite(s, ttl_days=90)
            await svc.redeem_invite(s, inv.token, 7)
            first, second = await svc.free_slots_on(s, settings.timezone, day, 60)

            res, b = await svc.book_slot(s, 7, first.id)
            assert res is svc.Book.OK
            # второе приглашение не появилось – повторно записаться нельзя
            res, _ = await svc.book_slot(s, 7, second.id)
            assert res is svc.Book.NO_INVITE

            res, moved = await svc.book_slot(s, 7, second.id, move_booking_id=b.id)
            assert res is svc.Book.OK
            await s.commit()
            assert (await s.get(Slot, first.id)).status == "free"
            assert (await s.get(Booking, b.id)).status == "moved"

            assert await svc.cancel_booking(s, moved.id, 7)
            await s.commit()
            assert (await s.get(Slot, second.id)).status == "free"
            # после отмены приглашение снова можно использовать
            assert await svc.get_usable_invite(s, 7) is not None

            f = await svc.funnel(s)
            assert f.invites == 1 and f.redeemed == 1 and f.canceled == 1
    run(go())


def test_min_lead_time(db, settings):
    async def go():
        async with db() as s:
            s.add(Slot(starts_at=utcnow() + timedelta(minutes=20), duration_min=30))
            inv, _ = await svc.create_invite(s, ttl_days=90)
            await svc.redeem_invite(s, inv.token, 5)
            await s.commit()
            slot_id = (await s.scalars(__import__("sqlalchemy").select(Slot.id))).first()
            res, _ = await svc.book_slot(s, 5, slot_id, min_lead_minutes=60)
            assert res is svc.Book.TOO_LATE
    run(go())
