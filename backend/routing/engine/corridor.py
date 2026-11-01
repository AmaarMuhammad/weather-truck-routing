"""Heatmap grid over the trip corridor, and coordinate snapping for weather
de-duplication.

The corridor is every grid cell whose centre lies within ``buffer_mi`` of any
route. Cell size adapts so the corridor stays under ``max_cells`` — the weather
API bills per location, so a cross-country trip gets coarser cells rather than
a quota-busting request. Cells are roughly square on the ground (the longitude
step is stretched by 1/cos(latitude)).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .geo import cumulative_miles, haversine_miles, interp

MILES_PER_DEG_LAT = 69.05
STEPS_DEG = [0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.75, 1.0, 1.25, 1.5, 2.0]
SAMPLE_STEP_MI = 5.0


@dataclass
class Grid:
    lat0: float          # centre latitude of row 0 (southernmost)
    lon0: float          # centre longitude of column 0 (westernmost)
    dlat: float
    dlon: float
    nrows: int
    ncols: int
    cells: list[tuple[int, int]] = field(default_factory=list)  # (row, col) in corridor

    def center(self, row: int, col: int) -> tuple[float, float]:
        return (round(self.lat0 + row * self.dlat, 4),
                round(self.lon0 + col * self.dlon, 4))

    def as_dict(self) -> dict:
        return {
            "lat0": self.lat0, "lon0": self.lon0,
            "dlat": self.dlat, "dlon": self.dlon,
            "nrows": self.nrows, "ncols": self.ncols,
            "cells": [list(c) for c in self.cells],
        }


def _resample(points: list[tuple[float, float]], step_mi: float) -> list[tuple[float, float]]:
    cum = cumulative_miles(points)
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    n = max(1, math.ceil(cum[-1] / step_mi))
    return [(interp(cum, lats, cum[-1] * k / n), interp(cum, lons, cum[-1] * k / n))
            for k in range(n + 1)]


def build_corridor(routes: list[list[tuple[float, float]]], buffer_mi: float = 25.0,
                   max_cells: int = 300) -> Grid:
    samples = [p for r in routes for p in _resample(r, SAMPLE_STEP_MI)]
    mid_lat = (min(p[0] for p in samples) + max(p[0] for p in samples)) / 2
    cos_mid = max(0.2, math.cos(math.radians(mid_lat)))

    grid = None
    for step in STEPS_DEG:
        grid = _grid_for_step(samples, step, step / cos_mid, buffer_mi)
        if len(grid.cells) <= max_cells:
            break
    return grid


def _grid_for_step(samples, dlat, dlon, buffer_mi) -> Grid:
    # never let cells get so big that the route slips between cell centres
    step_mi = dlat * MILES_PER_DEG_LAT
    radius = max(buffer_mi, 0.75 * step_mi)
    pad_lat = radius / MILES_PER_DEG_LAT + dlat
    lat0 = math.floor((min(p[0] for p in samples) - pad_lat) / dlat) * dlat
    lat1 = max(p[0] for p in samples) + pad_lat
    pad_lon = pad_lat * dlon / dlat
    lon0 = math.floor((min(p[1] for p in samples) - pad_lon) / dlon) * dlon
    lon1 = max(p[1] for p in samples) + pad_lon
    nrows = int((lat1 - lat0) / dlat) + 1
    ncols = int((lon1 - lon0) / dlon) + 1
    grid = Grid(round(lat0, 6), round(lon0, 6), dlat, dlon, nrows, ncols)

    span_r = int(math.ceil(radius / (dlat * MILES_PER_DEG_LAT))) + 1
    marked: set[tuple[int, int]] = set()
    for lat, lon in samples:
        r0 = round((lat - lat0) / dlat)
        c0 = round((lon - lon0) / dlon)
        col_mi = dlon * MILES_PER_DEG_LAT * max(0.2, math.cos(math.radians(lat)))
        span_c = int(math.ceil(radius / col_mi)) + 1
        for r in range(max(0, r0 - span_r), min(nrows, r0 + span_r + 1)):
            for c in range(max(0, c0 - span_c), min(ncols, c0 + span_c + 1)):
                if (r, c) not in marked and haversine_miles((lat, lon), grid.center(r, c)) <= radius:
                    marked.add((r, c))
    grid.cells = sorted(marked)
    return grid


def snap(lat: float, lon: float, step: float = 0.1) -> tuple[float, float]:
    return (round(round(lat / step) * step, 4), round(round(lon / step) * step, 4))
