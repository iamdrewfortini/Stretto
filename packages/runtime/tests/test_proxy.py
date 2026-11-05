# SPDX-License-Identifier: Apache-2.0
import json, os, threading, unittest, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from runtime.bus import EventBus
from runtime.gateway import Gateway, make_handler, serve, widen_csp
from runtime.registry import Registry

REG = os.path.join(os.path.dirname(__file__), "..", "..", "..", "docs", "spec", "models.registry.json")
CSP = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:"


class FakeStretto(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/api/events":
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            self.wfile.write(b"event: hello\ndata: {\"timer\": null}\n\n"); self.wfile.flush(); return
        b = b"<html>stretto __TOKEN__</html>" if self.path == "/" else json.dumps({"path": self.path, "token": self.headers.get("X-Stretto-Token")}).encode()
        self.send_response(200); self.send_header("Content-Type", "text/html" if self.path == "/" else "application/json")
        self.send_header("Content-Security-Policy", CSP); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0")); body = json.loads(self.rfile.read(n) or b"{}")
        b = json.dumps({"echo": body}).encode()
        self.send_response(201); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


def up(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class Proxy(unittest.TestCase):
    def setUp(self):
        self.st = up(ThreadingHTTPServer(("127.0.0.1", 0), FakeStretto))
        bus = EventBus(); reg = Registry.load(REG)
        self.gw = up(ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Gateway(reg, type("Up", (), {"key": "k", "base": "https://api.meta.ai/v1"})(), bus), bus, reg, None,
                                                                          {"host": "127.0.0.1", "port": self.st.server_address[1]})))
        self.base = f"http://127.0.0.1:{self.gw.server_address[1]}"

    def tearDown(self):
        self.gw.shutdown(); self.st.shutdown()

    def test_pages_and_api_pass_through_with_headers(self):
        r = urllib.request.urlopen(self.base + "/")
        self.assertIn(b"stretto", r.read())
        csp = r.headers["Content-Security-Policy"]
        self.assertIn("ws://127.0.0.1:8788", csp); self.assertIn("default-src 'self'", csp); self.assertIn("img-src 'self' data:", csp)
        req = urllib.request.Request(self.base + "/api/day?d=2026-11-04", headers={"X-Stretto-Token": "t0k"})
        self.assertEqual(json.load(urllib.request.urlopen(req)), {"path": "/api/day?d=2026-11-04", "token": "t0k"})
        req = urllib.request.Request(self.base + "/api/tasks", data=b'{"title": "x"}', headers={"Content-Type": "application/json"})
        r = urllib.request.urlopen(req); self.assertEqual(r.status, 201); self.assertEqual(json.load(r), {"echo": {"title": "x"}})

    def test_event_stream_passes_through(self):
        r = urllib.request.urlopen(self.base + "/api/events", timeout=5)
        self.assertEqual(r.readline(), b"event: hello\n")

    def test_v1_stays_with_the_runtime(self):
        h = json.load(urllib.request.urlopen(self.base + "/healthz"))
        self.assertTrue(h["ok"])

    def test_widen_csp_only_adds_the_voice_bridge(self):
        out = widen_csp(CSP)
        self.assertEqual(out.split("; ")[:3], CSP.split("; "))
        self.assertIn("connect-src 'self' ws://127.0.0.1:8788", out); self.assertNotIn("http:", out); self.assertNotIn("*", out)

    def test_refuses_non_loopback_stretto(self):
        env = {"RUNTIME_MODE": "local", "GATEWAY_BIND": "127.0.0.1:0", "MODEL_API_KEY": "k", "EGRESS_ALLOWLIST": "api.meta.ai",
               "REGISTRY_PATH": REG, "EVENT_LOG": "", "STRETTO_URL": "http://10.0.0.5:8760"}
        with self.assertRaises(SystemExit):
            serve(env)


if __name__ == "__main__":
    unittest.main()
