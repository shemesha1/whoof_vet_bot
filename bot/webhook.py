"""HTTP-эндпоинт для интернет-магазина: «заказ оплачен» → создаём приглашение и отдаём ссылку на бота.

POST /webhook/order-paid
Заголовок: X-Webhook-Secret: <WEBHOOK_SECRET>
Тело (JSON): {"order_id": "10234", "customer_name": "Анна", "phone": "+79990000000"}
Ответ:       {"ok": true, "token": "K7M2QX9P", "link": "https://t.me/<bot>?start=K7M2QX9P", "created": true}
"""
from __future__ import annotations

import hmac
import logging

from aiohttp import web
from sqlalchemy.ext.asyncio import async_sessionmaker

from . import services as svc
from .config import Settings

log = logging.getLogger(__name__)


def build_app(sessionmaker: async_sessionmaker, settings: Settings, bot_username: str) -> web.Application:
    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def order_paid(request: web.Request) -> web.Response:
        secret = request.headers.get("X-Webhook-Secret", "")
        if not settings.webhook_secret or not hmac.compare_digest(secret, settings.webhook_secret):
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        try:
            data = await request.json()
        except ValueError:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        order_id = str(data.get("order_id") or "").strip()
        if not order_id:
            return web.json_response({"ok": False, "error": "order_id is required"}, status=400)

        async with sessionmaker() as session:
            invite, created = await svc.create_invite(
                session,
                ttl_days=settings.invite_ttl_days,
                source=str(data.get("source") or "site")[:20],
                external_order_id=order_id[:64],
                customer_name=(str(data["customer_name"])[:200] if data.get("customer_name") else None),
                phone=(str(data["phone"])[:32] if data.get("phone") else None),
            )
            await session.commit()

        log.info("Заказ %s: приглашение %s (%s)", order_id, invite.token, "новое" if created else "уже было")
        return web.json_response({
            "ok": True,
            "token": invite.token,
            "link": svc.deep_link(bot_username, invite.token),
            "created": created,
        })

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/webhook/order-paid", order_paid)
    return app


async def start_server(app: web.Application, host: str, port: int) -> web.AppRunner:
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    log.info("Вебхук магазина слушает http://%s:%s/webhook/order-paid", host, port)
    return runner
