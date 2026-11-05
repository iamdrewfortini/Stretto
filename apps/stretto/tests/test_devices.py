"""Several computers, one person: time must be counted once. Independent of how the merge is implemented, the invariants are tested."""
import datetime as dt, random, unittest

from stretto import daycache, merge, segment
from stretto.server import Api
from stretto.store import Store

TODAY = dt.date.today()
T = dt.datetime.combine(TODAY - dt.timedelta(days=1), dt.time(9)).timestamp()


def seg(start, secs, app="Code", device="laptop", src="collector", idle=0, title="t", step=5, inp=None):
    return [dict(ts=T + start + i * step, dur=step, app=app, title=title, idle=idle, src=src, device=device, inp=inp, ctl="", domain="")
            for i in range(int(secs // step))]


def total(events):
    return sum(e["dur"] for e in events)


def at(events, a, b):
    """Resolved events whose midpoint is inside [T+a, T+b)."""
    return [e for e in events if T + a <= e["ts"] + e["dur"] / 2 < T + b]


class Invariants(unittest.TestCase):
    def test_simultaneous_devices_are_counted_once(self):
        ev = seg(0, 600, "Code", "laptop") + seg(0, 600, "chrome", "desktop", title="Docs - Google Docs")
        res, _ = merge.timeline(ev)
        self.assertAlmostEqual(total(res), 600, places=3)                               # not 1200
        self.assertEqual(merge.overlap(res)[0], 0)                                      # nothing left counted twice
        self.assertEqual(merge.overlap(ev)[0], 600)                                     # the raw data really was concurrent

    def test_sequential_use_is_untouched(self):
        ev = seg(0, 300, "Code", "laptop") + seg(300, 300, "chrome", "desktop")
        res, _ = merge.timeline(ev)
        self.assertAlmostEqual(total(res), 600, places=3)
        self.assertEqual({e["device"] for e in at(res, 0, 300)}, {"laptop"})
        self.assertEqual({e["device"] for e in at(res, 300, 600)}, {"desktop"})

    def test_the_newest_stay_wins_and_the_older_one_resumes_when_it_ends(self):
        ev = seg(0, 600, "Code", "laptop", title="a.py") + seg(300, 150, "chrome", "desktop")
        res, _ = merge.timeline(ev)
        self.assertAlmostEqual(total(res), 600, places=3)
        self.assertEqual({e["device"] for e in at(res, 0, 300)}, {"laptop"})
        self.assertEqual({e["device"] for e in at(res, 300, 450)}, {"desktop"})         # focus moved to the desktop at 300
        self.assertEqual({e["device"] for e in at(res, 450, 600)}, {"laptop"})          # and back when that stay ended
        bl = segment.blocks(res)
        self.assertEqual([b["device"] for b in bl], ["laptop", "desktop", "laptop"])

    def test_an_idle_computer_never_masks_an_active_one(self):
        ev = seg(0, 600, "idle", "laptop", idle=1, title="") + seg(0, 600, "Code", "desktop")
        res, _ = merge.timeline(ev)
        self.assertEqual({(e["device"], e["idle"]) for e in res}, {("desktop", 0)})
        self.assertAlmostEqual(total(res), 600, places=3)

    def test_everything_idle_is_idle_once(self):
        ev = seg(0, 300, "idle", "laptop", idle=1, title="") + seg(0, 300, "idle", "desktop", idle=1, title="")
        res, _ = merge.timeline(ev)
        self.assertAlmostEqual(total(res), 300, places=3)
        self.assertTrue(all(e["idle"] for e in res))

    def test_live_capture_beats_estimated_history_even_when_the_history_stay_is_newer(self):
        ev = seg(0, 300, "Code", "laptop") + seg(100, 200, "chrome", "desktop", src="chrome-history:Default", title="Docs", step=20)
        res, _ = merge.timeline(ev)
        self.assertEqual({e["device"] for e in at(res, 0, 300)}, {"laptop"})
        self.assertFalse([e for e in res if e["src"].startswith("chrome-history")])

    def test_each_device_resolves_its_own_sources_first(self):
        ev = (seg(0, 300, "Code", "desktop") + seg(0, 300, "chrome", "desktop", src="chrome-history:Default", step=30, title="x")
              + seg(600, 300, "Code", "laptop"))
        res, dropped = merge.timeline(ev)
        self.assertEqual(dropped.get("chrome-history:Default"), 10)                      # masked by the SAME computer's live capture
        self.assertAlmostEqual(total(res), 600, places=3)

    def test_input_ticks_are_scaled_to_the_part_of_an_event_that_survives(self):
        ev = [dict(ts=T, dur=10, app="Code", title="a", idle=0, src="collector", device="laptop", inp=10, ctl="", domain=""),
              dict(ts=T + 5, dur=5, app="chrome", title="b", idle=0, src="collector", device="desktop", inp=2, ctl="", domain="")]
        res, _ = merge.timeline(ev)
        laptop = [e for e in res if e["device"] == "laptop"]
        self.assertEqual((len(laptop), laptop[0]["dur"], laptop[0]["inp"]), (1, 5.0, 5))   # half the event, half the ticks
        self.assertEqual([e["inp"] for e in res if e["device"] == "desktop"], [2])

    def test_the_result_does_not_depend_on_input_order(self):
        ev = seg(0, 600, "Code", "laptop") + seg(200, 300, "chrome", "desktop") + seg(100, 200, "Slack", "phone-pc", title="s")
        base = [(e["device"], e["ts"], e["dur"]) for e in merge.timeline(ev)[0]]
        for seed in range(5):
            random.Random(seed).shuffle(ev)
            self.assertEqual([(e["device"], e["ts"], e["dur"]) for e in merge.timeline(ev)[0]], base)

    def test_one_device_is_exactly_resolve(self):
        ev = seg(0, 300, "Code", "only") + seg(0, 300, "chrome", "only", src="chrome-history:Default", step=30)
        self.assertEqual(merge.timeline(ev)[0], merge.resolve(ev)[0])

    def test_a_device_switch_is_a_change_of_place_but_one_computer_is_not(self):
        two = segment.blocks(seg(0, 300, "Code", "laptop") + seg(300, 300, "Code", "desktop"))
        self.assertEqual([b["device"] for b in two], ["laptop", "desktop"])               # same app, different computer
        one = segment.blocks(seg(0, 600, "Code", "laptop"))
        self.assertEqual(len(one), 1)


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")
        self.s.ingest(seg(0, 600, "Code", "laptop"), "collector", "laptop")
        self.s.ingest(seg(0, 600, "chrome", "desktop", title="Docs - Google Docs"), "collector", "desktop")
        self.api = Api(self.s)
        self.iso = (TODAY - dt.timedelta(days=1)).isoformat()

    def test_the_day_view_counts_ten_minutes_not_twenty_and_says_what_it_did(self):
        sm = self.api.day(self.iso)["summary"]
        self.assertEqual(sm["total_s"], 600)
        self.assertEqual((sm["overlap_s"], sm["overlap_devices"]), (0, []))                       # nothing left counted twice
        self.assertEqual((sm["concurrent_s"], sm["concurrent_devices"]), (600, ["desktop", "laptop"]))
        self.assertTrue(all("device" in b for b in self.api.day(self.iso)["blocks"]))

    def test_the_cached_history_agrees_with_the_day_view(self):
        self.assertEqual(self.api.day(self.iso)["summary"]["total_s"], 600)
        a, b = daycache.day_range(self.iso)
        cached = daycache.ensure(self.s, self.api.rules(), a, b)[self.iso]
        self.assertEqual((cached["total_s"], cached["focus_s"]), (600, self.api.day(self.iso)["summary"]["focus_s"]))

    def test_attention_does_not_count_the_second_computer_as_extra_activity(self):
        a = self.api.attention(self.iso)
        self.assertEqual(a["active_s"], 600)


if __name__ == "__main__":
    unittest.main()
