# SPDX-License-Identifier: Apache-2.0
import statistics, time, unittest

from runtime.bus import EventBus
from runtime.core import VoiceCore
from runtime.fastpath import match
from runtime.tools import Tools

BUDGET_MS = 100.0


class NoModel:
    def __init__(self):
        self.calls = 0

    def complete(self, body):
        self.calls += 1
        return {"choices": [{"message": {"role": "assistant", "content": "model answer"}}]}, "muse-spark-1.3", "r"


HITS = {
    "hello": ("greet", {}),
    "Hey there": ("greet", {}),
    "Log twenty five minutes of focus time on the demo script.": ("log_time", {"activity": "focus", "minutes": 25}),
    "I was in meetings for the last 40 minutes": ("log_time", {"activity": "meeting", "minutes": 40}),
    "I spent 1.5 hours on email": ("log_time", {"activity": "comms", "minutes": 90}),
    "log half an hour of admin": ("log_time", {"activity": "admin", "minutes": 30}),
    "start a focus timer": ("start_timer", {"activity": "focus"}),
    "I'm starting a call": ("start_timer", {"activity": "meeting"}),
    "stop the timer": ("stop_timer", {}),
    "How's my day going?": ("get_summary", {"range": "today"}),
    "what are my tasks": ("list_tasks", {}),
    "add a task: record the demo video, about 30 minutes": ("create_task", {"title": "record the demo video", "estimate_min": 30}),
}
MISSES = [  # must go to the model: ambiguous, no duration, no activity, or open questions
    "", "log some time", "start", "I was busy for 40 minutes", "should I take a break before the demo?",
    "what did I do yesterday afternoon", "log 900 minutes of focus", "move my meeting to tomorrow",
]


class Match(unittest.TestCase):
    def test_hits(self):
        for text, want in HITS.items():
            self.assertEqual(match(text), want, text)

    def test_misses_fall_through(self):
        for text in MISSES:
            self.assertIsNone(match(text), text)


class Latency(unittest.TestCase):
    def test_fast_turns_are_local_and_within_budget(self):
        """Proof for the <100 ms target: N real turns through VoiceCore (tools + event bus, no network), p95 measured."""
        gw = NoModel(); bus = EventBus(); core = VoiceCore(gw, Tools(bus), bus)
        texts = [t for t in HITS if not t.startswith("stop")] * 40
        ms = []
        for t in texts:
            t0 = time.perf_counter(); out = core.turn(t); ms.append((time.perf_counter() - t0) * 1000)
            self.assertEqual(out["path"], "fast", t)
        p50, p95 = statistics.median(ms), statistics.quantiles(ms, n=20)[18]
        print(f"\nfast path: n={len(ms)} p50={p50:.3f} ms p95={p95:.3f} ms max={max(ms):.3f} ms (budget {BUDGET_MS} ms)")
        self.assertEqual(gw.calls, 0)
        self.assertLess(p95, BUDGET_MS)

    def test_unmatched_goes_to_model(self):
        gw = NoModel(); bus = EventBus()
        out = VoiceCore(gw, Tools(bus), bus).turn("should I take a break before the demo?")
        self.assertEqual(out["path"], "model"); self.assertEqual(gw.calls, 1)

    def test_fast_reply_numbers_come_from_the_ledger(self):
        bus = EventBus(); core = VoiceCore(NoModel(), Tools(bus), bus)
        core.turn("I was in meetings for 40 minutes"); core.turn("log 25 minutes of focus")
        self.assertEqual(core.turn("how's my day")["reply"], "Today: 40 minutes meeting, 25 minutes focus.")


if __name__ == "__main__":
    unittest.main()
