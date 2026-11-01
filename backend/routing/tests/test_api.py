"""End-to-end /api/plan with TomTom and Open-Meteo mocked at the HTTP layer."""
import re
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

CHICAGO = {"label": "Chicago, IL", "lat": 41.8781, "lon": -87.6298}
DENVER = {"label": "Denver, CO", "lat": 39.7392, "lon": -104.9903}


class FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


def _tomtom_route(points, mph):
    """TomTom-shaped route with a sparse progress array (every 7th point)."""
    from routing.engine.geo import METERS_PER_MILE, cumulative_miles
    cum = cumulative_miles(points)
    progress = [
        {"pointIndex": i, "distanceInMeters": cum[i] * METERS_PER_MILE,
         "travelTimeInSeconds": round(cum[i] / mph * 3600)}
        for i in range(0, len(points), 7)
    ]
    return {
        "summary": {"lengthInMeters": cum[-1] * METERS_PER_MILE,
                    "travelTimeInSeconds": round(cum[-1] / mph * 3600),
                    "trafficDelayInSeconds": 0},
        "legs": [{"points": [{"latitude": a, "longitude": b} for a, b in points]}],
        "progress": progress,
    }


def _line(a, b, bend=0.0, n=120):
    """Polyline from a to b, bowed sideways by ``bend`` degrees of latitude."""
    import math
    return [(a[0] + (b[0] - a[0]) * t + bend * math.sin(math.pi * t),
             a[1] + (b[1] - a[1]) * t) for t in (i / (n - 1) for i in range(n))]


def fake_tomtom_get(url, params, timeout):
    # mirror TomTom's real validation (observed against the live API)
    if "alternativeType" in params and int(params["maxAlternatives"]) == 0:
        return FakeResponse(400, {"detailedError": {
            "message": "Invalid request: maxAlternative must be greater than 0 when alternativeType is set",
            "code": "BAD_INPUT"}})
    locs = re.search(r"calculateRoute/(.+)/json", url).group(1).split(":")
    a = tuple(map(float, locs[0].split(",")))
    b = tuple(map(float, locs[-1].split(",")))
    if len(locs) == 3:  # via detour
        return FakeResponse(200, {"routes": [_tomtom_route(_line(a, b, bend=-1.5), 52)]})
    # provider only finds 2 alternatives -> forces the fallback path
    return FakeResponse(200, {"routes": [
        _tomtom_route(_line(a, b), 55),
        _tomtom_route(_line(a, b, bend=1.2), 54),
    ]})


