"""Open-Meteo hourly forecasts for many locations at once.

Billing is per location (free tier: 600/min, 10k/day per IP), so callers dedupe
locations first and every location's series is cached. Locations go out in
POST chunks (GET URLs fail around 8 KB; the API caps a request at 1,000
locations). Any location that can't be fetched maps to None, which the engine
treats as Unknown risk — never as Low.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests
from django.conf import settings
from django.core.cache import cache

from ..engine.weather import HourlySeries

log = logging.getLogger(__name__)

CHUNK = 400
CACHE_TTL_S = 3600
_TIMEOUT = 30
HOURLY = "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall"


class WeatherUnavailable(Exception):
    pass


def _key(p: tuple[float, float], start_h: int, end_h: int) -> str:
    return f"om:{p[0]:.4f},{p[1]:.4f}:{start_h}:{end_h}"


def _hour_str(epoch_h: int) -> str:
    return datetime.fromtimestamp(epoch_h * 3600, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M")


def fetch_hourly(points: list[tuple[float, float]], start_h: int,
                 end_h: int) -> tuple[dict[tuple[float, float], HourlySeries | None], list[str]]:
    """Hourly series covering [start_h, end_h] (epoch hours, UTC) per point.
    Returns (series by point, warnings)."""
    points = list(dict.fromkeys(points))
    cached = cache.get_many([_key(p, start_h, end_h) for p in points])
    result = {p: cached.get(_key(p, start_h, end_h)) for p in points}
    missing = [p for p in points if result[p] is None]
    warnings: list[str] = []

    chunks = [missing[i:i + CHUNK] for i in range(0, len(missing), CHUNK)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        outcomes = list(pool.map(lambda c: _fetch_chunk(c, start_h, end_h), chunks))
    fresh = {}
    for chunk, outcome in zip(chunks, outcomes):
        if isinstance(outcome, WeatherUnavailable):
            warnings.append(str(outcome))
            continue
        for p, series in zip(chunk, outcome):
            result[p] = series
            fresh[_key(p, start_h, end_h)] = series
    if fresh:
        cache.set_many(fresh, CACHE_TTL_S)
    return result, sorted(set(warnings))


def _fetch_chunk(chunk, start_h, end_h):
    data = {
        "latitude": ",".join(f"{p[0]:.4f}" for p in chunk),
        "longitude": ",".join(f"{p[1]:.4f}" for p in chunk),
        "hourly": HOURLY,
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "GMT",
        "start_hour": _hour_str(start_h),
        "end_hour": _hour_str(end_h),
    }
    for attempt in range(2):
        try:
            resp = requests.post(settings.OPEN_METEO_URL, data=data, timeout=_TIMEOUT)
        except requests.RequestException as exc:
            log.warning("open-meteo request failed: %s", exc)
            continue
        if resp.status_code == 429:
            return WeatherUnavailable("Weather service rate limit reached; some checkpoints are Unknown.")
        if resp.status_code != 200:
            log.warning("open-meteo %s: %s", resp.status_code, resp.text[:200])
            continue
        try:
            body = resp.json()
            items = body if isinstance(body, list) else [body]
            if len(items) != len(chunk):
                return WeatherUnavailable("Weather service returned an incomplete response.")
            return [_parse(item) for item in items]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            log.warning("open-meteo bad response body: %s", exc)
    return WeatherUnavailable("Weather service unavailable; some checkpoints are Unknown.")


def _parse(item: dict) -> HourlySeries:
    h = item["hourly"]
    first = datetime.strptime(h["time"][0], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    # round to the API's 3-decimal precision: 0.01 + 0.09 must classify as 0.10
    rain = [None if r is None or s is None else round(r + s, 3)
            for r, s in zip(h["rain"], h["showers"])]
    return HourlySeries(
        start_epoch_h=int(first.timestamp() // 3600),
        wind=h["wind_speed_10m"],
        gust=h["wind_gusts_10m"],
        rain=rain,
        snow=h["snowfall"],
    )
