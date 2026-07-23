import asyncio
import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bcrypt

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


class TestUserDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        os.environ["DB_PATH"] = self.tmp.name
        self.db = _load_pkg_module("services.user_service.app.db", "services/user-service/app/db.py")
        self.db.DB_PATH = self.tmp.name
        self.db.init()

    def tearDown(self):
        os.environ.pop("DB_PATH", None)
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_insert_and_find_by_phone(self):
        self.db.insert_user("u1", "123456", "hash", "customer")
        row = self.db.find_by_phone("123456")
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], "u1")
        self.assertEqual(row["role"], "customer")

    def test_find_by_phone_missing(self):
        self.assertIsNone(self.db.find_by_phone("missing"))

    def test_find_by_id(self):
        self.db.insert_user("u2", "654321", "hash2", "agent")
        row = self.db.find_by_id("u2")
        self.assertIsNotNone(row)
        self.assertEqual(row["phone"], "654321")

    def test_find_by_id_missing(self):
        self.assertIsNone(self.db.find_by_id("nope"))

    def test_add_contact_duplicate_ignored(self):
        self.db.insert_user("u3", "111", "h", "business")
        self.db.add_contact("u3", "Alice", "222")
        self.db.add_contact("u3", "Alice", "222")
        rows = self.db.list_contacts("u3")
        self.assertEqual(len(rows), 1)

    def test_list_contacts_empty(self):
        self.db.insert_user("u4", "333", "h", "customer")
        self.assertEqual(self.db.list_contacts("u4"), [])


class TestUserMain(unittest.TestCase):
    def setUp(self):
        with mock.patch("prometheus_client.Counter") as mock_counter, \
             mock.patch("prometheus_client.make_asgi_app"):
            self.db = _load_pkg_module("services.user_service.app.db", "services/user-service/app/db.py")
            self.events = _load_pkg_module("services.user_service.app.events", "services/user-service/app/events.py")
            self.main = _load_pkg_module("services.user_service.app.main", "services/user-service/app/main.py")
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

    def test_make_token_claims(self):
        token = self.main.make_token("u1", "agent")
        payload = self.main.jwt.decode(token, self.main.JWT_SECRET, algorithms=[self.main.JWT_ALG])
        self.assertEqual(payload["sub"], "u1")
        self.assertEqual(payload["role"], "agent")

    def test_auth_missing_bearer(self):
        with self.assertRaises(self.main.HTTPException) as ctx:
            self.main.auth("")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_auth_bad_token(self):
        with self.assertRaises(self.main.HTTPException) as ctx:
            self.main.auth("Bearer bad")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_signup_duplicate_phone(self):
        self.db.insert_user("u5", "777777", "h", "customer")
        body = self.main.SignupIn(phone="777777", password="secret123", role="customer")
        with self.assertRaises(self.main.HTTPException) as ctx:
            self.loop.run_until_complete(self.main.signup(body))
        self.assertEqual(ctx.exception.status_code, 409)

    def test_login_invalid_credentials(self):
        body = self.main.LoginIn(phone="nope", password="wrong")
        with self.assertRaises(self.main.HTTPException) as ctx:
            self.loop.run_until_complete(self.main.login(body))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_contacts_endpoint(self):
        self.db.insert_user("u6", "888888", "h", "customer")
        self.db.add_contact("u6", "Bob", "999999")
        body = self.main.ContactIn(name="Bob", phone="999999")
        result = self.loop.run_until_complete(self.main.post_contact(body, claims={"sub": "u6"}))
        self.assertTrue(result["ok"])
        rows = self.loop.run_until_complete(self.main.get_contacts({"sub": "u6"}))
        self.assertEqual(len(rows), 1)

    def test_signup_success(self):
        body = self.main.SignupIn(phone="111111", password="secret123", role="customer")
        with mock.patch.object(self.main, "publish") as mock_pub:
            result = self.loop.run_until_complete(self.main.signup(body))
            self.assertIn("id", result)
            self.assertIn("token", result)
            self.assertTrue(mock_pub.called)

    def test_login_success(self):
        self.db.insert_user("u7", "222222", bcrypt.hashpw(b"secret123", bcrypt.gensalt()).decode(), "customer")
        body = self.main.LoginIn(phone="222222", password="secret123")
        with mock.patch.object(self.main, "publish") as mock_pub:
            result = self.loop.run_until_complete(self.main.login(body))
            self.assertIn("id", result)
            self.assertIn("token", result)

    def test_me_endpoint(self):
        self.db.insert_user("u8", "333333", "h", "agent")
        claims = {"sub": "u8"}
        result = self.loop.run_until_complete(self.main.me(claims))
        self.assertEqual(result["id"], "u8")
        self.assertEqual(result["role"], "agent")

    def test_readyz_kafka_down(self):
        with mock.patch.object(self.main, "health", return_value=False):
            with self.assertRaises(self.main.HTTPException) as ctx:
                self.loop.run_until_complete(self.main.readyz())
            self.assertEqual(ctx.exception.status_code, 503)


class TestUserEvents(unittest.TestCase):
    def test_circuit_breaker_same_implementation(self):
        with mock.patch("prometheus_client.Counter"), mock.patch("prometheus_client.make_asgi_app"):
            events = _load_pkg_module("services.user_service.app.events", "services/user-service/app/events.py")
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
            events = _load_pkg_module("services.user_service.app.events", "services/user-service/app/events.py")
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
            events = _load_pkg_module("services.user_service.app.events", "services/user-service/app/events.py")
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
            events = _load_pkg_module("services.user_service.app.events", "services/user-service/app/events.py")
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
            events = _load_pkg_module("services.user_service.app.events", "services/user-service/app/events.py")
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
            events = _load_pkg_module("services.user_service.app.events", "services/user-service/app/events.py")
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
            events = _load_pkg_module("services.user_service.app.events", "services/user-service/app/events.py")
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
