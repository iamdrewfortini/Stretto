# SPDX-License-Identifier: Apache-2.0
import json, os, tempfile, unittest

from runtime.bus import EventBus
from runtime.core import VoiceCore
from runtime.gateway import check_tool_pairs
from runtime.tools import Tools, run_tool


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def tc(i, name, **args):
    return {"id": f"call_{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class FakeGW:
    """Scripted model: each step is a list of tool_calls or a final string. Asserts Meta's pairing rule on every request."""
    def __init__(self, steps):
        self.steps, self.requests = list(steps), []

    def complete(self, body):
        check_tool_pairs(body["messages"])
        self.requests.append(body)
        s = self.steps.pop(0)
        msg = {"role": "assistant", "content": s} if isinstance(s, str) else {"role": "assistant", "content": "", "tool_calls": s}
        return {"choices": [{"message": msg}]}, "muse-spark-1.3", "req_x"


class ToolsT(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(); self.log = os.path.join(self.dir, "events.jsonl"); self.clock = Clock()
        self.tools = Tools(EventBus(self.log), clock=self.clock)

    def test_log_and_summary(self):
        self.tools.t_log_time("meeting", 40)
        self.tools.t_log_time("focus", 90, note="spec")
        s = self.tools.t_get_summary("all")
        self.assertEqual(s["by_activity_min"], {"focus": 90.0, "meeting": 40.0})
        self.assertEqual(s["total_min"], 130.0)

    def test_timer_start_stop_and_auto_stop(self):
        self.tools.t_start_timer("focus"); self.clock.t += 25 * 60
        r = self.tools.t_start_timer("comms")
        self.assertEqual(r["stopped_previous"]["minutes"], 25.0)
        self.clock.t += 5 * 60
        self.assertEqual(self.tools.t_stop_timer()["minutes"], 5.0)
        self.assertEqual(self.tools.t_get_summary("all")["by_activity_min"], {"focus": 25.0, "comms": 5.0})

    def test_state_rebuilds_from_event_log(self):
        self.tools.t_log_time("focus", 30)
        tid = self.tools.t_create_task("write demo script")["task_id"]
        self.tools.t_update_task(tid, "doing")
        self.tools.t_start_timer("focus", task_id=tid)
        again = Tools(EventBus(self.log), clock=self.clock)
        self.assertEqual(again.t_list_tasks(), self.tools.t_list_tasks())
        self.assertEqual(again.timer["task_id"], tid)
        self.assertEqual(again.t_get_summary("all")["total_min"], 30.0)

    def test_bad_calls_become_tool_errors(self):
        for call in (tc(1, "log_time", activity="napping", minutes=5), tc(2, "log_time", activity="focus", minutes=0),
                     tc(3, "stop_timer"), tc(4, "update_task", task_id="nope", status="done"), tc(5, "rm_rf"),
                     {"id": "call_6", "function": {"name": "log_time", "arguments": "{not json"}}):
            msg, ok, res = run_tool(self.tools, call)
            self.assertFalse(ok, call); self.assertIn("error", res); self.assertEqual(msg["tool_call_id"], call["id"])
        self.assertEqual(self.tools.events, [])


class CoreT(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus(); self.tools = Tools(self.bus, clock=Clock())

    def test_turn_runs_tools_then_replies(self):
        gw = FakeGW([[tc(1, "log_time", activity="meeting", minutes=40)], "Logged 40 minutes of meetings."])
        out = VoiceCore(gw, self.tools, self.bus).turn("I was in meetings for 40 minutes")
        self.assertEqual(out["reply"], "Logged 40 minutes of meetings.")
        self.assertEqual([c["name"] for c in out["tool_calls"]], ["log_time"])
        self.assertEqual(self.tools.t_get_summary("all")["by_activity_min"], {"meeting": 40.0})
        self.assertEqual(gw.requests[0]["role"], "voice.core")
        types = [e["type"] for e in self.bus.since(0)[0]]
        self.assertEqual(types[0], "core.turn.started"); self.assertEqual(types[-1], "core.turn.completed")

    def test_failed_tool_is_replayed_not_dropped(self):
        gw = FakeGW([[tc(1, "stop_timer")], "No timer was running."])
        out = VoiceCore(gw, self.tools, self.bus).turn("stop the timer")
        self.assertFalse(out["tool_calls"][0]["ok"])
        self.assertEqual(gw.requests[1]["messages"][-1]["role"], "tool")

    def test_tool_loop_is_bounded(self):
        gw = FakeGW([[tc(i, "list_tasks")] for i in range(10)])
        out = VoiceCore(gw, self.tools, self.bus).turn("loop forever")
        self.assertLessEqual(len(gw.requests), 5)
        self.assertTrue(out["reply"])

    def test_history_is_carried_and_bounded(self):
        gw = FakeGW(["ok"] * 20)
        core = VoiceCore(gw, self.tools, self.bus, history_turns=2)
        for i in range(5):
            core.turn(f"hello {i}")
        self.assertEqual(len(core.history), 4)
        self.assertEqual(gw.requests[-1]["messages"][-1]["content"], "hello 4")


if __name__ == "__main__":
    unittest.main()
