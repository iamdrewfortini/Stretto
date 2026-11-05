# SPDX-License-Identifier: Apache-2.0
import asyncio
import json
import os
import unittest

from runtime.bus import EventBus
from runtime import voice as voice_mod
from runtime.voice import bridge, start_voice_thread

API_KEY = "test-key-xyz"


class FakeClosed(Exception):
    def __init__(self, code=1000, reason="done"):
        super().__init__(reason)
        self.code = code


class FakeBrowser:
    """Duck-types a browser websocket: recv() from inbox, send() recorded."""
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
                "tool_calls": [{"name": "log_time", "args": "{}", "ok": True, "result": {}}],
                "model": "test", "ms": 3}


class FakeUpstream:
    """Duck-types an upstream ASR websocket. Pops scripted recv() results, then
    idles until the bridge sends endStream, then closes cleanly like Meta does."""
    def __init__(self, script):
        self.script = list(script)
        self.sent = []

    async def send(self, raw):
        self.sent.append(raw)

    async def recv(self):
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        for _ in range(400):
            for raw in self.sent:
                if isinstance(raw, str) and json.loads(raw).get("type") == "endStream":
                    raise FakeClosed(1000, "done")
            await asyncio.sleep(0.05)
        raise FakeClosed(1013, "no endStream")

    async def close(self):
        pass


async def wait_for_type(browser, kind, timeout=10.0):
    for _ in range(int(timeout / 0.05)):
        if kind in browser.types():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"browser never got {kind}: {browser.types()}")


def base_env(**kw):
    env = {"RUNTIME_MODE": "local", "VOICE_BIND": "127.0.0.1:8788",
           "META_ASR_URL": "wss://api.meta.ai/v1/asr/realtime",
           "EGRESS_ALLOWLIST": "api.meta.ai", "MODEL_API_KEY": API_KEY}
    env.update(kw)
    return env


class RefusalT(unittest.TestCase):
    def test_non_loopback_bind_refused(self):
        with self.assertRaises(SystemExit):
            start_voice_thread(None, EventBus(), base_env(VOICE_BIND="0.0.0.0:8788"))

    def test_non_local_runtime_refused(self):
        with self.assertRaises(SystemExit):
            start_voice_thread(None, EventBus(), base_env(RUNTIME_MODE="prod"))

    def test_non_wss_asr_url_refused(self):
        with self.assertRaises(SystemExit):
            start_voice_thread(None, EventBus(),
                               base_env(META_ASR_URL="https://api.meta.ai/v1/asr/realtime"))

    def test_non_allowlisted_asr_host_refused(self):
        with self.assertRaises(SystemExit):
            start_voice_thread(None, EventBus(),
                               base_env(META_ASR_URL="wss://evil.example/asr"))


