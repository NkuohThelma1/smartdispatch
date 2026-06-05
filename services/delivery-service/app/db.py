"""SQLite repository for delivery-service. Pattern: Repository."""
from __future__ import annotations
import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

DB_PATH = os.getenv("DB_PATH", "/data/delivery.db")
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
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS agents (
                id           TEXT PRIMARY KEY,
                name         TEXT NOT NULL,
                lat          REAL NOT NULL,
                lon          REAL NOT NULL,
                credibility  REAL NOT NULL DEFAULT 1.0,
                busy         INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS assignments (
                order_id     TEXT PRIMARY KEY,
                agent_id     TEXT NOT NULL,
                status       TEXT NOT NULL CHECK(status IN ('ASSIGNED','CONFIRMED','RELEASED')),
                created_at   TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS delivery_zones (
                id        TEXT PRIMARY KEY,
                lat       REAL NOT NULL,
                lon       REAL NOT NULL,
                radius_m  REAL NOT NULL
            );
            """
        )
        # Seed a few agents and zones for the demo
        seed = c.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        if seed == 0:
            c.executemany(
                "INSERT INTO agents (id, name, lat, lon, credibility) VALUES (?, ?, ?, ?, ?)",
                [
                    ("a1", "Agent Alpha", 4.0511, 9.7679, 0.9),
                    ("a2", "Agent Bravo", 4.0611, 9.7779, 0.8),
                    ("a3", "Agent Charlie", 4.0411, 9.7579, 0.7),
                ],
            )
            c.execute(
                "INSERT INTO delivery_zones (id, lat, lon, radius_m) VALUES (?, ?, ?, ?)",
                ("z1", 4.0500, 9.7700, 500.0),
            )


def all_free_agents() -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT * FROM agents WHERE busy = 0").fetchall()


def reserve_agent_for(aid: str, order_id: str) -> bool:
    """Atomic claim: returns True if agent was free and is now busy."""
    with conn() as c:
        cur = c.execute(
            "UPDATE agents SET busy = 1 WHERE id = ? AND busy = 0", (aid,)
        )
        if cur.rowcount == 0:
            return False
        try:
            c.execute(
                "INSERT INTO assignments (order_id, agent_id, status) VALUES (?, ?, 'ASSIGNED')",
                (order_id, aid),
            )
        except sqlite3.IntegrityError:
            c.execute("UPDATE agents SET busy = 0 WHERE id = ?", (aid,))
            return False
        return True


def assignment_for(order_id: str) -> Optional[sqlite3.Row]:
    with conn() as c:
        return c.execute(
            "SELECT * FROM assignments WHERE order_id = ?", (order_id,)
        ).fetchone()


def release_assignment(order_id: str) -> None:
    with conn() as c:
        row = c.execute(
            "SELECT agent_id FROM assignments WHERE order_id = ?", (order_id,)
        ).fetchone()
        if not row:
            return
        c.execute(
            "UPDATE assignments SET status='RELEASED' WHERE order_id = ?", (order_id,)
        )
        c.execute("UPDATE agents SET busy = 0 WHERE id = ?", (row["agent_id"],))


def list_delivery_zones() -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT * FROM delivery_zones").fetchall()