"""Hours-of-Service rests layered on top of pure driving time.

Routing APIs return continuous driving time; a real truck cannot drive 18 hours
straight, and the weather at a checkpoint depends on when the truck actually
gets there. Rules (FMCSA, property-carrying, driver starts fresh):
  * 30-minute break after 8 cumulative hours of driving;
  * 10 consecutive hours off duty after 11 hours of driving.
The 14-hour window never binds here (11 h driving + 0.5 h break < 14 h, with no
other on-duty work), and the 70-hour cycle is not reached by a fresh driver
within the 48 h–5 day trips this app plans.

Ported from the clock logic of the ELD planner (hos_engine/planner.py).
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass

HOUR = 3600.0
DRIVE_LIMIT_S = 11 * HOUR
BREAK_AFTER_S = 8 * HOUR
BREAK_S = 0.5 * HOUR
RESET_S = 10 * HOUR

_EPS = 1e-6


@dataclass(frozen=True)
class Rest:
    at_drive_s: float     # cumulative driving time when the rest starts
    duration_s: float
    kind: str             # "break" | "rest"


def plan_rests(total_drive_s: float) -> list[Rest]:
    """Rests required to drive ``total_drive_s``. None is inserted at the very
    end of the trip — the driver has arrived."""
    rests: list[Rest] = []
    t = since_break = since_reset = 0.0
    while True:
        to_break = BREAK_AFTER_S - since_break
        to_reset = DRIVE_LIMIT_S - since_reset
        step = min(to_break, to_reset)
        if t + step >= total_drive_s - _EPS:
            return rests
        t += step
        since_break += step
        since_reset += step
        if to_reset <= to_break + _EPS:
            rests.append(Rest(t, RESET_S, "rest"))
            since_break = since_reset = 0.0
        else:
            rests.append(Rest(t, BREAK_S, "break"))
            since_break = 0.0


class HosClock:
    """Maps cumulative driving time to elapsed trip time."""

    def __init__(self, rests: list[Rest]):
        self.rests = rests
        self._starts = [r.at_drive_s for r in rests]
        self._offsets = [0.0]
        for r in rests:
            self._offsets.append(self._offsets[-1] + r.duration_s)

    def elapsed(self, drive_s: float) -> float:
        """Elapsed seconds when the truck has driven ``drive_s``. A point
        reached exactly when a rest starts is reached *before* that rest."""
        return drive_s + self._offsets[bisect_left(self._starts, drive_s - _EPS)]

    @property
    def total_rest_s(self) -> float:
        return self._offsets[-1]


NO_HOS = HosClock([])
