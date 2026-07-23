import asyncio
import importlib.util
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


class TestAnalyticsDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        os.environ["DB_PATH"] = self.tmp.name
        self.db = _load_pkg_module("services.analytics_service.app.db", "services/analytics-service/app/db.py")
        self.db.DB_PATH = self.tmp.name
        self.db.init()

    def tearDown(self):
        os.environ.pop("DB_PATH", None)
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_bump_event_creates_and_increments(self):
        self.db.bump_event("order.placed")
        self.db.bump_event("order.placed")
        rows = self.db.event_summary()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["stream"], "order.placed")
        self.assertEqual(rows[0]["n"], 2)

    def test_log_order_ignore_duplicate(self):
        self.db.log_order("o1", 1.0, 2.0, "standard")
        self.db.log_order("o1", 1.0, 2.0, "standard")
        rows = self.db.delivery_map()
        self.assertEqual(len(rows), 1)

    def test_log_zone_hit(self):
        self.db.log_zone_hit("z1", "o1")
        self.db.log_zone_hit("z1", "o2")
        rows = self.db.zone_summary()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hits"], 2)

    def test_zone_summary_empty(self):
        self.assertEqual(self.db.zone_summary(), [])

    def test_event_summary_empty(self):
        self.assertEqual(self.db.event_summary(), [])


class TestAnalyticsMain(unittest.TestCase):
    def setUp(self):
        with mock.patch("prometheus_client.Counter") as mock_counter, \
             mock.patch("prometheus_client.make_asgi_app"):
            self.db = _load_pkg_module("services.analytics_service.app.db", "services/analytics-service/app/db.py")
            self.events = _load_pkg_module("services.analytics_service.app.events", "services/analytics-service/app/events.py")
            self.main = _load_pkg_module("services.analytics_service.app.main", "services/analytics-service/app/main.py")
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

    def test_on_event_user_registered(self):
        payload = {"_stream": "user.registered", "user_id": "u1"}
        with mock.patch.object(self.main, "EVENTS") as mock_counter:
            self.loop.run_until_complete(self.main.on_event(payload))
            mock_counter.labels.assert_called_with(stream="user.registered")
            self.assertTrue(mock_counter.labels.return_value.inc.called)

    def test_on_event_order_placed(self):
        payload = {
            "_stream": "order.placed",
            "order_id": "o1",
            "lat": 1.0,
            "lon": 2.0,
            "mode": "express",
        }
        with mock.patch.object(self.main, "EVENTS"):
            self.loop.run_until_complete(self.main.on_event(payload))
            rows = self.db.delivery_map()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["mode"], "express")

    def test_on_event_delivery_completed(self):
        payload = {"_stream": "delivery.completed", "zone_id": "z1", "order_id": "o1"}
        with mock.patch.object(self.main, "EVENTS"):
            self.loop.run_until_complete(self.main.on_event(payload))
            rows = self.db.zone_summary()
            self.assertEqual(len(rows), 1)

    def test_on_event_notification_sent(self):
        payload = {"_stream": "notification.sent", "channel": "sms", "template": "ack"}
        with mock.patch.object(self.main, "EVENTS"):
            self.loop.run_until_complete(self.main.on_event(payload))
            rows = self.db.event_summary()
            self.assertEqual(len(rows), 1)

    def test_stats_endpoints(self):
        self.db.bump_event("order.placed")
        self.db.log_order("o1", 1.0, 2.0, "standard")
        self.db.log_zone_hit("z1", "o1")
        zones = self.loop.run_until_complete(self.main.stats_zones())
        self.assertEqual(len(zones), 1)
        deliveries = self.loop.run_until_complete(self.main.stats_deliveries())
        self.assertEqual(len(deliveries), 1)
        events = self.loop.run_until_complete(self.main.stats_events())
        self.assertEqual(len(events), 1)

    def test_readyz_kafka_down(self):
        with mock.patch.object(self.main, "health", return_value=False):
            with self.assertRaises(self.main.HTTPException) as ctx:
                self.loop.run_until_complete(self.main.readyz())
            self.assertEqual(ctx.exception.status_code, 503)


class TestAnalyticsEvents(unittest.TestCase):
    def test_circuit_breaker_same_implementation(self):
        with mock.patch("prometheus_client.Counter"), mock.patch("prometheus_client.make_asgi_app"):
            events = _load_pkg_module("services.analytics_service.app.events", "services/analytics-service/app/events.py")
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
            events = _load_pkg_module("services.analytics_service.app.events", "services/analytics-service/app/events.py")
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
            events = _load_pkg_module("services.analytics_service.app.events", "services/analytics-service/app/events.py")
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
            events = _load_pkg_module("services.analytics_service.app.events", "services/analytics-service/app/events.py")
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
            events = _load_pkg_module("services.analytics_service.app.events", "services/analytics-service/app/events.py")
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
            events = _load_pkg_module("services.analytics_service.app.events", "services/analytics-service/app/events.py")
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
            events = _load_pkg_module("services.analytics_service.app.events", "services/analytics-service/app/events.py")
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
