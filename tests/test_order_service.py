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


class TestOrderDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        os.environ["DB_PATH"] = self.tmp.name
        self.db = _load_pkg_module("services.order_service.app.db", "services/order-service/app/db.py")
        self.db.DB_PATH = self.tmp.name
        self.db.init()

    def tearDown(self):
        os.environ.pop("DB_PATH", None)
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_insert_and_get(self):
        self.db.insert_order("o1", "u1", 1.0, 2.0, "standard", "ref1")
        row = self.db.get("o1")
        self.assertIsNotNone(row)
        self.assertEqual(row["user_id"], "u1")
        self.assertEqual(row["status"], "ACTIVE")
        self.assertEqual(row["mode"], "standard")

    def test_get_missing(self):
        self.assertIsNone(self.db.get("missing"))

    def test_cancel_active_order(self):
        self.db.insert_order("o2", "u2", 3.0, 4.0, "express", "ref2")
        row = self.db.cancel("o2", "u2")
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "CANCELLED")

    def test_cancel_wrong_user(self):
        self.db.insert_order("o3", "u3", 5.0, 6.0, "standard", "ref3")
        row = self.db.cancel("o3", "wrong")
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "ACTIVE")

    def test_cancel_already_cancelled(self):
        self.db.insert_order("o4", "u4", 7.0, 8.0, "standard", "ref4")
        self.db.cancel("o4", "u4")
        row = self.db.cancel("o4", "u4")
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "CANCELLED")


class TestOrderMain(unittest.TestCase):
    def setUp(self):
        with mock.patch("prometheus_client.Counter") as mock_counter, \
             mock.patch("prometheus_client.make_asgi_app"):
            self.db = _load_pkg_module("services.order_service.app.db", "services/order-service/app/db.py")
            self.events = _load_pkg_module("services.order_service.app.events", "services/order-service/app/events.py")
            self.main = _load_pkg_module("services.order_service.app.main", "services/order-service/app/main.py")
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

    def test_order_in_validation(self):
        body = self.main.OrderIn(lat=10.0, lon=20.0, mode="express", item_ref="ref")
        self.assertEqual(body.mode, "express")

    def test_auth_missing_bearer(self):
        with self.assertRaises(self.main.HTTPException) as ctx:
            self.main.auth("")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_auth_bad_token(self):
        with self.assertRaises(self.main.HTTPException) as ctx:
            self.main.auth("Bearer bad")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_cancel_order_not_found(self):
        with self.assertRaises(self.main.HTTPException) as ctx:
            self.loop.run_until_complete(self.main.cancel_order("missing", {"sub": "u1"}))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_get_order_not_found(self):
        with self.assertRaises(self.main.HTTPException) as ctx:
            self.loop.run_until_complete(self.main.get_order("missing"))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_place_order_success(self):
        body = self.main.OrderIn(lat=1.0, lon=2.0, mode="standard")
        with mock.patch.object(self.main, "publish") as mock_pub:
            result = self.loop.run_until_complete(self.main.place_order(body, claims={"sub": "u9"}))
            self.assertEqual(result["status"], "ACTIVE")
            self.assertIn("order_id", result)
            self.assertTrue(mock_pub.called)

    def test_readyz_kafka_down(self):
        with mock.patch.object(self.main, "health", return_value=False):
            with self.assertRaises(self.main.HTTPException) as ctx:
                self.loop.run_until_complete(self.main.readyz())
            self.assertEqual(ctx.exception.status_code, 503)


class TestOrderEvents(unittest.TestCase):
    def test_circuit_breaker_same_implementation(self):
        with mock.patch("prometheus_client.Counter"), mock.patch("prometheus_client.make_asgi_app"):
            events = _load_pkg_module("services.order_service.app.events", "services/order-service/app/events.py")
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
            events = _load_pkg_module("services.order_service.app.events", "services/order-service/app/events.py")
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
            events = _load_pkg_module("services.order_service.app.events", "services/order-service/app/events.py")
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
            events = _load_pkg_module("services.order_service.app.events", "services/order-service/app/events.py")
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
            events = _load_pkg_module("services.order_service.app.events", "services/order-service/app/events.py")
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
            events = _load_pkg_module("services.order_service.app.events", "services/order-service/app/events.py")
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
            events = _load_pkg_module("services.order_service.app.events", "services/order-service/app/events.py")
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
