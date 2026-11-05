# SPDX-License-Identifier: Apache-2.0
import json
import os
import statistics
import tempfile
import unittest

from sensors.adapters import Sample
from sensors.consent import ConsentStore
from sensors.episodes import EpisodeBuilder, categorize
from sensors.ingest import IngestClient, check_event
from sensors.importer import Importer
from sensors.metrics import MetricsEngine


class FixtureWindow:
    name, source, platforms = "fixture-window", "window", ()

    def __init__(self, script):
        self.script = script  # fn(now) -> (app, title)

    def probe(self):
        return True, "available"

    def poll(self, now):
        app, title = self.script(now)
        return [Sample("window", now, app=app, title=title)]


class FixtureClockImporter(unittest.TestCase):
    def _make(self, script, tmp, titles_on=True):
        consent = ConsentStore(path=os.path.join(tmp, "consent.json"))
        consent.grant(["window", "idle", "input", "pointer"], 100000, now=0)
        events = []
        imp = Importer([(FixtureWindow(script), True, "available")],
                       consent, events, titles_on=titles_on,
                       now_fn=lambda: 0.0)
        return imp, events, consent


class Episodes(FixtureClockImporter):
    def test_merging_and_idle_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            def script(now):
                return ("Code", "main.py") if now < 10 else ("Code", "x.py")
            imp, events, _ = self._make(script, tmp)
            for t in range(0, 20):
                imp._idle_s = 200.0 if t >= 15 else 0.0
                imp.tick(now=float(t))
            imp.close(now=20.0)
            eps = [e for e in events if e["type"] == "activity.episode"]
            apps = [(e["data"]["app"], round(e["data"]["seconds"]))
                    for e in eps]
            self.assertIn(("idle", 5), apps)
            self.assertEqual(eps[0]["data"]["category"], "focus")

    def test_category_rules(self):
        self.assertEqual(categorize("Visual Studio Code"), "focus")
        self.assertEqual(categorize("Zoom"), "meeting")
        self.assertEqual(categorize("Slack"), "comms")
        self.assertEqual(categorize("Safari", "Google search"), "search")
        self.assertEqual(categorize("Safari", "news"), "other")

    def test_ledger_thresholds_and_manual_dup(self):
        b = EpisodeBuilder()
        for t in range(0, 70):
            b.feed(Sample("window", float(t), app="Code", title="a"), 0.0)
        ep = b.close(70.0)[0]
        self.assertIsNotNone(b.ledger_event(ep))
        b2 = EpisodeBuilder()
        for t in range(0, 30):
            b2.feed(Sample("window", float(t), app="Code", title="a"), 0.0)
        short = b2.close(30.0)[0]
        self.assertIsNone(b2.ledger_event(short))  # < 60 s
        b.note_manual_span(10.0, 50.0)
        self.assertIsNone(b.ledger_event(ep))  # overlaps manual span


class Metrics(unittest.TestCase):
    def test_hand_computed(self):
        eps = [
            {"app": "Code", "category": "focus", "start": 0.0, "end": 100.0},
            {"app": "Slack", "category": "comms", "start": 100.0, "end": 200.0},
            {"app": "idle", "category": "idle", "start": 200.0, "end": 300.0},
        ]
        rows = {r["window_s"]: r for r in MetricsEngine().compute(eps, 600.0)}
        r = rows[600]
        self.assertEqual(r["focus_ratio"], 0.333)
        self.assertEqual(r["idle_ratio"], 0.333)
        self.assertEqual(r["switches"], 2)
        self.assertEqual(r["switches_per_min"], 0.2)
        self.assertEqual(r["mean_episode_s"], 100.0)
        self.assertEqual(r["longest_focus_s"], 100.0)


class ConsentPrivacy(FixtureClockImporter):
    def test_default_deny_and_revoke_next_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            consent = ConsentStore(path=os.path.join(tmp, "c.json"))
            events = []
            imp = Importer(
                [(FixtureWindow(lambda n: ("Code", "a")), True, "ok")],
                consent, events, now_fn=lambda: 0.0)
            imp.tick(now=1.0)
            self.assertEqual(events, [])  # default-deny: zero samples
            consent.grant(["window"], 1000, now=0)
            imp.tick(now=2.0)
            self.assertTrue(imp.builder.cur)
            consent.revoke(["window"])
            before = len(events)
            imp.tick(now=3.0)
            self.assertEqual(len(events), before)  # stopped next tick
            mode = oct(os.stat(consent.path).st_mode)[-3:]
            self.assertEqual(mode, "600")

    def test_keyboard_chars_never_emitted(self):
        class FixtureKeys:
            name, source, platforms = "fixture-keys", "input", ()

            def probe(self):
                return True, "available"

            def poll(self, now):
                # fixture adapter counts characters; only the count may leave
                return [Sample("input", now, keys=len("hunter2"))]

        with tempfile.TemporaryDirectory() as tmp:
            imp, events, _ = self._make(lambda n: ("Code", "a"), tmp)
            imp.adapters.append((FixtureKeys(), True, "ok"))
            imp.consent.grant(["input"], 100000, now=0)
            for t in range(3):
                imp.tick(now=float(t))
            blob = json.dumps(events)
            self.assertNotIn("hunter2", blob)
            for ch in "hunter2":
                self.assertNotIn(f'"keys": "{ch}"', blob)
            self.assertIn('"keys": 7', blob)

    def test_titles_off_and_truncation(self):
        with tempfile.TemporaryDirectory() as tmp:
            long_title = "jane.doe@example.com " + "x" * 120
            imp, events, _ = self._make(lambda n: ("Code", long_title), tmp)
            for t in range(5):
                imp.tick(now=float(t))
            imp2, events2, _ = self._make(
                lambda n: ("Code", long_title), tmp, titles_on=False)
            for t in range(5):
                imp2.tick(now=float(t))
            imp.close(now=5.0)
            imp2.close(now=5.0)
            ep = [e for e in events
                  if e["type"] == "activity.episode"][0]["data"]
            self.assertNotIn("jane.doe@example.com", ep["title"])
            self.assertLessEqual(len(ep["title"]), 80)
            ep2 = [e for e in events2
                   if e["type"] == "activity.episode"][0]["data"]
            self.assertNotIn("title", ep2)


