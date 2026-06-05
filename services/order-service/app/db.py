"""SQLite repository for order-service. Pattern: Repository."""
from __future__ import annotations
import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

DB_PATH = os.getenv("DB_PATH", "/data/order.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


@contextmanager
def conn() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init() -> None:
    with conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id           TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL,
                lat          REAL NOT NULL,
                lon          REAL NOT NULL,
                mode         TEXT NOT NULL CHECK(mode IN ('standard','express')),
                item_ref     TEXT,
                status       TEXT NOT NULL CHECK(status IN ('ACTIVE','CANCELLED','DELIVERED')),
                created_at   TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )


def insert_order(oid: str, uid: str, lat: float, lon: float, mode: str, item_ref: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO orders (id, user_id, lat, lon, mode, item_ref, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE')",
            (oid, uid, lat, lon, mode, item_ref),
        )


def cancel(oid: str, uid: str) -> Optional[sqlite3.Row]:
    with conn() as c:
        c.execute(
            "UPDATE orders SET status='CANCELLED' WHERE id=? AND user_id=? AND status='ACTIVE'",
            (oid, uid),
        )
        return c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()


def get(oid: str) -> Optional[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()