# SPDX-License-Identifier: Apache-2.0
import unittest
from datetime import datetime, timezone

from runtime.leaks import DEFAULTS, compute, daily_history, progress


def T(day, hour=9, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc).timestamp()


def ev(day, activity, minutes, hour=9, **kw):
    e = {"t": T(day, hour) + minute_offset(hour, kw.pop("slot", 0)),
         "activity": activity, "duration_s": minutes * 60.0, "text": activity}
    e.update(kw)
    return e


def minute_offset(hour, slot):
    return slot * 3600


class TestDefaults(unittest.TestCase):
    def test_defaults_exact(self):
        self.assertEqual(DEFAULTS, {
            "switch_cost_min": 5.0,
            "hourly_rate_usd": 100.0,
            "workdays_per_week": 5,
            "weeks_per_month": 4.33,
            "workdays_per_year": 240,
            "years_per_decade": 10,
        })


class TestCompute(unittest.TestCase):
    def test_switching_cost_from_switches(self):
        # 6 switches x 5 min = 30 min over 2 observed days -> 15/day.
        summary = {"range": "all", "total_min": 960.0, "by_activity_min": {},
                   "switches": 6, "lost_min": {}}
        events = [ev(1, "focus", 60), ev(2, "focus", 60)]
        out = compute(summary, events, 1_800_000_000.0)
        self.assertEqual(out["days_observed"], 2.0)
        self.assertAlmostEqual(out["per_day_min"]["switching"], 15.0)
        self.assertAlmostEqual(out["per_day_min"]["total"], 15.0)

    def test_failed_vs_normal_search_weighting(self):
        # 60 search min, 20 failed -> 20 + 0.5*40 = 40 re-finding min.
        summary = {"range": "all", "total_min": 120.0,
                   "by_activity_min": {"search": 60.0},
                   "switches": 0, "lost_min": {"search_failed": 20.0}}
        out = compute(summary, [ev(1, "search", 60)], 1_800_000_000.0)
        self.assertAlmostEqual(out["per_day_min"]["re_finding"], 40.0)
        # tracked 120, leaked 40 -> 100*40/120 = 33.33 -> 33.
        self.assertEqual(out["leak_score"], 33)

    def test_compounding_week_month_year_decade(self):
        # 60 leak min/day = 1h/day: week 1*5 = 5h; month 5*4.33 = 21.65h;
        # year 1*240 = 240h; decade 2400h; usd at $100/h.
        summary = {"range": "all", "total_min": 600.0,
                   "by_activity_min": {"admin": 60.0},
                   "switches": 0, "lost_min": {}}
        out = compute(summary, [ev(1, "admin", 60)], 1_800_000_000.0)
        c = out["compounded"]
        self.assertAlmostEqual(c["week"]["hours"], 5.0)
        self.assertAlmostEqual(c["week"]["usd"], 500.0)
        self.assertAlmostEqual(c["month"]["hours"], 21.65)
        self.assertAlmostEqual(c["month"]["usd"], 2165.0)
        self.assertAlmostEqual(c["year"]["hours"], 240.0)
        self.assertAlmostEqual(c["year"]["usd"], 24000.0)
        self.assertAlmostEqual(c["decade"]["hours"], 2400.0)
        self.assertAlmostEqual(c["decade"]["usd"], 240000.0)

    def test_leak_score_bounds_and_lower_is_better(self):
        base = {"range": "all", "total_min": 480.0, "switches": 0, "lost_min": {}}
        small = dict(base, by_activity_min={"admin": 10.0})
        big = dict(base, by_activity_min={"admin": 100.0})
        s = compute(small, [ev(1, "admin", 10)], 0)
        b = compute(big, [ev(1, "admin", 100)], 0)
        self.assertEqual(s["leak_score"], 2)   # 100*10/480 = 2.08
        self.assertEqual(b["leak_score"], 21)  # 100*100/480 = 20.83
        self.assertLess(s["leak_score"], b["leak_score"])
        for v in (s["leak_score"], b["leak_score"]):
            self.assertGreaterEqual(v, 0)
            self.assertLessEqual(v, 100)

    def test_zero_tracked_case(self):
        summary = {"range": "today", "total_min": 0.0,
                   "by_activity_min": {}, "switches": 0, "lost_min": {}}
        out = compute(summary, [], 1_800_000_000.0)
        self.assertEqual(out["days_observed"], 1.0)
        self.assertAlmostEqual(out["per_day_min"]["total"], 0.0)
        self.assertAlmostEqual(out["tracked_per_day_min"], 0.0)
        self.assertEqual(out["leak_score"], 0)

    def test_params_override_shows_in_assumptions(self):
        summary = {"range": "all", "total_min": 600.0,
                   "by_activity_min": {"admin": 60.0},
                   "switches": 0, "lost_min": {}}
        out = compute(summary, [ev(1, "admin", 60)], 0, params={"hourly_rate_usd": 200.0})
        self.assertEqual(out["assumptions"]["hourly_rate_usd"], 200.0)
        self.assertEqual(out["assumptions"]["switch_cost_min"], 5.0)
        self.assertAlmostEqual(out["compounded"]["week"]["usd"], 1000.0)


