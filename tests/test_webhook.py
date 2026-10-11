import asyncio

from aiohttp.test_utils import TestClient, TestServer

from bot.webhook import build_app


def test_order_paid_webhook(db, settings):
    async def go():
        app = build_app(db, settings, "whoof_vet_bot")
        async with TestClient(TestServer(app)) as client:
            r = await client.post("/webhook/order-paid", json={"order_id": "1"})
            assert r.status == 401

            headers = {"X-Webhook-Secret": settings.webhook_secret}
            r = await client.post("/webhook/order-paid", json={}, headers=headers)
            assert r.status == 400

            body = {"order_id": "10234", "customer_name": "Анна", "phone": "+79990000000"}
            r1 = await (await client.post("/webhook/order-paid", json=body, headers=headers)).json()
            r2 = await (await client.post("/webhook/order-paid", json=body, headers=headers)).json()
            assert r1["ok"] and r1["created"] and not r2["created"]
            assert r1["token"] == r2["token"]
            assert r1["link"] == f"https://t.me/whoof_vet_bot?start={r1['token']}"

            assert (await client.get("/health")).status == 200

    asyncio.run(go())
