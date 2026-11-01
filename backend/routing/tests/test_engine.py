"""Pure engine tests — no Django, no network."""
import json
from pathlib import Path
from unittest import TestCase

from routing.engine.checkpoints import (
    RouteProfile, build_checkpoints, checkpoint_miles, coverage, rest_stops, track,
)
from routing.engine.corridor import build_corridor, snap
from routing.engine.geo import haversine_miles
from routing.engine.hos import BREAK_S, HOUR, NO_HOS, RESET_S, HosClock, plan_rests
from routing.engine.recommend import recommend, score_route
from routing.engine.risk import Level, assess, rules_payload
from routing.engine.weather import HourlySeries, sample_at

SHARED = Path(__file__).resolve().parents[3] / "shared"
CASES = json.loads((SHARED / "risk_cases.json").read_text())["cases"]


class RiskTests(TestCase):
    def test_golden_cases(self):
        for c in CASES:
            with self.subTest(c["note"]):
                got = assess(c["wind"], c["rain"], c["snow"], c["load"]).level
                self.assertEqual(int(got), c["level"], c)

    def test_drivers_and_escalation(self):
        a = assess(40, 0.3, 0, 45_000)
        self.assertEqual(a.level, Level.SEVERE)
        self.assertEqual(a.drivers, ["wind"])
        self.assertTrue(a.load_escalated)
        self.assertEqual(assess(0, 0, 0, 0).drivers, [])
        self.assertEqual(assess(36, 0.3, 0, 0).drivers, ["wind", "rain"])

    def test_rules_payload_is_serialisable(self):
        payload = json.loads(json.dumps(rules_payload()))
        self.assertEqual(payload["levels"][4], "No Travel")
        self.assertEqual(payload["thresholds"]["rain"][3],
                         {"level": 4, "min": 1.0, "inclusive": False})

    def test_frontend_rules_snapshot_is_current(self):
        # the frontend's tests run the golden cases against this snapshot
        self.assertEqual(json.loads((SHARED / "rules.json").read_text()), rules_payload())


class HosTests(TestCase):
    def test_short_trip_needs_no_rest(self):
        self.assertEqual(plan_rests(7.9 * HOUR), [])
        self.assertEqual(plan_rests(8 * HOUR), [], "arriving exactly at 8 h needs no break")

    def test_break_then_reset_pattern(self):
        rests = plan_rests(30 * HOUR)
        self.assertEqual([(r.at_drive_s / HOUR, r.kind) for r in rests],
                         [(8, "break"), (11, "rest"), (19, "break"), (22, "rest")])

    def test_elapsed_time(self):
        clock = HosClock(plan_rests(17.8 * HOUR))
        self.assertEqual(clock.elapsed(8 * HOUR), 8 * HOUR, "reached before the break")
        self.assertAlmostEqual(clock.elapsed(8 * HOUR + 1), 8 * HOUR + 1 + BREAK_S)
        self.assertAlmostEqual(clock.elapsed(17.8 * HOUR), 17.8 * HOUR + BREAK_S + RESET_S)
        self.assertEqual(NO_HOS.elapsed(17.8 * HOUR), 17.8 * HOUR)


def straight_profile(miles=1000.0, mph=50.0, n=401):
    """Due-east route along 40N at constant speed."""
    pts, cum_mi, cum_s = [], [], []
    for i in range(n):
        m = miles * i / (n - 1)
        pts.append((40.0, -100.0 + m / 53.0))
        cum_mi.append(m)
        cum_s.append(m / mph * HOUR)
    return RouteProfile(pts, cum_mi, cum_s)


class CheckpointTests(TestCase):
    def test_marks(self):
        self.assertEqual(checkpoint_miles(100, 25), [0, 25, 50, 75, 100])
        self.assertEqual(checkpoint_miles(101, 25), [0, 25, 50, 75, 100, 101])
        self.assertEqual(checkpoint_miles(100.03, 25), [0, 25, 50, 75, 100.03])

    def test_coverage_reconciles_with_length(self):
        for total in (3.2, 100, 101, 987.6):
            for interval in (10, 25, 50):
                marks = checkpoint_miles(total, interval)
                self.assertAlmostEqual(sum(coverage(marks)), total, places=9)
        self.assertEqual(coverage([0, 25, 50, 60]), [12.5, 25, 17.5, 5])

    def test_etas_include_hos_rests(self):
        profile = straight_profile()                  # 20 h of driving
        clock = HosClock(plan_rests(profile.total_drive_s))
        cps = build_checkpoints(profile, 50, clock)
        self.assertEqual(len(cps), 21)
        self.assertEqual([c.elapsed_s for c in cps], sorted(c.elapsed_s for c in cps))
        by_mile = {round(c.mile): c for c in cps}
        self.assertAlmostEqual(by_mile[400].elapsed_s, 8 * HOUR, places=3)  # before break
        self.assertAlmostEqual(by_mile[450].elapsed_s, 9.5 * HOUR, places=3)
        self.assertAlmostEqual(by_mile[1000].elapsed_s, 20 * HOUR + 2 * BREAK_S + RESET_S, places=3)

    def test_rest_stops_and_track(self):
        profile = straight_profile()
        clock = HosClock(plan_rests(profile.total_drive_s))
        stops = rest_stops(profile, clock)
        self.assertEqual([(round(s["mile"]), s["kind"]) for s in stops],
                         [(400, "break"), (550, "rest"), (950, "break")])
        knots = track(profile, clock)
        times = [k[0] for k in knots]
        self.assertEqual(times, sorted(times))
        self.assertAlmostEqual(times[-1], clock.elapsed(profile.total_drive_s))


