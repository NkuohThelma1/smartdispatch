import asyncio
import importlib.util
import json
import logging
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load_events_module(service):
    sys.modules["aiokafka"] = mock.MagicMock()
    path = ROOT / "services" / service / "app" / "events.py"
    spec = importlib.util.spec_from_file_location(f"events_{service}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeMsg:
    def __init__(self, topic, partition, offset, key, value):
        self.topic = topic
        self.partition = partition
        self.offset = offset
        self.key = key
        self.value = value


class AsyncIterMock:
    def __init__(self, items):
        self.items = items
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.items):
            raise StopAsyncIteration
        item = self.items[self.index]
        self.index += 1
        return item


class FakeConsumer:
    def __init__(self, msgs):
        self.msgs = msgs

    async def start(self):
        pass

    def __aiter__(self):
        return AsyncIterMock(self.msgs)

    async def commit(self):
        pass

    async def stop(self):
        pass


class TestNotificationServiceConsume(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.events = _load_events_module("notification-service")
        self.producer_instance = mock.AsyncMock()
        self.producer_instance.client = mock.AsyncMock()

    async def test_consume_handler_success_commits_and_records_success(self):
        msgs = [FakeMsg("notification.sent", 0, 1, "k1", {"_stream": "notification.sent", "channel": "sms"})]
        self.events.AIOKafkaConsumer.return_value = FakeConsumer(msgs)
        self.events._producer = self.producer_instance

        handler = mock.AsyncMock()
        mock_breaker = mock.AsyncMock()
        mock_breaker.allow.return_value = True
        self.events._breaker = mock_breaker
        await self.events.consume(["notification.sent"], "ng", handler)

        handler.assert_called_once()
        mock_breaker.record_success.assert_called_once()

    async def test_consume_handler_failure_logs_and_records_failure(self):
        msgs = [FakeMsg("notification.sent", 0, 1, "k1", {"_stream": "notification.sent", "channel": "sms"})]
        self.events.AIOKafkaConsumer.return_value = FakeConsumer(msgs)
        self.events._producer = self.producer_instance

        handler = mock.AsyncMock(side_effect=RuntimeError("handler boom"))
        mock_breaker = mock.AsyncMock()
        mock_breaker.allow.return_value = True
        self.events._breaker = mock_breaker
        with self.assertLogs(self.events.log, level="ERROR") as cm:
            await self.events.consume(["notification.sent"], "ng", handler)

        mock_breaker.record_failure.assert_called_once()
        self.assertTrue(any("consumer.handler.failed" in msg for msg in cm.output))

    async def test_consume_open_breaker_skips_handler_and_commit(self):
        msgs = [FakeMsg("notification.sent", 0, 1, "k1", {"_stream": "notification.sent", "channel": "sms"})]
        self.events.AIOKafkaConsumer.return_value = FakeConsumer(msgs)
        self.events._producer = self.producer_instance

        handler = mock.AsyncMock()
        mock_breaker = mock.AsyncMock()
        mock_breaker.allow.return_value = False
        self.events._breaker = mock_breaker
        await self.events.consume(["notification.sent"], "ng", handler)

        handler.assert_not_called()
        mock_breaker.record_failure.assert_not_called()
        mock_breaker.record_success.assert_not_called()

    async def test_publish_success(self):
        self.events._producer = None
        with mock.patch.object(self.events, "AIOKafkaProducer") as mock_prod_cls:
            mock_p = mock.AsyncMock()
            mock_prod_cls.return_value = mock_p
            mock_breaker = mock.AsyncMock()
            mock_breaker.allow.return_value = True
            self.events._breaker = mock_breaker
            await self.events.publish("t", {"a": 1}, key="k")
            mock_breaker.record_success.assert_called_once()
            mock_p.send_and_wait.assert_called_once_with("t", value={"a": 1}, key="k")

    async def test_publish_failure_records_failure_and_raises(self):
        self.events._producer = None
        with mock.patch.object(self.events, "AIOKafkaProducer") as mock_prod_cls:
            mock_p = mock.AsyncMock()
            mock_p.send_and_wait.side_effect = Exception("broker down")
            mock_prod_cls.return_value = mock_p
            mock_breaker = mock.AsyncMock()
            mock_breaker.allow.return_value = True
            self.events._breaker = mock_breaker
            with self.assertRaises(Exception):
                await self.events.publish("t", {})
            mock_breaker.record_failure.assert_called_once()

    async def test_health_success(self):
        with mock.patch.object(self.events, "producer") as mock_prod:
            mock_client = mock.AsyncMock()
            mock_prod.return_value.client = mock_client
            result = await self.events.health()
            self.assertTrue(result)

    async def test_health_failure(self):
        with mock.patch.object(self.events, "producer", side_effect=Exception("down")):
            result = await self.events.health()
            self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
