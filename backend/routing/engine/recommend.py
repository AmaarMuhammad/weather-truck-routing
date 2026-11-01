"""Per-route risk summary and the recommendation.

Ranking is strict lexicographic over the brief's preference list, with two keys
added in front. A route that crosses No Travel weather must never beat one that
doesn't just because it has fewer Severe miles, and a route whose forecast is
missing must never win on Severe/High miles it was never measured on.

  0. fewest No Travel miles   (added)
  1. fewest Unknown miles     (added)
  2. fewest Severe miles
  3. fewest High miles
  4. lowest average risk      (distance-weighted, Low=0 .. No Travel=4)
  5. shortest travel time     (elapsed, including HOS rests)

Miles compare at 0.1 mi, average risk at 0.01, time at the minute, so float
noise never decides a key.
"""
from __future__ import annotations

from dataclasses import dataclass

from .risk import Level

LEVEL_KEYS = ["low", "moderate", "high", "severe", "no_travel"]
RANK_KEYS = ["no_travel_miles", "unknown_miles", "severe_miles", "high_miles", "avg_risk",
             "travel_time"]


@dataclass(frozen=True)
class RouteScore:
    route_id: str
    miles_by_level: dict[str, float]   # LEVEL_KEYS + "unknown"
    avg_risk: float | None             # over miles with known weather
    elapsed_s: float

    @property
    def rank_tuple(self) -> tuple:
        m = self.miles_by_level
        return (
            round(m["no_travel"], 1),
            round(m["unknown"], 1),
            round(m["severe"], 1),
            round(m["high"], 1),
            round(self.avg_risk, 2) if self.avg_risk is not None else float("inf"),
            round(self.elapsed_s / 60),
        )


def score_route(route_id: str, levels: list[Level | None], coverage_mi: list[float],
                elapsed_s: float) -> RouteScore:
    miles = {k: 0.0 for k in LEVEL_KEYS + ["unknown"]}
    weighted = known = 0.0
    for level, cov in zip(levels, coverage_mi):
        if level is None:
            miles["unknown"] += cov
            continue
        miles[LEVEL_KEYS[level]] += cov
        weighted += int(level) * cov
        known += cov
    return RouteScore(
        route_id=route_id,
        miles_by_level=miles,
        avg_risk=weighted / known if known > 0 else None,
        elapsed_s=elapsed_s,
    )


@dataclass(frozen=True)
class Recommendation:
    route_id: str
    ranking: list[str]
    deciding_key: str | None       # None when there is only one route or a full tie
    runner_up_id: str | None
    all_no_travel: bool
    has_unknown: bool

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def recommend(scores: list[RouteScore]) -> Recommendation:
    """Scores must be in provider order (fastest first) — that order breaks
    exact ties."""
    if not scores:
        raise ValueError("no routes to rank")
    ranked = sorted(scores, key=lambda s: s.rank_tuple)  # stable
    best = ranked[0]
    deciding = runner = None
    if len(ranked) > 1:
        runner = ranked[1]
        for key, a, b in zip(RANK_KEYS, best.rank_tuple, runner.rank_tuple):
            if a != b:
                deciding = key
                break
    return Recommendation(
        route_id=best.route_id,
        ranking=[s.route_id for s in ranked],
        deciding_key=deciding,
        runner_up_id=runner.route_id if runner else None,
        all_no_travel=all(s.miles_by_level["no_travel"] > 0 for s in scores),
        has_unknown=any(s.miles_by_level["unknown"] > 0 for s in scores),
    )