def fake_open_meteo_post(url, data, timeout):
    lats = [float(x) for x in data["latitude"].split(",")]
    start = datetime.strptime(data["start_hour"], "%Y-%m-%dT%H:%M")
    end = datetime.strptime(data["end_hour"], "%Y-%m-%dT%H:%M")
    hours = int((end - start).total_seconds() // 3600) + 1
    items = []
    for lat in lats:
        windy = lat > 41.0  # the northern corridor is stormy
        items.append({"hourly": {
            "time": [(start + timedelta(hours=k)).strftime("%Y-%m-%dT%H:%M") for k in range(hours)],
            "wind_speed_10m": [47.0 if windy else 10.0] * hours,
            "wind_gusts_10m": [60.0 if windy else 15.0] * hours,
            "rain": [0.0] * hours,
            "showers": [0.0] * hours,
            "snowfall": [0.0] * hours,
        }})
    return FakeResponse(200, items)


@override_settings(
    TOMTOM_API_KEY="test",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
@patch("routing.providers.open_meteo.requests.post", side_effect=fake_open_meteo_post)
@patch("routing.providers.tomtom.requests.get", side_effect=fake_tomtom_get)
class PlanApiTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def post(self, **overrides):
        body = {
            "origin": CHICAGO, "destination": DENVER,
            "departure": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "load_lb": 35_000, "interval_mi": 25,
        }
        body.update(overrides)
        return self.client.post("/api/plan", body, content_type="application/json")

    def test_full_plan(self, _get, _post):
        resp = self.post()
        self.assertEqual(resp.status_code, 200, resp.content)
        plan = resp.json()

        self.assertEqual([r["id"] for r in plan["routes"]], ["A", "B", "C"])
        self.assertTrue(plan["routes"][2]["generated_detour"])
        for r in plan["routes"]:
            miles = r["summary"]["miles_by_level"]
            self.assertAlmostEqual(sum(miles.values()), r["distance_mi"], delta=0.5)
            etas = [c["eta"] for c in r["checkpoints"]]
            self.assertEqual(etas, sorted(etas))
            self.assertEqual(miles["unknown"], 0)
            self.assertGreater(len(r["rest_stops"]), 0, "~1000 mi trip needs HOS rests")

        # 47 mph at 35,000 lb is No Travel; route B bows north into it
        b = plan["routes"][1]
        self.assertGreater(b["summary"]["miles_by_level"]["no_travel"], 0)
        rec = plan["recommendation"]
        self.assertNotEqual(rec["route_id"], "B")
        self.assertEqual(rec["ranking"][-1], "B")

        hm = plan["heatmap"]
        self.assertEqual(len(hm["wind"]), len(hm["grid"]["cells"]))
        self.assertTrue(all(len(row) == 49 for row in hm["wind"]))
        self.assertLessEqual(len(hm["grid"]["cells"]), 220)
        self.assertEqual(plan["rules"]["levels"][4], "No Travel")

    def test_repeat_request_is_served_from_cache(self, get, post):
        self.post()
        calls = get.call_count + post.call_count
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(get.call_count + post.call_count, calls)

    def test_different_departure_minute_is_not_served_from_cache(self, _get, _post):
        base = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(hours=2)
        first = self.post(departure=base.replace(minute=5).isoformat()).json()
        second = self.post(departure=base.replace(minute=55).isoformat()).json()
        self.assertNotEqual(first["inputs"]["departure"], second["inputs"]["departure"])

    def test_validation(self, _get, _post):
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        self.assertEqual(self.post(departure=past).status_code, 400)
        self.assertEqual(self.post(load_lb=60_000).status_code, 400)
        self.assertEqual(self.post(interval_mi=15).status_code, 400)
        self.assertEqual(self.post(destination=CHICAGO).status_code, 400)
        self.assertEqual(self.post(load_lb="NaN").status_code, 400)
        self.assertEqual(self.post(origin={**CHICAGO, "lat": "NaN"}).status_code, 400)

    def test_long_trip_stays_within_weather_budget(self, _get, post):
        los_angeles = {"label": "Los Angeles, CA", "lat": 34.05, "lon": -118.24}
        plan = self.post(destination=los_angeles, interval_mi=10).json()
        sent = sum(len(c.kwargs["data"]["latitude"].split(",")) for c in post.call_args_list)
        self.assertLessEqual(sent, 500)
        self.assertTrue(any("grid" in n for n in plan["notices"]))
        self.assertFalse(plan["recommendation"]["has_unknown"])

    def test_routing_network_error_never_leaks_api_key(self, get, _post):
        import requests
        get.side_effect = requests.ConnectionError(
            "HTTPSConnectionPool: Max retries exceeded with url: /routing/1/calculateRoute/x/json?key=test")
        resp = self.post()
        self.assertEqual(resp.status_code, 502)
        self.assertNotIn("key=", resp.content.decode())

    def test_malformed_weather_body_degrades_to_unknown(self, _get, post):
        post.side_effect = lambda *a, **k: FakeResponse(200, {"error": True, "reason": "overloaded"})
        resp = self.post()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["recommendation"]["has_unknown"])

    def test_rain_plus_showers_lands_on_band_edge(self, _get, _post):
        from routing.providers.open_meteo import _parse
        series = _parse({"hourly": {"time": ["2026-11-01T00:00"], "wind_speed_10m": [5],
                                    "wind_gusts_10m": [9], "rain": [0.01], "showers": [0.09],
                                    "snowfall": [0]}})
        self.assertEqual(series.rain, [0.1])

    def test_weather_outage_is_unknown_not_low(self, _get, post):
        post.side_effect = lambda *a, **k: FakeResponse(429, {"reason": "limit"})
        plan = self.post().json()
        for r in plan["routes"]:
            self.assertAlmostEqual(r["summary"]["miles_by_level"]["unknown"], r["distance_mi"], delta=0.5)
            self.assertEqual(r["summary"]["miles_by_level"]["low"], 0)
        self.assertTrue(any("rate limit" in n for n in plan["notices"]))
        self.assertTrue(plan["recommendation"]["has_unknown"])

        # once the weather service recovers, a retry must not get the degraded plan
        post.side_effect = fake_open_meteo_post
        retry = self.post().json()
        self.assertFalse(retry["recommendation"]["has_unknown"])


@override_settings(TOMTOM_API_KEY="test")
class GrossWeightTests(SimpleTestCase):
    def test_gross_weight_caps_at_federal_limit(self):
        from routing.providers.tomtom import gross_weight_kg
        self.assertEqual(gross_weight_kg(20_000), round(55_000 * 0.45359237))
        self.assertEqual(gross_weight_kg(48_000), round(80_000 * 0.45359237))
