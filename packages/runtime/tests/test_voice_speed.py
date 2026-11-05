# SPDX-License-Identifier: Apache-2.0
"""Voice speed: stutter debounce, thinking feedback, and fast model turns."""
import asyncio
import json
import time
import unittest

from runtime.bus import EventBus
from runtime.core import VoiceCore
from runtime.tools import Tools
from runtime.voice import bridge

API_KEY = "test-key-xyz"


class FakeClosed(Exception):
    def __init__(self, code=1000, reason="done"):
        super().__init__(reason)
        self.code = code


class FakeBrowser:
    def __init__(self):
        self.inbox = asyncio.Queue()
        self.sent = []

    async def recv(self):
        msg = await self.inbox.get()
        if isinstance(msg, Exception):
            raise msg
        return msg

    async def send(self, raw):
        self.sent.append(raw)

    def types(self):
        return [json.loads(raw).get("type") for raw in self.sent]

    def by_type(self, kind):
        return [json.loads(raw) for raw in self.sent if json.loads(raw).get("type") == kind]


class FakeCore:
    def __init__(self):
        self.texts = []

    def turn(self, text):
        self.texts.append(text)
        return {"turn_id": "turn_1", "reply": "got it",
                "tool_calls": [], "model": "test", "ms": 3}


class FakeUpstream:
    """Scripted ASR: str payloads, ("sleep", s) pauses, or Exceptions to raise."""

    def __init__(self, script):
        self.script = list(script)
        self.sent = []

    async def send(self, raw):
        self.sent.append(raw)

    async def recv(self):
        while True:
            if self.script:
                item = self.script.pop(0)
                if isinstance(item, tuple):
                    await asyncio.sleep(item[1])
                    continue
                if isinstance(item, Exception):
                    raise item
                return item
            for raw in self.sent:
                if isinstance(raw, str):
                    try:
                        obj = json.loads(raw)
                    except ValueError:
                        continue
                    if obj.get("type") == "endStream":
                        raise FakeClosed(1000, "done")
            await asyncio.sleep(0.05)

    async def close(self):
        pass


async def wait_for_type(browser, kind, timeout=10.0):
    for _ in range(int(timeout / 0.05)):
        if kind in browser.types():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"browser never got {kind}: {browser.types()}")


def ack():
    return json.dumps({"sessionId": "s1"})


def final(text):
    return json.dumps({"type": "speechComplete", "turnId": "t", "transcript": text})


class DebounceT(unittest.IsolatedAsyncioTestCase):
    async def _run(self, script, hold_s):
        bus, core, browser = EventBus(), FakeCore(), FakeBrowser()
        up = FakeUpstream(script)

        async def asr_connect():
            return up

        await browser.inbox.put(json.dumps({"type": "start", "sample_rate": 16000}))
        task = asyncio.create_task(bridge(browser, core, bus, asr_connect, API_KEY, hold_s=hold_s))
        return bus, core, browser, task

    async def _stop(self, browser, task):
        await browser.inbox.put(json.dumps({"type": "stop"}))
        await asyncio.wait_for(task, 15)

    async def test_two_finals_close_together_become_one_turn(self):
        # Stutter: "show my" + 0.3 s later "tasks" is one utterance, not two turns.
        _, core, browser, task = await self._run(
            [ack(), final("show my"), ("sleep", 0.3), final("tasks")], hold_s=0.45)
        await wait_for_type(browser, "reply")
        await self._stop(browser, task)
        self.assertEqual(core.texts, ["show my tasks"])
        self.assertEqual([m["text"] for m in browser.by_type("final")], ["show my tasks"])

    async def test_final_then_silence_runs_turn_after_hold(self):
        hold = 0.3
        _, core, browser, task = await self._run([ack(), final("hello there")], hold_s=hold)
        t0 = time.monotonic()
        await wait_for_type(browser, "reply")
        self.assertGreaterEqual(time.monotonic() - t0, hold - 0.1)
        await self._stop(browser, task)
        self.assertEqual(core.texts, ["hello there"])

    async def test_stutter_restarts_wait(self):
        # A speechStart during the hold means the person kept talking: no turn yet.
        start = json.dumps({"type": "speechStart", "turnId": "t", "audioProcessedMs": 10})
        _, core, browser, task = await self._run(
            [ack(), final("note that"), ("sleep", 0.15), start,
             ("sleep", 0.15), final("meeting ran long")], hold_s=0.4)
        await wait_for_type(browser, "reply")
        await self._stop(browser, task)
        self.assertEqual(core.texts, ["note that meeting ran long"])

    async def test_fillers_and_repeats_are_cleaned(self):
        _, core, browser, task = await self._run(
            [ack(), final("um uh I I want to log focus time you know")], hold_s=0.2)
        await wait_for_type(browser, "reply")
        await self._stop(browser, task)
        self.assertEqual(core.texts, ["I want to log focus time"])
        self.assertEqual([m["text"] for m in browser.by_type("final")],
                         ["I want to log focus time"])

    async def test_thinking_is_sent_before_reply(self):
        _, core, browser, task = await self._run([ack(), final("hi there")], hold_s=0.2)
        await wait_for_type(browser, "reply")
        await self._stop(browser, task)
        self.assertEqual(browser.types(), ["ready", "final", "thinking", "reply"])
        self.assertEqual(core.texts, ["hi there"])


class FakeGW:
    def __init__(self, steps):
        self.steps, self.requests = list(steps), []

    def complete(self, body):
        self.requests.append(body)
        s = self.steps.pop(0)
        msg = {"role": "assistant", "content": s} if isinstance(s, str) else \
            {"role": "assistant", "content": "", "tool_calls": s}
        return {"choices": [{"message": msg}]}, "muse-spark-1.3", "req_x"


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class ModelSpeedT(unittest.TestCase):
    def test_model_body_is_cache_hot_and_short(self):
        bus, tools = EventBus(), Tools(EventBus(), clock=Clock())
        tools.t_log_time("focus", 90)
        tools.t_log_time("meeting", 60)
        tools.t_log_time("comms", 30)
        tools.t_log_time("wait", 5)  # 4th activity: must fall out of the top 3
        titles = [f"speed task {i}" for i in range(7)]
        for title in titles:
            tools.t_create_task(title)
        gw = FakeGW(["ok"] * 10)
        core = VoiceCore(gw, tools, bus, fast=False)
        for i in range(4):
            core.turn(f"hello {i}")
        body = gw.requests[-1]
        self.assertEqual(body["prompt_cache_key"], "humanflow-voice-v1")
        hist = body["messages"][1:-1]  # between system context and the latest user text
        self.assertLessEqual(len(hist), 4)
        ctx = body["messages"][0]["content"]
        self.assertIn('"focus"', ctx)
        self.assertNotIn('"wait"', ctx)  # only the top 3 activities ride along
        kept = [t for t in titles if t in ctx]
        self.assertGreater(len(kept), 0)
        self.assertLessEqual(len(kept), 5)  # at most 5 open task titles


if __name__ == "__main__":
    unittest.main()
