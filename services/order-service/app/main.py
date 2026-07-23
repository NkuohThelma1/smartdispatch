"""order-service: order placement, tracking, and cancellation.

Emits: order.placed, order.cancelled

Endpoints:
  POST /orders              Bearer  { lat, lon, mode, item_ref? }  -> { order_id, status }
  POST /orders/{id}/cancel  Bearer                                  -> { status }
  GET  /orders/{id}                                                 -> { ... }
"""
from __future__ import annotations
import os
import uuid
import logging

import jwt
import structlog
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from prometheus_client import Counter, make_asgi_app

from .db import init, insert_order, cancel, get
from .events import publish, health, producer, stop_producer

logging.basicConfig(level=logging.INFO)
structlog.configure(processors=[structlog.processors.JSONRenderer()])
log = structlog.get_logger("order-service")

JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-change-me")
JWT_ALG = "HS256"
PORT = int(os.getenv("SERVICE_PORT", "8002"))

app = FastAPI(title="smartdispatch-order-service")
app.mount("/metrics", make_asgi_app())
ORDERS = Counter("smartdispatch_order_placed_total", "Orders placed", ["mode"])
CANCELS = Counter("smartdispatch_order_cancels_total", "Order cancellations")


class OrderIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    mode: str = Field(pattern="^(standard|express)$")
    item_ref: str | None = None


def auth(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    try:
        return jwt.decode(authorization[7:], JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"bad token: {e}")


@app.on_event("startup")
async def startup() -> None:
    init()
    await producer()
    log.info("order-service.up", port=PORT)


@app.on_event("shutdown")
async def shutdown() -> None:
    await stop_producer()


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "version": "v2"}


@app.get("/readyz")
async def readyz():
    if not await health():
        raise HTTPException(503, "kafka unreachable")
    return {"status": "ready"}


@app.post("/orders", status_code=201)
async def place_order(body: OrderIn, claims: dict = Depends(auth)):
    oid = str(uuid.uuid4())
    item_ref = body.item_ref or f"ref://order/{oid}/item"
    insert_order(oid, claims["sub"], body.lat, body.lon, body.mode, item_ref)
    await publish(
        "order.placed",
        {
            "order_id": oid,
            "user_id": claims["sub"],
            "lat": body.lat,
            "lon": body.lon,
            "mode": body.mode,
            "item_ref": item_ref,
        },
        key=oid,
    )
    ORDERS.labels(mode=body.mode).inc()
    log.info("order.placed", id=oid, mode=body.mode)
    return {"order_id": oid, "status": "ACTIVE"}


@app.post("/orders/{oid}/cancel")
async def cancel_order(oid: str, claims: dict = Depends(auth)):
    row = cancel(oid, claims["sub"])
    if not row:
        raise HTTPException(404, "order not found")
    if row["status"] != "CANCELLED":
        raise HTTPException(409, f"current status {row['status']} cannot be cancelled")
    await publish(
        "order.cancelled",
        {"order_id": oid, "user_id": claims["sub"]},
        key=oid
    )
    CANCELS.inc()
    return {"status": "CANCELLED"}


@app.get("/orders/{oid}")
async def get_order(oid: str):
    row = get(oid)
    if not row:
        raise HTTPException(404, "not found")
    return {k: row[k] for k in row.keys()}