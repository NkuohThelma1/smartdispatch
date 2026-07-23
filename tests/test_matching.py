import importlib.util
import os
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MATCHING_PATH = ROOT / "services" / "delivery-service" / "app" / "matching.py"


def load_matching_module():
    spec = importlib.util.spec_from_file_location("delivery_service_matching", MATCHING_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class MatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ.pop("MATCHER", None)

    def test_haversine_is_zero_for_identical_points(self):
        matching = load_matching_module()
        self.assertAlmostEqual(matching.haversine_m(4.0, 11.0, 4.0, 11.0), 0.0, places=6)

    def test_nearest_matcher_picks_closest_agent(self):
        matching = load_matching_module()
        matcher = matching.NearestMatcher()
        result = matcher.pick(
            4.0,
            11.0,
            [
                {"id": "far", "lat": 5.0, "lon": 12.0, "credibility": 10.0},
                {"id": "near", "lat": 4.01, "lon": 11.01, "credibility": 1.0},
            ],
        )
        self.assertEqual(result["id"], "near")

    def test_factory_uses_credibility_mode(self):
        os.environ["MATCHER"] = "credibility"
        matching = load_matching_module()
        matcher = matching.matcher()
        self.assertEqual(matcher.__class__.__name__, "CredibilityWeightedMatcher")

    def test_credibility_matcher_picks_higher_credibility(self):
        matching = load_matching_module()
        matcher = matching.CredibilityWeightedMatcher()
        result = matcher.pick(
            4.0,
            11.0,
            [
                {"id": "low", "lat": 4.0, "lon": 11.0, "credibility": 0.5},
                {"id": "high", "lat": 4.0, "lon": 11.0, "credibility": 10.0},
            ],
        )
        self.assertEqual(result["id"], "high")

    def test_credibility_matcher_empty_agents(self):
        matching = load_matching_module()
        matcher = matching.CredibilityWeightedMatcher()
        result = matcher.pick(4.0, 11.0, [])
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