class TitlesPref(FixtureClockImporter):
    def test_settings_titles_choice_applies_next_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "c.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"grants": {}, "titles": False}, f)
            consent = ConsentStore(path=path)
            self.assertIs(consent.titles_pref(), False)
            consent.grant(["window"], 1000, now=0)
            raw = json.load(open(path, encoding="utf-8"))
            self.assertIs(raw["titles"], False)  # grant keeps the pref
            events = []
            imp = Importer(
                [(FixtureWindow(lambda n: ("Code", "secret-title")), True, "ok")],
                consent, events, titles_on=True, now_fn=lambda: 0.0)
            for t in range(5):
                imp.tick(now=float(t))
            imp.close(now=5.0)
            ep = [e for e in events
                  if e["type"] == "activity.episode"][0]["data"]
            self.assertNotIn("title", ep)  # pref off beats startup on


class Ingest(unittest.TestCase):
    def test_batch_backoff_buffer(self):
        clock = [0.0]
        sent = []

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"accepted": 200}'

        def opener(req, timeout=2):
            sent.append(json.loads(req.data))
            return Resp()

        c = IngestClient("http://127.0.0.1:8787", opener=opener,
                         now_fn=lambda: clock[0])
        for i in range(250):
            c.push({"type": "attention.metrics", "data": {"i": i}})
        c.flush(force=True)
        self.assertLessEqual(len(sent[0]["events"]), 200)
        self.assertEqual(len(c.queue), 50)
        # gateway-down: queue holds, old events drop past 10 min
        def down(req, timeout=2):
            raise OSError("down")

        c2 = IngestClient("http://127.0.0.1:8787", opener=down,
                          now_fn=lambda: clock[0], buffer_s=600)
        c2.push({"type": "narration.log", "data": {"text": "x"}})
        self.assertEqual(c2.flush(force=True), 0)
        self.assertEqual(len(c2.queue), 1)
        clock[0] += 601
        c2.push({"type": "narration.log", "data": {"text": "y"}})
        self.assertEqual(c2.dropped, 1)

    def test_loopback_only_and_event_gate(self):
        with self.assertRaises(ValueError):
            IngestClient("https://example.com:8787")
        self.assertFalse(check_event({"type": "evil.x", "data": {}}))
        self.assertFalse(check_event(
            {"type": "ledger.event.added", "data": {"origin": "manual"}}))
        self.assertTrue(check_event(
            {"type": "ledger.event.added", "data": {"origin": "auto"}}))


class NarrationRules(unittest.TestCase):
    def test_suggestion_cadence_and_streak(self):
        from sensors.narration import Narrator
        n = Narrator(switch_cost_s=30.0)
        hot = {"switches": 11, "switches_per_min": 1.1, "idle_ratio": 0.0}
        self.assertIsNone(n.suggest(hot, 1000.0, in_streak=True))
        ev = n.suggest(hot, 1000.0, in_streak=False)
        self.assertIn("11 switches", ev["data"]["text"])
        self.assertIn("switches_per_min", ev["data"]["evidence"])
        self.assertIsNone(n.suggest(hot, 1100.0, in_streak=False))
        ev2 = n.suggest(hot, 1400.0, in_streak=False)
        self.assertIsNotNone(ev2)
        self.assertIn("won_back_min_week", ev2["data"])
        self.assertIn("adopt_cost_min", ev2["data"])
        from sensors.narration import Narrator as N2
        self.assertIsNone(N2().suggest(hot, 1000.0, in_streak=False))


class Registry(unittest.TestCase):
    def test_discover_dedupes(self):
        from sensors import adapters
        adapters.discover()
        n = len(adapters.registry())
        adapters.discover()
        self.assertEqual(len(adapters.registry()), n)


class Perf(FixtureClockImporter):
    def test_3600_ticks_p95(self):
        with tempfile.TemporaryDirectory() as tmp:
            imp, events, _ = self._make(lambda n: ("Code", "a"), tmp)
            for t in range(3600):
                imp.tick(now=float(t))
            times = sorted(imp.tick_ms)
            p50 = statistics.median(times)
            p95 = times[int(0.95 * len(times))]
            print(f"\nperf: p50={p50:.3f}ms p95={p95:.3f}ms "
                  f"ticks={len(times)}")
            self.assertLess(p95, 5.0)


if __name__ == "__main__":
    unittest.main()