class TestDailyHistory(unittest.TestCase):
    def test_groups_by_date(self):
        # Day 1: two wait blocks, same activity -> no switch: leak 60, tracked 60.
        # Day 2: 20 search (normal -> half = 10) + 10 admin + 1 switch (5) = 25.
        events = [
            ev(1, "wait", 30, slot=0),
            ev(1, "wait", 30, slot=1),
            ev(2, "search", 20, slot=0),
            ev(2, "admin", 10, slot=1),
        ]
        hist = daily_history(events)
        self.assertEqual([d["date"] for d in hist], ["2026-11-01", "2026-11-02"])
        self.assertAlmostEqual(hist[0]["leak_min"], 60.0)
        self.assertAlmostEqual(hist[0]["tracked_min"], 60.0)
        self.assertAlmostEqual(hist[1]["leak_min"], 25.0)
        self.assertAlmostEqual(hist[1]["tracked_min"], 30.0)

    def test_tz_offset_shifts_date(self):
        # 2026-11-01 23:30 UTC is 2026-11-02 at UTC+5.
        t = datetime(2026, 11, 1, 23, 30, tzinfo=timezone.utc).timestamp()
        e = {"t": t, "activity": "wait", "duration_s": 600.0, "text": "x"}
        self.assertEqual(daily_history([e])[0]["date"], "2026-11-01")
        self.assertEqual(daily_history([e], tz_offset_s=5 * 3600)[0]["date"], "2026-11-02")


class TestProgress(unittest.TestCase):
    def test_baseline_won_back_xp_level(self):
        # Baseline = median(100, 80, 60) = 80; won back = 0+20+40 = 60.
        hist = [
            {"date": "2026-11-01", "leak_min": 100.0, "tracked_min": 400.0},
            {"date": "2026-11-02", "leak_min": 80.0, "tracked_min": 400.0},
            {"date": "2026-11-03", "leak_min": 60.0, "tracked_min": 400.0},
            {"date": "2026-11-04", "leak_min": 40.0, "tracked_min": 400.0},
        ]
        p = progress(hist)
        self.assertAlmostEqual(p["baseline_min_per_day"], 80.0)
        self.assertAlmostEqual(p["today_min"], 40.0)
        self.assertAlmostEqual(p["won_back_min"], 60.0)
        self.assertEqual(p["xp"], 60)
        self.assertEqual(p["level"], 1)
        self.assertEqual(p["level_name"], "Noticing")
        self.assertEqual(p["xp_into_level"], 30)
        self.assertEqual(p["xp_for_next"], 30)

    def test_single_day_no_won_back(self):
        p = progress([{"date": "2026-11-01", "leak_min": 50.0, "tracked_min": 400.0}])
        self.assertAlmostEqual(p["baseline_min_per_day"], 50.0)
        self.assertAlmostEqual(p["won_back_min"], 0.0)
        self.assertEqual(p["xp"], 0)
        self.assertEqual(p["level"], 0)
        self.assertEqual(p["level_name"], "Leaking")

    def test_level_thresholds_and_names(self):
        # Two-day history [xp, 0]: baseline xp, won back xp -> xp exact.
        cases = [
            (0, 0, "Leaking"), (29, 0, "Leaking"),
            (30, 1, "Noticing"), (89, 1, "Noticing"),
            (90, 2, "Plugging"), (179, 2, "Plugging"),
            (180, 3, "Flowing"), (299, 3, "Flowing"),
            (300, 4, "Compounding"), (449, 4, "Compounding"),
            (450, 5, "Coherent"), (629, 5, "Coherent"),
            (630, 6, "Coherent"), (1000, 7, "Coherent"),
        ]
        for xp_want, level_want, name_want in cases:
            with self.subTest(xp=xp_want):
                hist = [
                    {"date": "2026-11-01", "leak_min": float(xp_want), "tracked_min": 500.0},
                    {"date": "2026-11-02", "leak_min": 0.0, "tracked_min": 500.0},
                ]
                p = progress(hist)
                self.assertEqual(p["xp"], xp_want)
                self.assertEqual(p["level"], level_want)
                self.assertEqual(p["level_name"], name_want)


if __name__ == "__main__":
    unittest.main()
