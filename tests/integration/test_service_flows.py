import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


def _load_pkg_module(full_name, relpath):
    path = ROOT / relpath
    spec = importlib.util.spec_from_file_location(full_name, path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = full_name.rpartition(".")[0]
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    sys.modules[full_name] = module
    return module


def _make_token(uid, role="customer"):
    secret = "dev-only-change-me"
    alg = "HS256"
    import jwt
    payload = {
        "sub": uid,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + 86400,
    }
    return jwt.encode(payload, secret, algorithm=alg)


class TestOrderPlacementIntegration(unittest.TestCase):
    def test_order_flow_persists_and_publishes_event(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        os.environ["DB_PATH"] = tmp.name
        os.environ["JWT_SECRET"] = "dev-only-change-me"
        os.environ["KAFKA_BOOTSTRAP"] = "localhost:9092"

        try:
            with mock.patch("prometheus_client.Counter"), mock.patch("prometheus_client.make_asgi_app"):
                order_db = _load_pkg_module("services.order_service.app.db", "services/order-service/app/db.py")
                order_events = _load_pkg_module("services.order_service.app.events", "services/order-service/app/events.py")
                order_main = _load_pkg_module("services.order_service.app.main", "services/order-service/app/main.py")

            order_db.DB_PATH = tmp.name
            order_db.init()

            user_id = "integration-user-1"
            token = _make_token(user_id)

            mock_producer = mock.AsyncMock()
            mock_breaker = mock.AsyncMock()
            mock_breaker.allow.return_value = True
            with mock.patch.object(order_events, "producer", return_value=mock_producer), \
                 mock.patch.object(order_events, "_breaker", mock_breaker):
                client = TestClient(order_main.app)
                response = client.post(
                    "/orders",
                    json={"lat": 4.0, "lon": 11.0, "mode": "standard"},
                    headers={"Authorization": f"Bearer {token}"},
                )

            self.assertEqual(response.status_code, 201)
            body = response.json()
            self.assertEqual(body["status"], "ACTIVE")
            order_id = body["order_id"]

            row = order_db.get(order_id)
            self.assertIsNotNone(row)
            self.assertEqual(row["user_id"], user_id)
            self.assertEqual(row["mode"], "standard")

            mock_breaker.allow.assert_called()
            mock_breaker.record_success.assert_called()
            mock_producer.send_and_wait.assert_called_once()
            call_args = mock_producer.send_and_wait.call_args
            self.assertEqual(call_args[0][0], "order.placed")
            self.assertEqual(call_args[1]["key"], order_id)
            event_payload = call_args[1]["value"]
            self.assertEqual(event_payload["order_id"], order_id)
            self.assertEqual(event_payload["user_id"], user_id)
            self.assertEqual(event_payload["mode"], "standard")
        finally:
            os.environ.pop("DB_PATH", None)
            os.environ.pop("JWT_SECRET", None)
            os.environ.pop("KAFKA_BOOTSTRAP", None)


class TestUserRegistrationOrderAssociation(unittest.TestCase):
    def test_signup_then_place_order_links_user(self):
        user_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        user_tmp.close()
        order_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        order_tmp.close()

        os.environ["DB_PATH"] = user_tmp.name
        os.environ["JWT_SECRET"] = "dev-only-change-me"
        os.environ["KAFKA_BOOTSTRAP"] = "localhost:9092"

        try:
            with mock.patch("prometheus_client.Counter"), mock.patch("prometheus_client.make_asgi_app"):
                user_db = _load_pkg_module("services.user_service.app.db", "services/user-service/app/db.py")
                user_events = _load_pkg_module("services.user_service.app.events", "services/user-service/app/events.py")
                user_main = _load_pkg_module("services.user_service.app.main", "services/user-service/app/main.py")

            user_db.DB_PATH = user_tmp.name
            user_db.init()

            mock_producer = mock.AsyncMock()
            mock_breaker = mock.AsyncMock()
            mock_breaker.allow.return_value = True
            with mock.patch.object(user_events, "producer", return_value=mock_producer), \
                 mock.patch.object(user_events, "_breaker", mock_breaker):
                client = TestClient(user_main.app)
                signup_resp = client.post(
                    "/signup",
                    json={"phone": "111222", "password": "secret123", "role": "customer"},
                )

            self.assertEqual(signup_resp.status_code, 201)
            signup_body = signup_resp.json()
            user_id = signup_body["id"]
            token = signup_body["token"]

            mock_breaker.allow.assert_called()
            mock_breaker.record_success.assert_called()
            mock_producer.send_and_wait.assert_called_once()
            event_call = mock_producer.send_and_wait.call_args
            self.assertEqual(event_call[0][0], "user.registered")
            self.assertEqual(event_call[1]["value"]["id"], user_id)

            os.environ["DB_PATH"] = order_tmp.name
            with mock.patch("prometheus_client.Counter"), mock.patch("prometheus_client.make_asgi_app"):
                order_db = _load_pkg_module("services.order_service.app.db", "services/order-service/app/db.py")
                order_events = _load_pkg_module("services.order_service.app.events", "services/order-service/app/events.py")
                order_main = _load_pkg_module("services.order_service.app.main", "services/order-service/app/main.py")

            order_db.DB_PATH = order_tmp.name
            order_db.init()

            order_mock_producer = mock.AsyncMock()
            order_mock_breaker = mock.AsyncMock()
            order_mock_breaker.allow.return_value = True
            with mock.patch.object(order_events, "producer", return_value=order_mock_producer), \
                 mock.patch.object(order_events, "_breaker", order_mock_breaker):
                order_client = TestClient(order_main.app)
                order_resp = order_client.post(
                    "/orders",
                    json={"lat": 4.0, "lon": 11.0, "mode": "express"},
                    headers={"Authorization": f"Bearer {token}"},
                )

            self.assertEqual(order_resp.status_code, 201)
            order_body = order_resp.json()
            self.assertEqual(order_body["status"], "ACTIVE")
            order_id = order_body["order_id"]

            row = order_db.get(order_id)
            self.assertIsNotNone(row)
            self.assertEqual(row["user_id"], user_id)
            self.assertEqual(row["mode"], "express")
        finally:
            os.environ.pop("DB_PATH", None)
            os.environ.pop("JWT_SECRET", None)
            os.environ.pop("KAFKA_BOOTSTRAP", None)


if __name__ == "__main__":
    unittest.main()
