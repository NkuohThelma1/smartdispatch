"""notification-service: simulated SMS / push / email delivery.

Consumes: delivery.assigned, delivery.completed, order.placed (standard mode only)
Produces: notification.sent

Real SMS / push is OUT OF SCOPE — we just log a structured line and persist a row.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os

import structlog
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, make_asgi_app

from .db import init, record, list_all
from .events import consume, publish, health, producer, stop_producer

logging.basicConfig(level=logging.INFO)
structlog.configure(processors=[structlog.processors.JSONRenderer()])
log = structlog.get_logger("notification-service")

PORT = int(os.getenv("SERVICE_PORT", "8004"))
GROUP = "notification-service"

app = FastAPI(title="smartdispatch-notification-service")
app.mount("/metrics", make_asgi_app())
SENT = Counter(
    "smartdispatch_notifications_sent_total", "Notifications", ["channel", "template"]
)

TEMPLATES = {
    "delivery.assigned": (
        "sms",
        "agent_dispatched",
        "Agent {agent_id} is on the way for order {order_id}.",
    ),
    "delivery.completed": (
        "push",
        "delivery_zone_alert",
        "Your order {order_id} has reached delivery zone {zone_id}.",
    ),
    "order.placed": (
        "sms",
        "order_ack",
        "Order {order_id} received successfully (standard-mode fallback).",
    ),
}


async def on_event(p: dict) -> None:
    stream = p.get("_stream", "")
    tmpl = TEMPLATES.get(stream)
    if not tmpl:
        return
    # Standard-mode orders get an SMS acknowledgement
    # Express-mode orders are handled differently downstream
    if stream == "order.placed" and p.get("mode") != "standard":
        return
    channel, name, body_fmt = tmpl
    recipient = p.get("user_id") or p.get("customer_user") or "broadcast"
    msg = body_fmt.format(
        **{k: p.get(k, "?") for k in ("order_id", "agent_id", "zone_id")}
    )
    record(channel, recipient, name, json.dumps({"text": msg, "src": p}))
    log.info(
        "notification.delivered",
        channel=channel,
        template=name,
        recipient=recipient,
        body=msg
    )
    SENT.labels(channel=channel, template=name).inc()
    await publish(
        "notification.sent",
        {"channel": channel, "template": name, "recipient": recipient},
        key=p.get("order_id"),
    )


@app.on_event("startup")
async def startup() -> None:
    init()
    await producer()
    asyncio.create_task(
        consume(
            ["delivery.assigned", "delivery.completed", "order.placed"],
            GROUP,
            on_event,
        )
    )
    log.info("notification-service.up", port=PORT)


@app.on_event("shutdown")
async def shutdown() -> None:
    await stop_producer()


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    if not await health():
        raise HTTPException(503, "kafka unreachable")
    return {"status": "ready"}


@app.get("/notifications")
async def latest(limit: int = 50):
    rows = list_all(min(max(limit, 1), 500))
    return [dict(r) for r in rows]