class WeatherSamplingTests(TestCase):
    series = HourlySeries(
        start_epoch_h=100,
        wind=[10, 20, 30, None],
        gust=[1, 2, 3, 4],
        rain=[0.0, 0.1, 0.2, 0.3],
        snow=[0.0, 0.0, 0.5, 0.0],
    )

    def test_wind_interpolates_precip_uses_preceding_hour_bucket(self):
        s = sample_at(self.series, (100 + 1.25) * 3600)
        self.assertAlmostEqual(s.wind, 22.5)
        self.assertEqual((s.rain, s.snow, s.gust), (0.2, 0.5, 3))

    def test_exact_hour_uses_bucket_ending_then(self):
        s = sample_at(self.series, 101 * 3600)
        self.assertEqual((s.wind, s.rain), (20, 0.1))

    def test_missing_gust_does_not_make_weather_unknown(self):
        series = HourlySeries(100, wind=[10, 20], gust=[None, None], rain=[0, 0], snow=[0, 0])
        s = sample_at(series, 100.5 * 3600)
        self.assertIsNotNone(s)
        self.assertIsNone(s.gust)

    def test_outside_or_missing_is_unknown(self):
        self.assertIsNone(sample_at(self.series, 99.5 * 3600))
        self.assertIsNone(sample_at(self.series, 104 * 3600))
        self.assertIsNone(sample_at(self.series, 102.5 * 3600), "wind at 103 is missing")


class RecommendTests(TestCase):
    def score(self, rid, levels, elapsed_h=10.0, cov=10.0):
        return score_route(rid, levels, [cov] * len(levels), elapsed_h * HOUR)

    def test_no_travel_beats_fewer_severe(self):
        L = Level
        a = self.score("A", [L.NO_TRAVEL, L.LOW, L.LOW])
        b = self.score("B", [L.SEVERE, L.SEVERE, L.LOW])
        rec = recommend([a, b])
        self.assertEqual((rec.route_id, rec.deciding_key), ("B", "no_travel_miles"))

    def test_key_order(self):
        L = Level
        severe = self.score("A", [L.SEVERE, L.LOW, L.LOW], elapsed_h=8)
        high = self.score("B", [L.HIGH, L.HIGH, L.HIGH], elapsed_h=12)
        self.assertEqual(recommend([severe, high]).route_id, "B")

        high1 = self.score("A", [L.HIGH, L.LOW, L.LOW], elapsed_h=8)
        mods = self.score("B", [L.MODERATE, L.MODERATE, L.MODERATE], elapsed_h=12)
        rec = recommend([high1, mods])
        self.assertEqual((rec.route_id, rec.deciding_key), ("B", "high_miles"))

        lower_avg = self.score("A", [L.MODERATE, L.LOW, L.LOW], elapsed_h=12)
        higher_avg = self.score("B", [L.MODERATE, L.MODERATE, L.LOW], elapsed_h=8)
        rec = recommend([higher_avg, lower_avg])
        self.assertEqual((rec.route_id, rec.deciding_key), ("A", "avg_risk"))

    def test_clear_weather_falls_through_to_time(self):
        L = Level
        slow = self.score("A", [L.LOW] * 3, elapsed_h=12)
        fast = self.score("B", [L.LOW] * 3, elapsed_h=11)
        rec = recommend([slow, fast])
        self.assertEqual((rec.route_id, rec.deciding_key, rec.ranking), ("B", "travel_time", ["B", "A"]))

    def test_average_is_distance_weighted(self):
        s = score_route("A", [Level.SEVERE, Level.LOW], [10, 30], HOUR)
        self.assertAlmostEqual(s.avg_risk, 0.75)
        self.assertEqual(s.miles_by_level["severe"], 10)

    def test_unknown_weather_never_wins_on_unmeasured_keys(self):
        L = Level
        known_severe = self.score("A", [L.LOW, L.SEVERE, L.LOW], elapsed_h=8)
        no_forecast = self.score("B", [None, None, None], elapsed_h=9)
        mostly_unknown = self.score("C", [L.LOW, None, L.LOW], elapsed_h=8.5)
        rec = recommend([known_severe, no_forecast, mostly_unknown])
        self.assertEqual((rec.route_id, rec.deciding_key, rec.ranking),
                         ("A", "unknown_miles", ["A", "C", "B"]))

    def test_flags(self):
        L = Level
        rec = recommend([self.score("A", [L.NO_TRAVEL, None]), self.score("B", [L.NO_TRAVEL])])
        self.assertTrue(rec.all_no_travel)
        self.assertTrue(rec.has_unknown)
        self.assertIsNone(recommend([self.score("A", [L.LOW])]).deciding_key)


class CorridorTests(TestCase):
    def test_corridor_covers_route_within_cell_budget(self):
        chicago_denver = [(41.88, -87.63), (41.6, -93.6), (41.26, -95.94), (40.8, -100.0), (39.74, -104.99)]
        grid = build_corridor([chicago_denver], buffer_mi=25, max_cells=300)
        self.assertLessEqual(len(grid.cells), 300)
        self.assertGreater(len(grid.cells), 30)
        centers = [grid.center(r, c) for r, c in grid.cells]
        for p in chicago_denver:
            nearest = min(haversine_miles(p, c) for c in centers)
            self.assertLess(nearest, 25 + grid.dlat * 69.05)

    def test_cross_country_stays_under_budget(self):
        la_nyc = [(34.05, -118.24), (35.1, -106.6), (35.2, -101.8), (38.6, -90.2), (40.0, -83.0), (40.71, -74.0)]
        grid = build_corridor([la_nyc], max_cells=300)
        self.assertLessEqual(len(grid.cells), 300)

    def test_snap(self):
        self.assertEqual(snap(41.8781, -87.6298), (41.9, -87.6))
