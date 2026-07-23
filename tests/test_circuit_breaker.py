import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
EVENTS_PATH = ROOT / "services" / "delivery-service" / "app" / "events.py"


def _load_events_module():
    sys.modules["aiokafka"] = mock.MagicMock()
    spec = importlib.util.spec_from_file_location("test_events_cb", EVENTS_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


_MODULE = _load_events_module()
CircuitBreaker = _MODULE.CircuitBreaker


class TestCircuitBreaker(unittest.IsolatedAsyncioTestCase):
    async def test_closed_remains_true_below_threshold(self):
        cb = CircuitBreaker(fail_threshold=3, reset_after_s=30.0)
        self.assertTrue(await cb.allow())
        self.assertTrue(await cb.allow())
        self.assertTrue(await cb.allow())

    async def test_closed_opens_after_threshold_failures(self):
        cb = CircuitBreaker(fail_threshold=3, reset_after_s=30.0)
        for _ in range(3):
            self.assertTrue(await cb.allow())
        await cb.record_failure()
        await cb.record_failure()
        await cb.record_failure()
        self.assertFalse(await cb.allow())

    async def test_open_blocks_calls_before_cooldown(self):
        cb = CircuitBreaker(fail_threshold=2, reset_after_s=10.0)
        await cb.record_failure()
        await cb.record_failure()
        self.assertFalse(await cb.allow())

    async def test_open_transitions_to_half_open_after_cooldown(self):
        cb = CircuitBreaker(fail_threshold=2, reset_after_s=0.1)
        await cb.record_failure()
        await cb.record_failure()
        self.assertFalse(await cb.allow())
        await asyncio.sleep(0.2)
        self.assertTrue(await cb.allow())
        self.assertFalse(await cb.allow())

    async def test_half_open_closes_on_success(self):
        cb = CircuitBreaker(fail_threshold=2, reset_after_s=0.1)
        await cb.record_failure()
        await cb.record_failure()
        await asyncio.sleep(0.2)
        self.assertTrue(await cb.allow())
        await cb.record_success()
        self.assertTrue(await cb.allow())

    async def test_half_open_reopens_on_failure(self):
        cb = CircuitBreaker(fail_threshold=2, reset_after_s=0.1)
        await cb.record_failure()
        await cb.record_failure()
        await asyncio.sleep(0.2)
        self.assertTrue(await cb.allow())
        await cb.record_failure()
        self.assertFalse(await cb.allow())

    async def test_success_resets_failure_count_in_closed(self):
        cb = CircuitBreaker(fail_threshold=3, reset_after_s=30.0)
        await cb.record_failure()
        await cb.record_success()
        await cb.record_failure()
        await cb.record_failure()
        self.assertTrue(await cb.allow())

    async def test_concurrent_half_open_allows_only_one(self):
        cb = CircuitBreaker(fail_threshold=2, reset_after_s=0.1)
        await cb.record_failure()
        await cb.record_failure()
        await asyncio.sleep(0.2)
        results = await asyncio.gather(
            cb.allow(),
            cb.allow(),
            cb.allow(),
        )
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 2)


if __name__ == "__main__":
    unittest.main()