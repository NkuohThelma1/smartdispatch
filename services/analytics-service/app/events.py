import asyncio
import json
import logging
import os
import time
from enum import Enum, auto
from typing import Awaitable, Callable, Iterable

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")

log = logging.getLogger(__name__)

_producer: AIOKafkaProducer | None = None


async def producer() -> AIOKafkaProducer:
    global _producer
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            enable_idempotence=True,
            acks="all",
            value_serializer=lambda v: json.dumps(v).encode(),
            key_serializer=lambda k: k.encode() if k else None,
        )
        await _producer.start()
    return _producer


async def stop_producer() -> None:
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None


async def health() -> bool:
    """Liveness ping for /readyz — verify broker reachable + metadata fetch works."""
    try:
        p = await producer()
        await p.client.fetch_all_metadata()
        return True
    except Exception:
        return False


class _State(Enum):
    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()


class CircuitBreaker:
    def __init__(self, fail_threshold: int = 5, reset_after_s: float = 30.0):
        self.fail_threshold = fail_threshold
        self.reset_after_s = reset_after_s
        self._state = _State.CLOSED
        self._fails = 0
        self._opened_at: float | None = None
        self._lock = asyncio.Lock()
        self._half_open_in_progress = False

    async def allow(self) -> bool:
        async with self._lock:
            if self._state is _State.CLOSED:
                return True
            if self._state is _State.OPEN:
                if (
                    self._opened_at is not None
                    and time.monotonic() - self._opened_at >= self.reset_after_s
                ):
                    self._state = _State.HALF_OPEN
                    self._half_open_in_progress = True
                    return True
                return False
            if self._state is _State.HALF_OPEN:
                if not self._half_open_in_progress:
                    self._half_open_in_progress = True
                    return True
                return False
            return False

    async def record_success(self) -> None:
        async with self._lock:
            self._fails = 0
            self._state = _State.CLOSED
            self._opened_at = None
            self._half_open_in_progress = False

    async def record_failure(self) -> None:
        async with self._lock:
            self._fails += 1
            if self._state is _State.HALF_OPEN:
                self._state = _State.OPEN
                self._opened_at = time.monotonic()
                self._half_open_in_progress = False
                return
            if self._state is _State.CLOSED and self._fails >= self.fail_threshold:
                self._state = _State.OPEN
                self._opened_at = time.monotonic()


_breaker = CircuitBreaker()


async def publish(topic: str, event: dict, key: str | None = None) -> None:
    """Outbox-lite: caller should db-write THEN await publish() in same async block."""
    if not await _breaker.allow():
        raise RuntimeError(f"circuit-open: {topic}")
    try:
        p = await producer()
        await p.send_and_wait(topic, value=event, key=key)
        await _breaker.record_success()
    except Exception:
        await _breaker.record_failure()
        raise


Handler = Callable[[dict], Awaitable[None]]


async def consume(topics: Iterable[str], group: str, handler: Handler) -> None:
    """Consumer-group reader with manual commit on handler success (at-least-once)."""
    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=group,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        value_deserializer=lambda v: json.loads(v.decode()),
    )
    await consumer.start()
    try:
        async for msg in consumer:
            payload = msg.value
            payload["_stream"] = msg.topic  # back-compat name for handlers
            if not await _breaker.allow():
                continue
            try:
                await handler(payload)
                await _breaker.record_success()
                await consumer.commit()
            except Exception as exc:
                await _breaker.record_failure()
                log.error(
                    "consumer.handler.failed topic=%s partition=%s offset=%s key=%r"
                    " error=%s",
                    msg.topic,
                    msg.partition,
                    msg.offset,
                    msg.key,
                    exc,
                    exc_info=True,
                )
                # leave un-committed → re-delivered on next read (at-least-once)
    finally:
        await consumer.stop()
