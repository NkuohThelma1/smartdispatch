import asyncio
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load_pkg_module(full_name, relpath):
    path = ROOT / relpath
    spec = importlib.util.spec_from_file_location(full_name, path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = full_name.rpartition(".")[0]
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    sys.modules[full_name] = module
    return module


class TestNotificationDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        os.environ["DB_PATH"] = self.tmp.name
        self.db = _load_pkg_module("services.notification_service.app.db", "services/notification-service/app/db.py")
        self.db.DB_PATH = self.tmp.name
        self.db.init()

    def tearDown(self):
        os.environ.pop("DB_PATH", None)
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_record_and_list(self):
        rid = self.db.record("sms", "u1", "welcome", '{"text":"hi"}')
        self.assertIsNotNone(rid)
        rows = self.db.list_all(10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["channel"], "sms")
        self.assertEqual(rows[0]["template"], "welcome")

    def test_list_all_order_and_limit(self):
        for i in range(5):
            self.db.record("push", f"u{i}", "t", "{}")
        rows = self.db.list_all(3)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["id"], 5)


class TestNotificationMain(unittest.TestCase):
    def setUp(self):
        with mock.patch("prometheus_client.Counter") as mock_counter, \
             mock.patch("prometheus_client.make_asgi_app"):
            self.db = _load_pkg_module("services.notification_service.app.db", "services/notification-service/app/db.py")
            self.events = _load_pkg_module("services.notification_service.app.events", "services/notification-service/app/events.py")
            self.main = _load_pkg_module("services.notification_service.app.main", "services/notification-service/app/main.py")
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        os.environ["DB_PATH"] = self.tmp.name
        self.db.DB_PATH = self.tmp.name
        self.db.init()
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()
        os.environ.pop("DB_PATH", None)
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_on_event_unknown_stream(self):
        result = self.loop.run_until_complete(self.main.on_event({"_stream": "unknown"}))
        self.assertIsNone(result)

    def test_on_event_order_placed_non_standard(self):
        payload = {"_stream": "order.placed", "mode": "express", "order_id": "o1"}
        result = self.loop.run_until_complete(self.main.on_event(payload))
        self.assertIsNone(result)

    def test_on_event_delivery_assigned(self):
        payload = {
            "_stream": "delivery.assigned",
            "order_id": "o1",
            "agent_id": "a1",
        }
        with mock.patch.object(self.main, "publish") as mock_pub:
            self.loop.run_until_complete(self.main.on_event(payload))
            self.assertTrue(mock_pub.called)
            self.assertEqual(mock_pub.call_args[0][0], "notification.sent")

    def test_on_event_delivery_completed(self):
        payload = {
            "_stream": "delivery.completed",
            "order_id": "o1",
            "zone_id": "z1",
        }
        with mock.patch.object(self.main, "publish") as mock_pub:
            self.loop.run_until_complete(self.main.on_event(payload))
            self.assertTrue(mock_pub.called)
            self.assertEqual(mock_pub.call_args[0][0], "notification.sent")

    def test_on_event_missing_keys_uses_broadcast(self):
        payload = {"_stream": "delivery.assigned"}
        with mock.patch.object(self.main, "publish") as mock_pub:
            self.loop.run_until_complete(self.main.on_event(payload))
            self.assertTrue(mock_pub.called)

    def test_latest_limit_clamped(self):
        for _ in range(5):
            self.db.record("sms", "u1", "t", "{}")
        rows = self.loop.run_until_complete(self.main.latest(limit=50))
        self.assertEqual(len(rows), 5)
        rows = self.loop.run_until_complete(self.main.latest(limit=0))
        self.assertEqual(len(rows), 1)