class BridgeT(unittest.IsolatedAsyncioTestCase):
    async def test_empty_final_ignored(self):
        bus, core, browser = EventBus(), FakeCore(), FakeBrowser()
        up = FakeUpstream([json.dumps({"sessionId": "s1"}),
                           json.dumps({"type": "speechComplete", "turnId": "t", "transcript": "   "}),
                           json.dumps({"type": "speechComplete", "turnId": "t", "transcript": "hi"})])

        async def asr_connect():
            return up

        await browser.inbox.put(json.dumps({"type": "start", "sample_rate": 16000}))
        task = asyncio.create_task(bridge(browser, core, bus, asr_connect, API_KEY))
        await wait_for_type(browser, "final")
        await browser.inbox.put(json.dumps({"type": "stop"}))
        await asyncio.wait_for(task, 15)
        self.assertEqual(browser.types(), ["ready", "final", "thinking", "reply"])
        self.assertEqual(core.texts, ["hi"])
        finals = [e for e in bus.since(0)[0] if e["type"] == "voice.utterance.final"]
        self.assertEqual([e["data"]["text"] for e in finals], ["hi"])

    async def test_unexpected_close_reopens_once(self):
        bus, core, browser = EventBus(), FakeCore(), FakeBrowser()
        ups = [FakeUpstream([json.dumps({"sessionId": "s1"}), FakeClosed(1013, "slow")]),
               FakeUpstream([json.dumps({"sessionId": "s2"}),
                             json.dumps({"type": "speechComplete", "turnId": "t", "transcript": "again"})])]
        calls = []

        async def asr_connect():
            calls.append(1)
            return ups.pop(0)

        await browser.inbox.put(json.dumps({"type": "start", "sample_rate": 16000}))
        task = asyncio.create_task(bridge(browser, core, bus, asr_connect, API_KEY))
        await wait_for_type(browser, "final")
        await browser.inbox.put(json.dumps({"type": "stop"}))
        await asyncio.wait_for(task, 15)
        self.assertEqual(len(calls), 2)
        self.assertEqual(browser.types(), ["ready", "error", "final", "thinking", "reply"])
        self.assertEqual(core.texts, ["again"])

    async def test_full_loop_against_fake_asr_server(self):
        from websockets.asyncio.client import connect
        from websockets.asyncio.server import serve

        seen = {}

        async def asr_handler(ws):
            hs = json.loads(await asyncio.wait_for(ws.recv(), 10))
            seen["hs"] = hs
            await ws.send(json.dumps({"sessionId": "sess-1"}))
            audio, fired = 0, False
            async for msg in ws:
                if isinstance(msg, bytes):
                    audio += len(msg)
                    if audio >= 3200 and not fired:
                        fired = True
                        await ws.send(json.dumps({"type": "speechStart", "turnId": "t1", "audioProcessedMs": 200}))
                        await ws.send(json.dumps({"type": "transcript", "transcript": "hello",
                                                  "final": False, "audioProcessedMs": 200}))
                        await ws.send(json.dumps({"type": "speechComplete", "turnId": "t1",
                                                  "transcript": "hello there"}))
                elif json.loads(msg).get("type") == "endStream":
                    break
            seen["audio"] = audio
            await ws.close()

        server = await serve(asr_handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            bus, core, browser = EventBus(), FakeCore(), FakeBrowser()
            # proxy=None: the sandbox sets *proxy env vars that would route even
            # loopback through a proxy; the fake speaks plain ws on loopback.
            async def asr_connect():
                return await connect(f"ws://127.0.0.1:{port}/", max_size=None, proxy=None)

            await browser.inbox.put(json.dumps({"type": "start", "sample_rate": 16000}))
            task = asyncio.create_task(bridge(browser, core, bus, asr_connect, API_KEY))
            for _ in range(4):
                await browser.inbox.put(bytes(1600))
            await wait_for_type(browser, "final")
            await browser.inbox.put(json.dumps({"type": "stop"}))
            await asyncio.wait_for(task, 15)
        finally:
            server.close()
            await server.wait_closed()

        # handshake is exact
        hs = seen["hs"]
        self.assertEqual(hs["authorization"], {"accessToken": "Bearer " + API_KEY})
        self.assertEqual(hs["audioEncoding"], "PCM_16KHZ")
        self.assertEqual(hs["model"], "muse-voice-transcribe-1.0")
        self.assertEqual(hs["mode"], "ENDPOINTING")
        self.assertEqual(hs["partialMode"], "CUMULATIVE")
        self.assertEqual(hs["emitAudioProgress"], False)
        self.assertGreaterEqual(seen["audio"], 3200)

        # browser hears ready, partial, final, reply in order
        self.assertEqual(browser.types(), ["ready", "partial", "final", "thinking", "reply"])
        self.assertEqual([m["text"] for m in browser.by_type("partial")], ["hello"])
        self.assertEqual([m["text"] for m in browser.by_type("final")], ["hello there"])
        replies = browser.by_type("reply")
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]["text"], "got it")
        self.assertEqual(replies[0]["tools"], ["log_time"])
        self.assertEqual(replies[0]["ms"], 3)
        self.assertEqual(core.texts, ["hello there"])

        # bus events, and the key appears in none of them
        evs = bus.since(0)[0]
        kinds = [e["type"] for e in evs]
        for want in ("voice.session.started", "voice.speech.start",
                     "voice.utterance.final", "voice.session.ended"):
            self.assertIn(want, kinds)
        self.assertTrue(all(e["source"] == "runtime.voice" for e in evs))
        self.assertNotIn(API_KEY, json.dumps(evs))
        finals_bus = [e for e in evs if e["type"] == "voice.utterance.final"]
        self.assertEqual([e["data"]["text"] for e in finals_bus], ["hello there"])


if __name__ == "__main__":
    unittest.main()
