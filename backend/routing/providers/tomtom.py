"""TomTom Calculate Route — truck routing with alternatives.

Each route comes back with its polyline and a sparse ``progress`` array of
(pointIndex, cumulative distance, cumulative travel time). We turn that into a
per-point profile so ETA can be read at any mile.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import requests
from django.conf import settings

from ..engine.checkpoints import RouteProfile
from ..engine.geo import METERS_PER_MILE, cumulative_miles, interp

BASE_URL = "https://api.tomtom.com/routing/1/calculateRoute"
LB_TO_KG = 0.45359237
ASSUMED_TARE_LB = 35_000      # empty tractor + 53' trailer
MAX_GROSS_LB = 80_000         # federal gross vehicle weight limit
# Without a cap TomTom times trucks at posted limits (~73 mph average on
# Chicago->Denver); fleets typically govern trucks at about 65 mph.
GOVERNED_SPEED_KMH = 105
_TIMEOUT = 40


class RoutingError(Exception):
    pass


class ComputeTimeout(RoutingError):
    """TomTom gave up computing (long trip + alternatives); retry with fewer."""


@dataclass
class ProviderRoute:
    profile: RouteProfile
    length_mi: float
    drive_s: float
    traffic_delay_s: float
    via: tuple[float, float] | None = None


def gross_weight_kg(load_lb: float) -> int:
    return round(min(load_lb + ASSUMED_TARE_LB, MAX_GROSS_LB) * LB_TO_KG)


def _fmt(p: tuple[float, float]) -> str:
    return f"{p[0]:.6f},{p[1]:.6f}"


def calculate_routes(origin: tuple[float, float], destination: tuple[float, float], *,
                     load_lb: float, depart_at: datetime | None,
                     max_alternatives: int = 2,
                     via: tuple[float, float] | None = None,
                     via_radius_m: int = 15_000) -> list[ProviderRoute]:
    if not settings.TOMTOM_API_KEY:
        raise RoutingError("TOMTOM_API_KEY is not configured on the server.")
    locations = [_fmt(origin)]
    if via:
        # a circle waypoint steers the route without adding a leg or a stop
        locations.append(f"circle({_fmt(via)},{via_radius_m})")
    locations.append(_fmt(destination))
    params = {
        "key": settings.TOMTOM_API_KEY,
        "travelMode": "truck",
        "vehicleCommercial": "true",
        "vehicleWeight": gross_weight_kg(load_lb),
        "vehicleMaxSpeed": GOVERNED_SPEED_KMH,
        "routeType": "fastest",
        "traffic": "true",
        "maxAlternatives": max_alternatives,
        "routeRepresentation": "polyline",
        "extendedRouteRepresentation": ["distance", "travelTime"],
        "computeTravelTimeFor": "none",
    }
    if max_alternatives > 0:  # TomTom rejects alternativeType with maxAlternatives=0
        params["alternativeType"] = "anyRoute"
    if depart_at is not None:
        params["departAt"] = depart_at.isoformat(timespec="seconds")
    try:
        resp = requests.get(f"{BASE_URL}/{':'.join(locations)}/json",
                            params=params, timeout=_TIMEOUT)
    except requests.Timeout as exc:
        raise ComputeTimeout("Routing service timed out.") from exc
    except requests.RequestException as exc:
        # never echo exc: its message includes the request URL, API key and all
        raise RoutingError("Routing service unavailable.") from exc

    if resp.status_code != 200:
        detail = _error_message(resp)
        if resp.status_code >= 500:
            raise ComputeTimeout(detail or "Routing service failed to compute a route.")
        if resp.status_code in (401, 403):
            raise RoutingError("Routing service rejected the API key.")
        raise RoutingError(detail or "No truck route found between those locations.")
    return [_parse_route(r, via) for r in resp.json().get("routes", [])]


def _error_message(resp: requests.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return ""
    err = body.get("detailedError") or body.get("error") or {}
    return err.get("message", "") if isinstance(err, dict) else str(err)


def _parse_route(route: dict, via) -> ProviderRoute:
    points = [(p["latitude"], p["longitude"]) for leg in route["legs"] for p in leg["points"]]
    summary = route["summary"]
    total_m = summary["lengthInMeters"]
    total_s = summary["travelTimeInSeconds"]

    # progress is sparse: interpolate distance/time at every point, using
    # geometric distance along the polyline as the common axis
    geo_cum = cumulative_miles(points)
    knots = sorted(route.get("progress") or [], key=lambda k: k["pointIndex"])
    if not knots or knots[0]["pointIndex"] != 0:
        knots.insert(0, {"pointIndex": 0, "distanceInMeters": 0, "travelTimeInSeconds": 0})
    if knots[-1]["pointIndex"] != len(points) - 1:
        knots.append({"pointIndex": len(points) - 1, "distanceInMeters": total_m,
                      "travelTimeInSeconds": total_s})
    kx = [geo_cum[k["pointIndex"]] for k in knots]
    kd = [k["distanceInMeters"] / METERS_PER_MILE for k in knots]
    kt = [float(k["travelTimeInSeconds"]) for k in knots]
    cum_mi = [interp(kx, kd, x) for x in geo_cum]
    cum_s = [interp(kx, kt, x) for x in geo_cum]

    return ProviderRoute(
        profile=RouteProfile(points, cum_mi, cum_s),
        length_mi=total_m / METERS_PER_MILE,
        drive_s=float(total_s),
        traffic_delay_s=float(summary.get("trafficDelayInSeconds", 0)),
        via=via,
    )
