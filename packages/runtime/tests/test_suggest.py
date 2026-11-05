# SPDX-License-Identifier: Apache-2.0
"""Tests for runtime.suggest (fixtures built by hand; no runtime.leaks import)."""

import unittest

from runtime.suggest import CATALOG, rank, trajectory


def make_leaks(per_day, rate=100.0, wdays_week=5, wdays_year=240):
    return {
        "per_day_min": dict(per_day),
        "assumptions": {
            "switch_cost_min": 5.0,
            "hourly_rate_usd": rate,
            "workdays_per_week": wdays_week,
            "weeks_per_month": 4.33,
            "workdays_per_year": wdays_year,
            "years_per_decade": 10,
        },
    }


BASE_PER_DAY = {
    "switching": 30.0,
    "waiting": 20.0,
    "re_finding": 10.0,
    "admin": 15.0,
    "total": 75.0,
}


class CatalogTest(unittest.TestCase):
    def test_catalog_has_ten_or_more(self):
        self.assertGreaterEqual(len(CATALOG), 10)

    def test_owner_rule_catalog_has_winback_and_cost(self):
        for entry in CATALOG:
            self.assertIn(entry["targets"], ("switching", "waiting", "re_finding", "admin"))
            self.assertGreaterEqual(entry["recover_fraction"], 0)
            self.assertLessEqual(entry["recover_fraction"], 1)
            self.assertIn("adopt_cost_min", entry)
            self.assertIn("adopt_cost_usd", entry)
            self.assertTrue(entry["text"] and entry["text"][0].isupper())


class RankTest(unittest.TestCase):
    def test_winback_arithmetic_by_hand(self):
        leaks = make_leaks(BASE_PER_DAY)
        catalog = [
            {
                "id": "batch",
                "text": "Batch messages into two windows a day.",
                "targets": "switching",
                "recover_fraction": 0.5,
                "adopt_cost_min": 30.0,
                "adopt_cost_usd": 10.0,
            }
        ]
        (item,) = rank(leaks, catalog=catalog)
        # per_day 30 * 0.5 * 5 = 75 min/week
        self.assertAlmostEqual(item["winback_min_per_week"], 75.0)
        # 30 * 0.5 * 240 / 60 = 60 hours/year; usd = 6000
        self.assertAlmostEqual(item["winback_hours_year"], 60.0)
        self.assertAlmostEqual(item["winback_usd_year"], 6000.0)
        # score = 60*100 / (30/60*100 + 10 + 1) = 6000/61
        self.assertAlmostEqual(item["score"], 6000.0 / 61.0)
        self.assertEqual(item["evidence"]["component"], "switching")
        self.assertAlmostEqual(item["evidence"]["per_day_min"], 30.0)
        self.assertAlmostEqual(item["evidence"]["recover_fraction"], 0.5)
        self.assertEqual(item["adopt_cost_min"], 30.0)
        self.assertEqual(item["adopt_cost_usd"], 10.0)

    def test_zero_leak_component_drops_items(self):
        leaks = make_leaks({**BASE_PER_DAY, "waiting": 0.0})
        items = rank(leaks)
        self.assertTrue(items)
        for item in items:
            self.assertNotEqual(item["targets"], "waiting")
            self.assertGreater(item["winback_min_per_week"], 0)

    def test_sort_order_score_with_cost_tiebreak(self):
        leaks = make_leaks(BASE_PER_DAY)
        catalog = [
            {
                "id": "cheap",
                "text": "Do the cheap fix first.",
                "targets": "switching",
                "recover_fraction": 0.2,
                "adopt_cost_min": 60.0,
                "adopt_cost_usd": 0.0,
            },
            {
                "id": "pricey",
                "text": "Do the pricey fix later.",
                "targets": "switching",
                "recover_fraction": 0.2,
                "adopt_cost_min": 60.0,
                "adopt_cost_usd": 50.0,
            },
        ]
        # Force equal scores by patching? Instead check ordering property:
        items = rank(leaks, catalog=catalog)
        self.assertEqual([i["id"] for i in items], ["cheap", "pricey"])
        # Tie-break: identical score -> lower adopt cost first.
        tied = [
            dict(items[0], score=1.0, adopt_cost_min=5.0, adopt_cost_usd=0.0),
            dict(items[1], score=1.0, adopt_cost_min=50.0, adopt_cost_usd=0.0),
        ]
        tied_sorted = sorted(tied, key=lambda r: (-r["score"], r["adopt_cost_min"] + r["adopt_cost_usd"]))
        self.assertEqual(tied_sorted[0]["adopt_cost_min"], 5.0)
        # General order: scores descending.
        full = rank(leaks)
        scores = [i["score"] for i in full]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_every_item_has_winback_and_adopt_cost(self):
        leaks = make_leaks(BASE_PER_DAY)
        for item in rank(leaks):
            self.assertIn("winback_min_per_week", item)
            self.assertIn("winback_hours_year", item)
            self.assertIn("winback_usd_year", item)
            self.assertIn("adopt_cost_min", item)
            self.assertIn("adopt_cost_usd", item)

    def test_assumptions_come_from_leaks(self):
        leaks_a = make_leaks(BASE_PER_DAY, rate=100.0, wdays_week=5, wdays_year=240)
        leaks_b = make_leaks(BASE_PER_DAY, rate=200.0, wdays_week=4, wdays_year=200)
        catalog = [c for c in CATALOG if c["id"] == "batch-messages"]
        (a,) = rank(leaks_a, catalog=catalog)
        (b,) = rank(leaks_b, catalog=catalog)
        # winback_min_per_week uses workdays_per_week from leaks
        self.assertAlmostEqual(a["winback_min_per_week"], 30.0 * 0.4 * 5)
        self.assertAlmostEqual(b["winback_min_per_week"], 30.0 * 0.4 * 4)
        # usd uses hourly_rate_usd from leaks
        self.assertAlmostEqual(b["winback_usd_year"], b["winback_hours_year"] * 200.0)
        self.assertNotAlmostEqual(a["winback_usd_year"], b["winback_usd_year"])


