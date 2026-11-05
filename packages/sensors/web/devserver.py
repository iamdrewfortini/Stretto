# SPDX-License-Identifier: Apache-2.0
"""Demo dev server: the local runtime surface the dashboard needs.

Implements the ingest contract from the spec (POST /v1/ingest),
the SSE feed the Attention panel consumes (GET /v1/events), and the
dashboard page (GET /dashboard, panel fragment inlined). Loopback
only, stdlib only, in-memory bus. This is a demo harness for the
sensors package; the production runtime remains packages/runtime
(see Integration notes in the sensors final report).
"""
import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ALLOWED = ("telemetry.", "activity.", "attention.", "narration.",
           "consent.")
HERE = os.path.dirname(os.path.abspath(__file__))
BUS = []
LOCK = threading.Lock()
COND = threading.Condition()
SEQ = [0]


def validate(payload):
    """Return (events, error). Pure function; unit-tested directly."""
    events = payload.get("events")
    if not isinstance(events, list) or not events:
        return None, "events must be a non-empty list"
    if len(events) > 200:
        return None, "at most 200 events per request"
    bad = []
    for e in events:
        t = e.get("type", "")
        if t.startswith(ALLOWED):
            continue
        if t == "ledger.event.added" and \
                e.get("data", {}).get("origin") == "auto":
            continue
        bad.append(t)
    if bad:
        return None, f"bad types: {bad}"
    return events, None


def wrap(payload, now=None):
    now = time.time() if now is None else now
    host = payload.get("source_host", "unknown")
    out = []
    with LOCK:
        for e in payload["events"]:
            SEQ[0] += 1
            out.append({
                "id": f"e{SEQ[0]}", "type": e["type"], "ts": now,
                "source": f"sensors@{host}", "subject": "owner",
                "causation_id": None, "correlation_id": None,
                "schema": 1, "data": e.get("data", {})})
        BUS.extend(out)
        del BUS[:-500]
    with COND:
        COND.notify_all()
    return out


SETTINGS_HTML = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1'>
<title>Humanflow settings</title><style>
body{font-family:system-ui;margin:16px;max-width:560px}
@media (prefers-color-scheme: dark){body{background:#111;color:#eee}}
input{width:100%;padding:8px} button{margin-top:8px;padding:8px 16px}
</style></head><body><h1>Settings</h1>
<p>Paste your Meta Model API key. It is saved to
<code>~/.config/humanflow/runtime.env</code> (mode 600, outside the
repo) and never displayed, logged or sent anywhere except the
gateway's own calls to api.meta.ai. Loopback only.</p>
<form id="f"><input id="k" type="password" autocomplete="off"
placeholder="MODEL_API_KEY" aria-label="Meta Model API key">
<button type="submit">Save key</button></form>
<p id="out" role="status"></p>
<p><a href="/dashboard">Back to dashboard</a></p>
<script>
document.getElementById("f").addEventListener("submit", function (ev) {
  ev.preventDefault();
  var out = document.getElementById("out");
  var key = document.getElementById("k").value;
  fetch("/v1/settings/key", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({api_key: key})})
  .then(function (r) { return r.json().then(function (j) {
    if (!r.ok) throw new Error(j.error || "save failed"); return j; }); })
  .then(function (j) {
    document.getElementById("k").value = "";
    out.textContent = "Saved (len=" + j.len + " sha256:" + j.fingerprint +
      "). Restart the gateway: make gateway";
  }).catch(function (e) { out.textContent = String(e.message || e); });
});
</script></body></html>"""


def save_key(api_key):
    """Write MODEL_API_KEY into the external env. Returns (len, fp)."""
    import hashlib
    sys_path = os.path.join(HERE, "..", "..", "..", "scripts")
    sys.path.insert(0, os.path.abspath(sys_path))
    try:
        from set_key import write_key
    finally:
        sys.path.pop(0)
    env_path = os.environ.get(
        "HUMANFLOW_ENV",
        os.path.expanduser("~/.config/humanflow/runtime.env"))
    from pathlib import Path
    return write_key(Path(env_path), api_key)


def dashboard_html():
    frag = open(os.path.join(HERE, "attention-panel.html"),
                encoding="utf-8").read()
    body = frag.split("-->", 1)[1] if "-->" in frag else frag
    return ("<!doctype html><html><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Humanflow — Attention</title><style>"
            "body{font-family:system-ui;margin:16px;max-width:900px}"
            "@media (prefers-color-scheme: dark){body{background:#111;color:#eee}}"
            "#attention-timeline div{height:14px}"
            "</style></head><body><h1>Humanflow</h1>"
            "<p><a href=\"/settings\">Settings</a></p>"
            + body + "</body></html>")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path == "/v1/settings/key":
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                length, fp = save_key(str(body.get("api_key", "")))
            except ValueError as e:
                return self._send(400, json.dumps({"error": str(e)}))
            except Exception:
                return self._send(400, json.dumps({"error": "bad request"}))
            return self._send(200, json.dumps(
                {"ok": True, "len": length, "fingerprint": fp}))
        if self.path != "/v1/ingest":
            return self._send(404, json.dumps({"error": "not found"}))
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, TypeError):
            return self._send(400, json.dumps({"error": "bad json"}))
        _events, err = validate(payload)
        if err:
            return self._send(400, json.dumps({"error": err}))
        out = wrap(payload)
        return self._send(200, json.dumps({"accepted": len(out)}))

    def do_GET(self):
        if self.path == "/settings":
            return self._send(200, SETTINGS_HTML, "text/html")
        if self.path in ("/", "/dashboard"):
            return self._send(200, dashboard_html(), "text/html")
        if self.path == "/health":
            return self._send(200, json.dumps({"ok": True,
                                               "events": len(BUS)}))
        if self.path == "/v1/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            seen = 0
            try:
                while True:
                    with LOCK:
                        fresh = BUS[seen:]
                        seen = len(BUS)
                    for e in fresh:
                        self.wfile.write(
                            f"data: {json.dumps(e)}\n\n".encode())
                    self.wfile.flush()
                    with COND:
                        COND.wait(timeout=5)
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
            return
        return self._send(404, json.dumps({"error": "not found"}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    a = ap.parse_args()
    ThreadingHTTPServer.daemon_threads = True
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"dashboard http://127.0.0.1:{a.port}/dashboard", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
