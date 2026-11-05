# SPDX-License-Identifier: Apache-2.0
"""Per-day cache: identical answers to a from-scratch reference, warm reads touch no events, every change invalidates exactly what it should."""
import datetime as dt, os, tempfile, unittest
from unittest import mock

from stretto import analyze, consent, daycache, demo, gamify, merge, segment
from stretto.server import Api
from stretto.store import Store

TODAY = dt.date.today()


def day_start(k):
    return dt.datetime.combine(TODAY - dt.timedelta(days=k), dt.time()).timestamp()


def fill(store, days=15, device="d"):
    for k in range(1, days + 1):
        store.ingest(demo.samples(day_start(k), seed=k), src="collector", device=device)


def ref_blocks(api, iso):
    a, b = daycache.day_range(iso)
    kept, _ = merge.resolve(api.s.events(a, b))
    return segment.blocks(kept, api.rules())


def ref_summary(api, iso):
    """The OLD way, written independently of daycache: recompute from raw events."""
    bl = ref_blocks(api, iso)
    sm = analyze.summary(bl)
    hours = [0.0] * 24
    for b in bl:
        if b["category"] in segment.FOCUS:
            hours[dt.datetime.fromtimestamp(b["start"]).hour] += b["seconds"]
    return dict(sm, hours=[round(h) for h in hours], loss_s=analyze.findings(bl)[1], focus_exact=sum(b["seconds"] for b in bl if b["category"] in segment.FOCUS))


