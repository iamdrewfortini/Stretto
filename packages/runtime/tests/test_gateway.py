# SPDX-License-Identifier: Apache-2.0
import io, json, os, threading, unittest, urllib.error, urllib.request
from email.message import Message
from http.server import ThreadingHTTPServer

from runtime.bus import EventBus
from runtime.gateway import Gateway, GatewayError, Upstream, check_tool_pairs, make_handler, normalize, serve
from runtime.registry import Registry

REG = os.path.join(os.path.dirname(__file__), "..", "..", "..", "docs", "spec", "models.registry.json")
USAGE = {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100, "prompt_tokens_details": {"cached_tokens": 0}}


def ok_body(model):
    return io.BytesIO(json.dumps({"choices": [{"message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
                                  "model": model, "usage": USAGE}).encode())


def http_error(code, retry_after=None):
    h = Message()
    if retry_after:
        h["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://api.meta.ai/v1/chat/completions", code, "err", h, io.BytesIO(b'{"error":"x"}'))


class FakeUp:
    def __init__(self, script):
        self.script, self.calls, self.key, self.base = list(script), [], "k", "https://api.meta.ai/v1"

    def post(self, path, body, timeout=120):
        self.calls.append(body)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return ok_body(body["model"])


def gw(script, **kw):
    bus = EventBus()
    return Gateway(Registry.load(REG), FakeUp(script), bus, sleep=lambda s: None, **kw), bus


MSG = [{"role": "user", "content": "hello"}]
VOICE = Registry.load(REG).chain(role="voice.core")  # primary, then fallbacks, as the registry binds them
PRICE = Registry.load(REG).models[VOICE[0]]["price_per_mtok"]


class T(unittest.TestCase):
    def test_role_resolves_and_params_normalized(self):
        g, bus = gw(["ok"])
        data, model, _ = g.complete({"role": "voice.core", "messages": MSG, "max_tokens": 50, "stop": ["x"], "presence_penalty": 1})
        sent = g.up.calls[0]
        self.assertEqual(model, VOICE[0])
        self.assertEqual(sent["max_completion_tokens"], 512)  # raised to the role's floor
        self.assertNotIn("max_tokens", sent); self.assertNotIn("stop", sent); self.assertNotIn("presence_penalty", sent)
        self.assertEqual(sent["reasoning_effort"], "minimal")

    def test_max_tokens_renamed_above_floor(self):
        g, _ = gw(["ok"])
        g.complete({"model": "muse-spark-1.3", "messages": MSG, "max_tokens": 2000})
        self.assertEqual(g.up.calls[0]["max_completion_tokens"], 2000)

    def test_unknown_or_non_meta_model_refused(self):
        g, _ = gw([])
        for m in ("gpt-4o", "muse-glimmer-30b", "muse-spark-open"):
            with self.assertRaises(GatewayError) as c:
                g.complete({"model": m, "messages": MSG})
            self.assertEqual(c.exception.status, 400)
        self.assertEqual(g.up.calls, [])

    def test_unbound_roles_say_why(self):
        g, _ = gw([])
        for role in ("embed", "voice.tts"):
            with self.assertRaises(GatewayError) as c:
                g.complete({"role": role, "messages": MSG})
            self.assertIn(role, str(c.exception))

    def test_retry_then_fallback(self):
        g, bus = gw([http_error(503), http_error(503, "0"), http_error(503), "ok"])
        _, model, _ = g.complete({"role": "voice.core", "messages": MSG})
        self.assertEqual(model, VOICE[1])
        self.assertEqual([c["model"] for c in g.up.calls], [VOICE[0]] * 3 + [VOICE[1]])
        calls = [e for e in bus.since(0)[0] if e["type"] == "gateway.call"]
        self.assertEqual([c["data"]["status"] for c in calls], [503, 503, 503, 200])

    def test_client_errors_do_not_retry(self):
        g, _ = gw([http_error(400), "ok"])
        with self.assertRaises(GatewayError) as c:
            g.complete({"role": "voice.core", "messages": MSG})
        self.assertEqual(c.exception.status, 400); self.assertEqual(len(g.up.calls), 1)

    def test_unanswered_tool_call_caught_locally(self):
        msgs = MSG + [{"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
                      {"role": "user", "content": "and?"}]
        with self.assertRaises(GatewayError):
            check_tool_pairs(msgs)
        check_tool_pairs(msgs[:2] + [{"role": "tool", "tool_call_id": "c1", "content": "{}"}] + msgs[2:])

    def test_cost_and_spend_limit(self):
        g, bus = gw(["ok", "ok"], spend_limit=1e-6)
        g.complete({"role": "voice.core", "messages": MSG})
        self.assertAlmostEqual(g.spent, (1000 * PRICE["in"] + 100 * PRICE["out"]) / 1e6)
        with self.assertRaises(GatewayError) as c:
            g.complete({"role": "agent.background", "messages": MSG})
        self.assertEqual(c.exception.status, 402)
        g.complete({"role": "voice.core", "messages": MSG})  # the person's own voice turn is never blocked

    def test_redaction_applied_before_egress(self):
        g, bus = gw(["ok"], redact=lambda s: (s.replace("4111111111111111", "[CARD]"), {"CARD": 1} if "4111" in s else {}))
        g.complete({"role": "voice.core", "messages": [{"role": "user", "content": "card 4111111111111111"}]})
        self.assertNotIn("4111", json.dumps(g.up.calls[0]))
        self.assertTrue(any(e["type"] == "gateway.redacted" for e in bus.since(0)[0]))

    def test_effort_clamped_to_model(self):
        r = Registry.load(REG)
        self.assertEqual(r.effort("x", "muse-spark-1.3", "max"), "xhigh")
        self.assertEqual(r.effort("x", "muse-wonder-1.0", "max"), "max")

    def test_egress_allowlist(self):
        for url in ("http://api.meta.ai/v1", "https://evil.example/v1", "https://api.meta.ai.evil.example/v1"):
            with self.assertRaises(GatewayError):
                Upstream(url, "k", ["api.meta.ai"])
        Upstream("https://api.meta.ai/v1", "k", ["api.meta.ai"])

    def test_refuses_non_local_start(self):
        base = {"MODEL_API_KEY": "k", "EGRESS_ALLOWLIST": "api.meta.ai", "REGISTRY_PATH": REG}
        for env in ({**base, "RUNTIME_MODE": "local", "GATEWAY_BIND": "0.0.0.0:8787"},
                    {**base, "RUNTIME_MODE": "cloud", "GATEWAY_BIND": "127.0.0.1:8787"},
                    {"RUNTIME_MODE": "local", "GATEWAY_BIND": "127.0.0.1:8787", "EGRESS_ALLOWLIST": "api.meta.ai", "REGISTRY_PATH": REG}):
            with self.assertRaises(SystemExit):
                serve(env)

    def test_bus_readers_keep_their_place_past_the_cap(self):
        bus = EventBus()
        _, seq = bus.since(0)
        for i in range(600):
            bus.emit("x", {"i": i}, "t")
        evs, seq = bus.since(seq)
        self.assertEqual(len(evs), 500)  # oldest 100 aged out of memory, the rest arrive
        bus.emit("x", {"i": 600}, "t")
        evs, _ = bus.since(seq)
        self.assertEqual([e["data"]["i"] for e in evs], [600])

    def test_pages_served_with_csp_and_unknown_paths_404(self):
        g, bus = gw([])
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(g, bus, g.reg))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            from runtime.gateway import WEB
            for path, name in (("/", "voice.html"), ("/dashboard", "dashboard.html")):
                if (WEB / name).is_file():
                    r = urllib.request.urlopen(base + path)
                    self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
            with self.assertRaises(urllib.error.HTTPError) as c:
                urllib.request.urlopen(base + "/../../.env")
            self.assertEqual(c.exception.code, 404)
        finally:
            srv.shutdown()

    def test_http_end_to_end(self):
        g, bus = gw(["ok"])
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(g, bus, g.reg))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            h = json.load(urllib.request.urlopen(base + "/healthz"))
            self.assertTrue(h["ok"])
            req = urllib.request.Request(base + "/v1/chat/completions", data=json.dumps({"role": "voice.core", "messages": MSG}).encode(),
                                         headers={"Content-Type": "application/json"})
            r = urllib.request.urlopen(req)
            self.assertEqual(r.headers["x-gateway-model"], VOICE[0])
            self.assertEqual(json.load(r)["choices"][0]["message"]["content"], "hi")
            bad = urllib.request.Request(base + "/v1/chat/completions", data=b'{"model":"gpt-4o","messages":[{"role":"user","content":"x"}]}')
            with self.assertRaises(urllib.error.HTTPError) as c:
                urllib.request.urlopen(bad)
            self.assertEqual(c.exception.code, 400)
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
