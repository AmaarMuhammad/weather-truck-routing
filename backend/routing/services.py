"""Trip planning pipeline: routes -> checkpoints & ETAs -> weather -> risk ->
recommendation, plus the corridor heatmap frames for the 0–48 h slider."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .engine.checkpoints import build_checkpoints, rest_stops, track
from .engine.corridor import build_corridor, snap
from .engine.geo import simplify
from .engine.hos import NO_HOS, HosClock, plan_rests
from .engine.recommend import recommend, score_route
from .engine.risk import assess, rules_payload
from .engine.weather import hour_slice, sample_at
from .providers import alternatives, open_meteo

HEATMAP_HOURS = 49                 # slider positions 0..48
FORECAST_HORIZON = timedelta(days=15)
CORRIDOR_BUFFER_MI = 25.0
# Open-Meteo's free tier bills per location (600/min), so one plan gets a fixed
# location budget: checkpoints first, the heatmap gets what is left.
WEATHER_BUDGET = 500
MAX_HEATMAP_CELLS = 220
MIN_HEATMAP_CELLS = 60
SNAP_STEPS_DEG = (0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5)
DRAW_TOLERANCE_DEG = 0.0008        # ~80 m; only affects drawn polylines
ROUTE_IDS = "ABC"


@dataclass
class TripRequest:
    origin: dict          # {"label", "lat", "lon"}
    destination: dict
    departure: datetime   # aware
    load_lb: float
    interval_mi: int
    hos: bool = True


def plan_trip(req: TripRequest, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    departure = max(req.departure.astimezone(timezone.utc), now)
    origin = (req.origin["lat"], req.origin["lon"])
    destination = (req.destination["lat"], req.destination["lon"])

    found, notice = alternatives.find_routes(
        origin, destination, load_lb=req.load_lb,
        depart_at=req.departure if req.departure > now else None,
    )

    # 1. checkpoints and ETAs per route
    routes = []
    for rid, pr in zip(ROUTE_IDS, found):
        clock = HosClock(plan_rests(pr.drive_s)) if req.hos else NO_HOS
        routes.append({
            "id": rid,
            "provider": pr,
            "clock": clock,
            "checkpoints": build_checkpoints(pr.profile, req.interval_mi, clock),
        })

    # 2. weather for every (snapped) checkpoint and heatmap cell, in one batch
    all_cps = [c for r in routes for c in r["checkpoints"]]
    for snap_step in SNAP_STEPS_DEG:
        cp_points = list(dict.fromkeys(snap(c.lat, c.lon, snap_step) for c in all_cps))
        if len(cp_points) <= WEATHER_BUDGET - MIN_HEATMAP_CELLS:
            break
    if snap_step > SNAP_STEPS_DEG[0]:
        notice_snap = (f"Long trip: checkpoint weather is read on a {snap_step}° grid "
                       "to stay within the weather service's free quota.")
    else:
        notice_snap = None
    grid = build_corridor([simplify(r["provider"].profile.points, 0.01) for r in routes],
                          buffer_mi=CORRIDOR_BUFFER_MI,
                          max_cells=max(MIN_HEATMAP_CELLS,
                                        min(MAX_HEATMAP_CELLS, WEATHER_BUDGET - len(cp_points))))
    cell_points = [grid.center(r, c) for r, c in grid.cells]
    dep_s = departure.timestamp()
    start_h = int(dep_s // 3600)
    last_eta_s = max(r["checkpoints"][-1].elapsed_s for r in routes) + dep_s
    end_h = math.ceil(max(dep_s + HEATMAP_HOURS * 3600, last_eta_s) / 3600) + 1
    end_h = min(end_h, int((now + FORECAST_HORIZON).timestamp() // 3600))
    weather, warnings = open_meteo.fetch_hourly(cp_points + cell_points, start_h, end_h)

    # 3. risk per checkpoint, route scores, recommendation
    scores = []
    for r in routes:
        levels, cps = [], []
        for c in r["checkpoints"]:
            series = weather.get(snap(c.lat, c.lon, snap_step))
            eta_s = dep_s + c.elapsed_s
            s = sample_at(series, eta_s) if series else None
            a = assess(s.wind, s.rain, s.snow, req.load_lb) if s else None
            levels.append(a.level if a else None)
            cps.append(_checkpoint_json(c, eta_s, s, a))
        score = score_route(r["id"], levels, [c.coverage_mi for c in r["checkpoints"]],
                            r["checkpoints"][-1].elapsed_s)
        scores.append(score)
        r["checkpoints_json"] = cps
        r["score"] = score
    rec = recommend(scores)

    return {
        "inputs": {
            "origin": req.origin, "destination": req.destination,
            "departure": departure.isoformat(), "load_lb": req.load_lb,
            "interval_mi": req.interval_mi, "hos": req.hos,
        },
        "routes": [_route_json(r, dep_s) for r in routes],
        "recommendation": rec.as_dict(),
        "heatmap": _heatmap_json(grid, cell_points, weather, start_h),
        "rules": rules_payload(),
        "notices": [n for n in [notice, notice_snap] if n] + warnings,
    }


def _iso(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, tz=timezone.utc).isoformat(timespec="seconds")


def _checkpoint_json(c, eta_s, sample, assessment) -> dict:
    out = {
        "mile": round(c.mile, 2),
        "lat": round(c.lat, 5),
        "lon": round(c.lon, 5),
        "eta": _iso(eta_s),
        "coverage_mi": round(c.coverage_mi, 3),
        "level": int(assessment.level) if assessment else None,
    }
    if sample:
        out.update(wind=round(sample.wind, 1),
                   gust=None if sample.gust is None else round(sample.gust, 1),
                   rain=round(sample.rain, 3), snow=round(sample.snow, 3))
    if assessment:
        out.update(drivers=assessment.drivers, load_escalated=assessment.load_escalated)
    return out


def _route_json(r: dict, dep_s: float) -> dict:
    pr, score = r["provider"], r["score"]
    return {
        "id": r["id"],
        "geometry": [[round(lat, 5), round(lon, 5)]
                     for lat, lon in simplify(pr.profile.points, DRAW_TOLERANCE_DEG)],
        "distance_mi": round(pr.length_mi, 1),
        "drive_s": round(pr.drive_s),
        "elapsed_s": round(score.elapsed_s),
        "arrival": _iso(dep_s + score.elapsed_s),
        "traffic_delay_s": round(pr.traffic_delay_s),
        "generated_detour": pr.via is not None,
        "summary": {
            "miles_by_level": {k: round(v, 1) for k, v in score.miles_by_level.items()},
            # same precision the ranking compares at, so the UI never shows a
            # difference the recommendation ignored
            "avg_risk": round(score.avg_risk, 2) if score.avg_risk is not None else None,
        },
        "checkpoints": r["checkpoints_json"],
        "rest_stops": [
            {**s, "mile": round(s["mile"], 1), "lat": round(s["lat"], 5),
             "lon": round(s["lon"], 5), "start": _iso(dep_s + s["start_s"])}
            for s in rest_stops(pr.profile, r["clock"])
        ],
        "track": [[round(t), round(lat, 5), round(lon, 5)]
                  for t, lat, lon in track(pr.profile, r["clock"])],
    }


def _heatmap_json(grid, cell_points, weather, start_h) -> dict:
    wind, rain, snow = [], [], []
    for p in cell_points:
        series = weather.get(p)
        if series is None:
            vals = {"wind": [None] * HEATMAP_HOURS, "rain": [None] * HEATMAP_HOURS,
                    "snow": [None] * HEATMAP_HOURS}
        else:
            vals = hour_slice(series, start_h, HEATMAP_HOURS)
        wind.append([None if v is None else round(v, 1) for v in vals["wind"]])
        rain.append([None if v is None else round(v, 3) for v in vals["rain"]])
        snow.append([None if v is None else round(v, 3) for v in vals["snow"]])
    return {
        "grid": grid.as_dict(),
        "buffer_mi": CORRIDOR_BUFFER_MI,
        "start": _iso(start_h * 3600),
        "hours": HEATMAP_HOURS,
        "wind": wind,
        "rain": rain,
        "snow": snow,
    }
