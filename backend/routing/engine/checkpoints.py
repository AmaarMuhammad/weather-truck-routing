"""Checkpoints along a route and the truck's arrival time at each.

A route is described by its polyline plus, for every polyline point, the
provider's cumulative distance and cumulative driving time. Checkpoints sit at
exact N-mile marks (interpolated, not snapped to polyline vertices), plus the
origin and the destination. ETA = departure + driving time to that mile + any
HOS rests taken before it.
"""
from __future__ import annotations

from dataclasses import dataclass

from .geo import interp
from .hos import HosClock

TRACK_STEP_MI = 5.0
_MIN_TAIL_MI = 0.05  # a final mark closer than this to the destination is merged


class RouteProfile:
    def __init__(self, points: list[tuple[float, float]], cum_miles: list[float],
                 cum_drive_s: list[float]):
        if len(points) < 2 or not (len(points) == len(cum_miles) == len(cum_drive_s)):
            raise ValueError("Route profile needs >=2 points with matching progress.")
        self.points = points
        self.cum_miles = cum_miles
        self.cum_drive_s = cum_drive_s
        self._lats = [p[0] for p in points]
        self._lons = [p[1] for p in points]

    @property
    def total_miles(self) -> float:
        return self.cum_miles[-1]

    @property
    def total_drive_s(self) -> float:
        return self.cum_drive_s[-1]

    def position(self, mile: float) -> tuple[float, float]:
        return (interp(self.cum_miles, self._lats, mile),
                interp(self.cum_miles, self._lons, mile))

    def drive_s_at(self, mile: float) -> float:
        return interp(self.cum_miles, self.cum_drive_s, mile)

    def mile_at_drive_s(self, drive_s: float) -> float:
        return interp(self.cum_drive_s, self.cum_miles, drive_s)


def checkpoint_miles(total_miles: float, interval_mi: float) -> list[float]:
    if interval_mi <= 0:
        raise ValueError("interval must be positive")
    marks = []
    m = 0.0
    while m < total_miles - _MIN_TAIL_MI:
        marks.append(m)
        m += interval_mi
    marks.append(total_miles)
    return marks


def coverage(marks: list[float]) -> list[float]:
    """Miles each checkpoint represents (midpoint rule). Sums to the route
    length, so per-level mileage always reconciles with the route distance."""
    if len(marks) == 1:
        return [0.0]
    out = []
    for i, m in enumerate(marks):
        lo = m if i == 0 else (marks[i - 1] + m) / 2
        hi = m if i == len(marks) - 1 else (m + marks[i + 1]) / 2
        out.append(hi - lo)
    return out


@dataclass(frozen=True)
class Checkpoint:
    index: int
    mile: float
    lat: float
    lon: float
    drive_s: float
    elapsed_s: float
    coverage_mi: float


def build_checkpoints(profile: RouteProfile, interval_mi: float,
                      clock: HosClock) -> list[Checkpoint]:
    marks = checkpoint_miles(profile.total_miles, interval_mi)
    out = []
    for i, (mile, cov) in enumerate(zip(marks, coverage(marks))):
        lat, lon = profile.position(mile)
        drive_s = profile.drive_s_at(mile)
        out.append(Checkpoint(i, mile, lat, lon, drive_s, clock.elapsed(drive_s), cov))
    return out


def rest_stops(profile: RouteProfile, clock: HosClock) -> list[dict]:
    out = []
    for r in clock.rests:
        mile = profile.mile_at_drive_s(r.at_drive_s)
        lat, lon = profile.position(mile)
        out.append({
            "kind": r.kind,
            "mile": mile,
            "lat": lat,
            "lon": lon,
            "start_s": clock.elapsed(r.at_drive_s),
            "duration_s": r.duration_s,
        })
    return out


def track(profile: RouteProfile, clock: HosClock) -> list[tuple[float, float, float]]:
    """(elapsed_s, lat, lon) knots for animating the truck's position. Rests
    appear as two knots at the same place so the truck waits there."""
    knots = []
    for mile in checkpoint_miles(profile.total_miles, TRACK_STEP_MI):
        lat, lon = profile.position(mile)
        knots.append((clock.elapsed(profile.drive_s_at(mile)), lat, lon))
    for stop in rest_stops(profile, clock):
        knots.append((stop["start_s"], stop["lat"], stop["lon"]))
        knots.append((stop["start_s"] + stop["duration_s"], stop["lat"], stop["lon"]))
    knots.sort(key=lambda k: k[0])
    return knots
