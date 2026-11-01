from __future__ import annotations

import math
from bisect import bisect_left

METERS_PER_MILE = 1609.344
EARTH_RADIUS_MI = 3958.7613


def haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return EARTH_RADIUS_MI * 2 * math.asin(math.sqrt(min(1.0, h)))


def cumulative_miles(points: list[tuple[float, float]]) -> list[float]:
    out = [0.0]
    for a, b in zip(points, points[1:]):
        out.append(out[-1] + haversine_miles(a, b))
    return out


def interp(xs: list[float], ys: list[float], x: float) -> float:
    """Piecewise-linear y(x) for ascending ``xs``; clamps outside the range."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect_left(xs, x)
    x0, x1 = xs[i - 1], xs[i]
    if x1 == x0:
        return ys[i]
    f = (x - x0) / (x1 - x0)
    return ys[i - 1] + (ys[i] - ys[i - 1]) * f


def offset_point(origin: tuple[float, float], bearing_deg: float,
                 distance_mi: float) -> tuple[float, float]:
    """Destination point given start, bearing and distance (great circle)."""
    lat1, lon1 = map(math.radians, origin)
    brg = math.radians(bearing_deg)
    d = distance_mi / EARTH_RADIUS_MI
    lat2 = math.asin(math.sin(lat1) * math.cos(d)
                     + math.cos(lat1) * math.sin(d) * math.cos(brg))
    lon2 = lon1 + math.atan2(math.sin(brg) * math.sin(d) * math.cos(lat1),
                             math.cos(d) - math.sin(lat1) * math.sin(lat2))
    return math.degrees(lat2), (math.degrees(lon2) + 540) % 360 - 180


def simplify(points: list[tuple[float, float]], tolerance_deg: float) -> list[tuple[float, float]]:
    """Ramer–Douglas–Peucker in plain lat/lon (iterative). Only used to shrink
    polylines for drawing; all calculations use the full geometry."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    tol2 = tolerance_deg ** 2
    while stack:
        i, j = stack.pop()
        (ay, ax), (by, bx) = points[i], points[j]
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        best, best_d = -1, tol2
        for k in range(i + 1, j):
            py, px = points[k]
            if seg2 == 0:
                d = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
                d = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if d > best_d:
                best, best_d = k, d
        if best >= 0:
            keep[best] = True
            stack.extend(((i, best), (best, j)))
    return [p for p, k in zip(points, keep) if k]


def bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = (math.cos(lat1) * math.sin(lat2)
         - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1))
    return (math.degrees(math.atan2(y, x)) + 360) % 360