class TestNotificationEvents(unittest.TestCase):
    def test_circuit_breaker_same_implementation(self):
        with mock.patch("prometheus_client.Counter"), mock.patch("prometheus_client.make_asgi_app"):
            events = _load_pkg_module("services.notification_service.app.events", "services/notification-service/app/events.py")
        cb = events.CircuitBreaker(fail_threshold=2, reset_after_s=30.0)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            self.assertTrue(loop.run_until_complete(cb.allow()))
            self.assertTrue(loop.run_until_complete(cb.allow()))
            loop.run_until_complete(cb.record_failure())
            loop.run_until_complete(cb.record_failure())
            self.assertFalse(loop.run_until_complete(cb.allow()))
        finally:
            loop.close()

    def test_producer_singleton(self):
        with mock.patch("prometheus_client.Counter"), mock.patch("prometheus_client.make_asgi_app"):
            events = _load_pkg_module("services.notification_service.app.events", "services/notification-service/app/events.py")
        with mock.patch.object(events, "AIOKafkaProducer") as mock_producer_cls:
            mock_instance = mock_producer_cls.return_value
            mock_instance.start = mock.AsyncMock()
            mock_instance.stop = mock.AsyncMock()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                events._producer = None
                p1 = loop.run_until_complete(events.producer())
                p2 = loop.run_until_complete(events.producer())
                self.assertIs(p1, p2)
                self.assertEqual(mock_producer_cls.call_count, 1)
                loop.run_until_complete(events.stop_producer())
                self.assertIsNone(events._producer)
            finally:
                loop.close()

    def test_health_success(self):
        with mock.patch("prometheus_client.Counter"), mock.patch("prometheus_client.make_asgi_app"):
            events = _load_pkg_module("services.notification_service.app.events", "services/notification-service/app/events.py")
        with mock.patch.object(events, "producer") as mock_prod:
            mock_client = mock.AsyncMock()
            mock_prod.return_value.client = mock_client
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(events.health())
                self.assertTrue(result)
            finally:
                loop.close()

    def test_health_failure(self):
        with mock.patch("prometheus_client.Counter"), mock.patch("prometheus_client.make_asgi_app"):
            events = _load_pkg_module("services.notification_service.app.events", "services/notification-service/app/events.py")
        with mock.patch.object(events, "producer", side_effect=Exception("kafka down")):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(events.health())
                self.assertFalse(result)
            finally:
                loop.close()

    def test_publish_success(self):
        with mock.patch("prometheus_client.Counter"), mock.patch("prometheus_client.make_asgi_app"):
            events = _load_pkg_module("services.notification_service.app.events", "services/notification-service/app/events.py")
        mock_breaker = mock.AsyncMock()
        mock_breaker.allow.return_value = True
        mock_p = mock.AsyncMock()
        mock_prod = mock.AsyncMock(return_value=mock_p)
        with mock.patch.object(events, "_breaker", mock_breaker), \
             mock.patch.object(events, "producer", mock_prod):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(events.publish("test.topic", {"a": 1}, key="k1"))
                mock_breaker.allow.assert_called_once()
                mock_breaker.record_success.assert_called_once()
                mock_p.send_and_wait.assert_called_once_with("test.topic", value={"a": 1}, key="k1")
            finally:
                loop.close()

    def test_publish_circuit_open(self):
        with mock.patch("prometheus_client.Counter"), mock.patch("prometheus_client.make_asgi_app"):
            events = _load_pkg_module("services.notification_service.app.events", "services/notification-service/app/events.py")
        mock_breaker = mock.AsyncMock()
        mock_breaker.allow.return_value = False
        with mock.patch.object(events, "_breaker", mock_breaker):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                with self.assertRaises(RuntimeError):
                    loop.run_until_complete(events.publish("test.topic", {}))
                mock_breaker.record_failure.assert_not_called()
            finally:
                loop.close()

    def test_publish_failure(self):
        with mock.patch("prometheus_client.Counter"), mock.patch("prometheus_client.make_asgi_app"):
            events = _load_pkg_module("services.notification_service.app.events", "services/notification-service/app/events.py")
        mock_breaker = mock.AsyncMock()
        mock_breaker.allow.return_value = True
        mock_p = mock.AsyncMock()
        mock_p.send_and_wait.side_effect = Exception("broker down")
        mock_prod = mock.AsyncMock(return_value=mock_p)
        with mock.patch.object(events, "_breaker", mock_breaker), \
             mock.patch.object(events, "producer", mock_prod):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                with self.assertRaises(Exception):
                    loop.run_until_complete(events.publish("test.topic", {}))
                mock_breaker.record_failure.assert_called_once()
            finally:
                loop.close()


if __name__ == "__main__":
    unittest.main()