class Equivalence(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")
        fill(self.s)
        self.api = Api(self.s)

    def test_range_matches_a_from_scratch_reference_exactly(self):
        got = self.api.range(10)["days"]
        for row in got:
            if row["total_s"] == 0:
                continue
            ref = ref_summary(self.api, row["date"])
            self.assertEqual((row["focus_s"], row["distraction_s"], row["total_s"], row["by_category"], row["hours"], row["loss_s"]),
                             (ref["focus_s"], ref["distraction_s"], ref["total_s"], ref["by_category"], ref["hours"], ref["loss_s"]), row["date"])

    def test_focus_history_matches_reference(self):
        iso = (TODAY - dt.timedelta(days=1)).isoformat()
        got = self.api.focus_history(iso)
        self.assertEqual(len(got), 15)
        for d, v in got.items():
            self.assertAlmostEqual(v, ref_summary(self.api, d)["focus_exact"], places=2, msg=d)

    def test_patterns_match_a_reference_built_the_old_way(self):
        p = self.api.patterns(30)
        days = {(TODAY - dt.timedelta(days=k)).isoformat(): ref_blocks(self.api, (TODAY - dt.timedelta(days=k)).isoformat()) for k in range(1, 16)}
        hf, ht = [0.0] * 24, [0.0] * 24
        for bs in days.values():
            for b in bs:
                if b["category"] != "Idle":
                    h = dt.datetime.fromtimestamp(b["start"]).hour
                    ht[h] += b["seconds"]
                    if b["category"] in segment.FOCUS:
                        hf[h] += b["seconds"]
        self.assertEqual((p["days"], p["enough"]), (15, True))
        for got, want in zip(p["hour_focus_s"], [round(x / 15) for x in hf]):
            self.assertLessEqual(abs(got - want), 1)               # per-day rounding of hour arrays: under a second
        best = max(range(24), key=lambda h: sum(hf[(h + k) % 24] for k in range(3)))
        self.assertEqual(p["best_window"]["start_hour"], best)

    def test_day_view_xp_and_streak_match_the_reference(self):
        iso = (TODAY - dt.timedelta(days=1)).isoformat()
        d = self.api.day(iso)
        goal = self.api.goal_s()
        fbd = {(TODAY - dt.timedelta(days=k)).isoformat(): ref_summary(self.api, (TODAY - dt.timedelta(days=k)).isoformat())["focus_exact"] for k in range(1, 16)}
        self.assertEqual(d["xp"]["xp"], sum(gamify.xp_for_day(v, goal) for v in fbd.values()))
        self.assertEqual(d["streak"], gamify.streak(fbd, iso, goal))


class Behaviour(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")
        fill(self.s, days=6)
        self.api = Api(self.s)
        self.t0, self.t1 = self.api.window(TODAY.isoformat(), 10)

    def ensure(self):
        st = {}
        out = daycache.ensure(self.s, self.api.rules(), self.t0, self.t1, stats=st)
        return out, st

    def test_cold_then_warm_and_warm_reads_touch_no_events(self):
        _, st = self.ensure()
        self.assertEqual((st["hits"], st["computed"]), (0, 6))
        with mock.patch.object(Store, "events", side_effect=AssertionError("events were read")):
            out, st = self.ensure()
            self.api.patterns(10)
            self.api.range(7)
        self.assertEqual((st["hits"], st["computed"], len(out)), (6, 0, 6))

    def test_new_data_in_one_day_recomputes_only_that_day(self):
        self.ensure()
        k = 3
        self.s.ingest([dict(ts=day_start(k) + 20 * 3600, dur=5, app="Code", title="late", src="collector")], src="collector", device="d")
        _, st = self.ensure()
        self.assertEqual((st["computed"], st["hits"]), (1, 5))

    def test_a_changed_duration_with_the_same_count_still_invalidates(self):
        self.ensure()
        self.s.x("UPDATE events SET dur = dur + 1 WHERE id = (SELECT MIN(id) FROM events WHERE ts >= ? AND ts < ?)", (day_start(2), day_start(2) + 86400))
        self.assertEqual(self.ensure()[1]["computed"], 1)

    def test_changing_a_rule_recomputes_every_day(self):
        self.ensure()
        self.s.x("INSERT INTO rules(field,pattern,category) VALUES('app','^code$','Learn')")
        _, st = self.ensure()
        self.assertEqual((st["computed"], st["hits"]), (6, 0))
        out, _ = self.ensure()
        self.assertTrue(all("Learn" in v["by_category"] for v in out.values()))             # the new rule is really in the numbers

    def test_a_purge_removes_days_from_the_cache_and_the_result(self):
        self.s.ingest([dict(ts=day_start(5), dur=5, app="x", title="t")], src="git-history:p", device="d")
        self.ensure()
        before = {r["day"] for r in self.s.q("SELECT day FROM day_cache")}
        self.s.x("DELETE FROM events")
        out, st = self.ensure()
        self.assertEqual((out, st["days"]), ({}, 0))
        self.assertEqual(self.s.q("SELECT COUNT(*) AS n FROM day_cache")[0]["n"], 0)
        self.assertTrue(before)

    def test_the_viewed_day_is_used_but_never_stored_from_the_page_read(self):
        iso = (TODAY - dt.timedelta(days=2)).isoformat()
        self.api.day(iso)
        stored = {r["day"] for r in self.s.q("SELECT day FROM day_cache")}
        self.assertNotIn(iso, stored)                                                       # no race: only fingerprint-first reads are cached
        self.assertIn((TODAY - dt.timedelta(days=3)).isoformat(), stored)

    def test_windows_are_whole_calendar_days(self):
        t0, t1 = Api.window("2026-03-08", 3)                                                # a US daylight-saving change day
        self.assertEqual(dt.datetime.fromtimestamp(t0).time(), dt.time(0, 0))
        self.assertEqual(dt.datetime.fromtimestamp(t1).time(), dt.time(0, 0))


class Parallel(unittest.TestCase):
    def test_cold_start_fans_out_and_agrees_with_one_process(self):
        d = tempfile.mkdtemp()
        s = Store(os.path.join(d, "t.sqlite"))
        fill(s, days=daycache.PARALLEL_MIN + 3)
        api = Api(s)
        t0, t1 = api.window(TODAY.isoformat(), daycache.PARALLEL_MIN + 5)
        st = {}
        par = daycache.ensure(s, api.rules(), t0, t1, stats=st)
        if (os.cpu_count() or 1) > 1:
            self.assertTrue(st["parallel"], "expected the worker pool to run on a multi-core machine")
        s.x("DELETE FROM day_cache")
        with mock.patch.object(daycache, "PARALLEL_MIN", 10 ** 6):
            st2 = {}
            seq = daycache.ensure(s, api.rules(), t0, t1, stats=st2)
        self.assertFalse(st2["parallel"])
        self.assertEqual(par, seq)                                                          # fan-out changes speed, never numbers

    def test_memory_stores_never_use_the_pool(self):
        s = Store(":memory:")
        fill(s, days=daycache.PARALLEL_MIN + 2)
        api = Api(s)
        st = {}
        daycache.ensure(s, api.rules(), *api.window(TODAY.isoformat(), daycache.PARALLEL_MIN + 4), stats=st)
        self.assertFalse(st["parallel"])


if __name__ == "__main__":
    unittest.main()
