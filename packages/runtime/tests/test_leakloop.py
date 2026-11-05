# SPDX-License-Identifier: Apache-2.0
import time, unittest
from datetime import datetime

from runtime.bus import EventBus
from runtime.core import VoiceCore
from runtime.leakloop import start_leak_loop
from runtime.tools import Tools

NOON = datetime(2026, 11, 4, 12, 0).timestamp()


class NoModel:
    def complete(self, body):
        raise AssertionError("model called")


class LeakLoopT(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus(); self.tools = Tools(self.bus, clock=lambda: NOON)
        for act, mins in (("focus", 50), ("comms", 10), ("focus", 30), ("wait", 20), ("comms", 15), ("admin", 25)):
            self.tools.t_log_time(act, mins)

    def test_publishes_all_four_events_and_owner_rule_holds(self):
        start_leak_loop(self.bus, self.tools)
        types = [e["type"] for e in self.bus.since(0)[0]]
        for t in ("leaks.computed", "suggestions.ranked", "progress.updated", "trajectory.forecast"):
            self.assertIn(t, types)
        items = [e for e in self.bus.since(0)[0] if e["type"] == "suggestions.ranked"][-1]["data"]["items"]
        self.assertTrue(items)
        for it in items:  # never a suggestion without both numbers
            self.assertGreater(it["winback_min_per_week"], 0); self.assertIn("adopt_cost_min", it)
        self.assertEqual(items, sorted(items, key=lambda r: -r["score"]))

    def test_recomputes_after_each_ledger_change(self):
        start_leak_loop(self.bus, self.tools)
        before = sum(e["type"] == "leaks.computed" for e in self.bus.since(0)[0])
        self.tools.t_log_time("wait", 15)
        after = [e for e in self.bus.since(0)[0] if e["type"] == "leaks.computed"]
        self.assertEqual(len(after), before + 1)
        self.assertGreater(after[-1]["data"]["per_day_min"]["waiting"], 0)

    def test_voice_answers_leak_questions_locally_and_fast(self):
        core = VoiceCore(NoModel(), self.tools, self.bus, clock=lambda: NOON)
        t0 = time.perf_counter(); out = core.turn("what's my leak score"); ms = (time.perf_counter() - t0) * 1000
        self.assertEqual(out["path"], "fast"); self.assertLess(ms, 100.0)
        self.assertIn("Leak score", out["reply"]); self.assertIn("hours a year", out["reply"])


if __name__ == "__main__":
    unittest.main()
