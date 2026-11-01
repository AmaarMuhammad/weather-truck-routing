"""Guaranteeing three distinct route options.

No routing API reliably returns three alternatives for long truck trips (the
provider may return fewer when no "significantly different" route exists, or
time out computing them). When short, we force detours: a via point offset
perpendicular to the main route, tried on both sides at the midpoint, then at
the thirds. A candidate is kept only if it is not a near-duplicate of a route we
already have and is no more than 1.4x the fastest drive time. If three still
can't be found, we return what exists and say so.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from ..engine.geo import bearing, offset_point
from .tomtom import ComputeTimeout, ProviderRoute, RoutingError, calculate_routes

TARGET = 3
MAX_SLOWDOWN = 1.4
DUPLICATE_OVERLAP = 0.9       # share of a route lying on another route
OVERLAP_TOLERANCE_DEG = 0.02  # ~1.4 mi spatial hash cell
US_BBOX = (24.0, -125.0, 50.0, -66.0)  # south, west, north, east


def find_routes(origin, destination, *, load_lb: float,
                depart_at: datetime | None) -> tuple[list[ProviderRoute], str | None]:
    kwargs = {"load_lb": load_lb, "depart_at": depart_at}
    try:
        routes = calculate_routes(origin, destination, max_alternatives=2, **kwargs)
    except ComputeTimeout:
        routes = calculate_routes(origin, destination, max_alternatives=0, **kwargs)
    if not routes:
        raise RoutingError("No truck route found between those locations.")

    routes = _dedupe(routes)
    main = routes[0]
    for fractions in ((0.5,), (1 / 3, 2 / 3)):
        if len(routes) >= TARGET:
            break
        vias = [v for f in fractions for v in _via_candidates(main, f)]
        with ThreadPoolExecutor(max_workers=len(vias) or 1) as pool:
            results = list(pool.map(lambda v: _try_via(origin, destination, v, kwargs), vias))
        fastest = min(r.drive_s for r in routes)
        for cand in results:
            if (cand and len(routes) < TARGET
                    and cand.drive_s <= MAX_SLOWDOWN * fastest
                    and not any(_overlap(cand, r) > DUPLICATE_OVERLAP for r in routes)):
                routes.append(cand)

    notice = None
    if len(routes) < TARGET:
        notice = (f"Only {len(routes)} distinct truck route(s) exist within "
                  f"{MAX_SLOWDOWN:.1f}x the fastest drive time for this trip.")
    return routes[:TARGET], notice


def _via_candidates(route: ProviderRoute, fraction: float) -> list[tuple[float, float]]:
    p = route.profile
    total = p.total_miles
    mile = total * fraction
    here = p.position(mile)
    ahead = p.position(min(total, mile + max(5.0, total * 0.02)))
    heading = bearing(here, ahead)
    offset = min(250.0, max(15.0, total * 0.12))
    out = []
    for side in (90, -90):
        via = offset_point(here, heading + side, offset)
        s, w, n, e = US_BBOX
        if s <= via[0] <= n and w <= via[1] <= e:
            out.append(via)
    return out


def _try_via(origin, destination, via, kwargs) -> ProviderRoute | None:
    try:
        found = calculate_routes(origin, destination, max_alternatives=0, via=via, **kwargs)
    except RoutingError:
        return None
    return found[0] if found else None


def _cells(route: ProviderRoute, step_mi: float = 1.0) -> list[tuple[int, int]]:
    p = route.profile
    n = max(1, int(p.total_miles / step_mi))
    out = []
    for k in range(n + 1):
        lat, lon = p.position(p.total_miles * k / n)
        out.append((round(lat / OVERLAP_TOLERANCE_DEG), round(lon / OVERLAP_TOLERANCE_DEG)))
    return out


def _overlap(a: ProviderRoute, b: ProviderRoute) -> float:
    """Fraction of route ``a`` lying within ~1.4 mi of route ``b``."""
    b_cells = set(_cells(b))
    a_cells = _cells(a)
    near = sum(
        1 for (r, c) in a_cells
        if any((r + dr, c + dc) in b_cells for dr in (-1, 0, 1) for dc in (-1, 0, 1))
    )
    return near / len(a_cells)


def _dedupe(routes: list[ProviderRoute]) -> list[ProviderRoute]:
    kept: list[ProviderRoute] = []
    for r in routes:
        if not any(_overlap(r, k) > DUPLICATE_OVERLAP for k in kept):
            kept.append(r)
    return kept