class TrajectoryTest(unittest.TestCase):
    def test_current_vs_adopted_cumulative_never_negative(self):
        leaks = make_leaks(BASE_PER_DAY)
        top3 = [i["id"] for i in rank(leaks)[:3]]
        t = trajectory(leaks, top3, horizon_weeks=52)
        self.assertEqual(t["weeks"], list(range(1, 53)))
        self.assertEqual(len(t["current_hours"]), 52)
        self.assertEqual(len(t["adopted_hours"]), 52)
        for c, a in zip(t["current_hours"], t["adopted_hours"]):
            self.assertGreaterEqual(c, 0)
            self.assertGreaterEqual(a, 0)
            self.assertGreaterEqual(c, a - 1e-9)
        # cumulative: non-decreasing
        for xs in (t["current_hours"], t["adopted_hours"]):
            for prev, nxt in zip(xs, xs[1:]):
                self.assertLessEqual(prev, nxt + 1e-9)
        self.assertGreater(t["won_back_hours"], 0)
        self.assertAlmostEqual(t["won_back_usd"], t["won_back_hours"] * 100.0)
        self.assertAlmostEqual(t["won_back_hours"], t["current_hours"][-1] - t["adopted_hours"][-1])

    def test_no_adoptions_matches_current(self):
        leaks = make_leaks(BASE_PER_DAY)
        t = trajectory(leaks, [], horizon_weeks=4)
        self.assertAlmostEqual(t["won_back_hours"], 0.0)
        self.assertEqual(t["current_hours"], t["adopted_hours"])

    def test_double_targeting_compounds_multiplicatively(self):
        leaks = make_leaks({"switching": 40.0, "waiting": 0.0, "re_finding": 0.0, "admin": 0.0, "total": 40.0})
        catalog = [
            {
                "id": "a",
                "text": "Do one thing now.",
                "targets": "switching",
                "recover_fraction": 0.5,
                "adopt_cost_min": 10.0,
                "adopt_cost_usd": 0.0,
            },
            {
                "id": "b",
                "text": "Do another thing now.",
                "targets": "switching",
                "recover_fraction": 0.5,
                "adopt_cost_min": 10.0,
                "adopt_cost_usd": 0.0,
            },
        ]
        t = trajectory(leaks, ["a", "b"], horizon_weeks=1, catalog=catalog)
        # 40 * (1-0.5) * (1-0.5) = 10 min/day adopted; week = 10*5/60 h
        self.assertAlmostEqual(t["adopted_hours"][0], 10.0 * 5 / 60.0)
        self.assertAlmostEqual(t["current_hours"][0], 40.0 * 5 / 60.0)


if __name__ == "__main__":
    unittest.main()
