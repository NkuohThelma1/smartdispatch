"""delivery-service: localize customer, match a delivery agent,
enforce no-double-assignment.

Consumes: order.placed, order.cancelled
Produces: delivery.assigned, delivery.confirmed, delivery.completed

Patterns demonstrated:
  - Strategy   (matching.py)
  - Saga       (this service is the saga coordinator's middle step)
  - Repository (db.py)
  - Outbox-lite (claim row then emit assignment in same handler)
"""
from __future__ import annotations
import asyncio
import logging
import os

import structlog
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, make_asgi_app
from pydantic import BaseModel

from .db import (
    init,
    all_free_agents,
    reserve_agent_for,
    assignment_for,
    release_assignment,
    list_delivery_zones,
)
from .events import consume, publish, health, producer, stop_producer
from .matching import matcher, haversine_m

logging.basicConfig(level=logging.INFO)
structlog.configure(processors=[structlog.processors.JSONRenderer()])
log = structlog.get_logger("delivery-service")

PORT = int(os.getenv("SERVICE_PORT", "8003"))
GROUP = "delivery-service"

app = FastAPI(title="smartdispatch-delivery-service")
app.mount("/metrics", make_asgi_app())
ASSIGNED = Counter("smartdispatch_delivery_assigned_total", "Assignments")
RELEASED = Counter("smartdispatch_delivery_released_total", "Cancellations released")
ZONE_HITS = Counter("smartdispatch_delivery_zone_hits_total", "Delivery zone hits")


class ConfirmIn(BaseModel):
    order_id: str
    agent_id: str


async def on_event(payload: dict) -> None:
    stream = payload.get("_stream")
    if stream == "order.placed":
        await handle_order(payload)
    elif stream == "order.cancelled":
        await handle_cancel(payload)
    else:
        log.info("ignored", stream=stream)


async def handle_order(p: dict) -> None:
    oid = p["order_id"]
    if assignment_for(oid):
        log.info("delivery.idempotent", order_id=oid)
        return
    free = all_free_agents()
    if not free:
        log.warning("no agents free", order_id=oid)
        return
    pick = matcher().pick(p["lat"], p["lon"], free)
    if not pick:
        return
    if not reserve_agent_for(pick["id"], oid):
        log.warning("race lost, retry next event", agent=pick["id"], order_id=oid)
        return
    await publish(
        "delivery.assigned",
        {
            "order_id": oid,
            "agent_id": pick["id"],
            "customer_user": p["user_id"],
            "lat": p["lat"],
            "lon": p["lon"]
        },
        key=oid,
    )
    ASSIGNED.inc()
    log.info("delivery.assigned", order_id=oid, agent=pick["id"])

    # Zone alerts: notify when delivery location is inside a known zone
    for z in list_delivery_zones():
        if haversine_m(p["lat"], p["lon"], z["lat"], z["lon"]) <= z["radius_m"]:
            await publish(
                "delivery.completed",
                {"zone_id": z["id"], "order_id": oid, "user_id": p["user_id"]},
                key=oid,
            )
            ZONE_HITS.inc()


async def handle_cancel(p: dict) -> None:
    oid = p["order_id"]
    if not assignment_for(oid):
        return
    release_assignment(oid)
    await publish(
        "delivery.confirmed",
        {"order_id": oid, "status": "RELEASED"},
        key=oid
    )
    RELEASED.inc()


@app.on_event("startup")
async def startup() -> None:
    init()
    await producer()
    asyncio.create_task(consume(["order.placed", "order.cancelled"], GROUP, on_event))
    log.info("delivery-service.up", port=PORT)


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


@app.post("/agents/confirm")
async def confirm(body: ConfirmIn):
    """Agent acknowledges they are en route. Emits delivery.confirmed."""
    a = assignment_for(body.order_id)
    if not a or a["agent_id"] != body.agent_id:
        raise HTTPException(404, "no matching assignment")
    await publish(
        "delivery.confirmed",
        {"order_id": body.order_id, "status": "EN_ROUTE"},
        key=body.order_id
    )
    return {"ok": True}
