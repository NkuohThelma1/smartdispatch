"""Pattern: Strategy. Plug-in matching algorithms for choosing a delivery agent.

Switch via env MATCHER=nearest|credibility.
"""
from __future__ import annotations
import math
import os
from typing import Iterable, Protocol


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


class Agent(Protocol):
    id: str
    lat: float
    lon: float
    credibility: float


class Matcher(Protocol):
    def pick(self, customer_lat: float, customer_lon: float, agents: Iterable) -> dict | None: ...


class NearestMatcher:
    def pick(self, customer_lat, customer_lon, agents):
        best = None
        best_d = float("inf")
        for a in agents:
            d = haversine_m(customer_lat, customer_lon, a["lat"], a["lon"])
            if d < best_d:
                best, best_d = a, d
        return {"id": best["id"], "distance_m": best_d} if best else None


class CredibilityWeightedMatcher:
    """Score = credibility / (distance_km + 1). Higher score wins."""
    def pick(self, customer_lat, customer_lon, agents):
        best = None
        best_score = -1.0
        for a in agents:
            d_km = haversine_m(customer_lat, customer_lon, a["lat"], a["lon"]) / 1000.0
            score = a["credibility"] / (d_km + 1.0)
            if score > best_score:
                best, best_score = a, score
        if not best:
            return None
        return {"id": best["id"], "score": best_score}


def matcher() -> Matcher:
    name = os.getenv("MATCHER", "nearest").lower()
    if name == "credibility":
        return CredibilityWeightedMatcher()
    return NearestMatcher()