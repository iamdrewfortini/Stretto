# SPDX-License-Identifier: Apache-2.0
"""Runtime gateway (replaces Bifrost). The only holder of MODEL_API_KEY. Local-only by construction:
- listens on a loopback address only, and answers loopback clients only;
- calls only hosts in EGRESS_ALLOWLIST, over https, and never follows redirects;
- serves only models in MODEL-REGISTRY-01, resolved by role with ordered fallbacks.
Every upstream call is one `gateway.call` event on the bus (model, latency, tokens, cost, status). Stdlib only."""
import hashlib, ipaddress, json, os, random, threading, time, urllib.error, urllib.request, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from runtime.bus import EventBus
from runtime.registry import Registry

PASS_KEYS = {"messages", "tools", "tool_choice", "response_format", "temperature", "top_p", "stream", "max_completion_tokens",
             "parallel_tool_calls", "prompt_cache_key", "prompt_cache_retention", "safety_identifier", "top_logprobs"}
DROP_KEYS = {"stop", "logit_bias", "prediction", "web_search_options", "modalities", "audio", "frequency_penalty",
             "presence_penalty", "logprobs", "n", "seed", "user", "max_output_tokens"}
RETRY_STATUS = {429, 500, 502, 503, 504}
WEB = __import__("pathlib").Path(__file__).resolve().parents[2] / "web"
PAGES = {"/": "voice.html", "/dashboard": "dashboard.html", "/settings": "settings.html"}


class GatewayError(Exception):
    def __init__(self, status, message):
        super().__init__(message); self.status = status


def _loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise GatewayError(502, f"upstream redirect refused ({code})")


class Upstream:
    def __init__(self, base_url, key, allow):
        u = urlsplit(base_url)
        if u.scheme != "https" or u.hostname not in allow:
            raise GatewayError(500, f"egress refused: {u.scheme}://{u.hostname} is not an allowlisted https host")
        self.base, self.key, self.allow = base_url.rstrip("/"), key, set(allow)
        self.opener = urllib.request.build_opener(_NoRedirect)

    def post(self, path, body, timeout=120):
        url = self.base + path
        if urlsplit(url).hostname not in self.allow:
            raise GatewayError(500, "egress refused")
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
            "Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
            "Accept": "text/event-stream" if body.get("stream") else "application/json"})
        return self.opener.open(req, timeout=timeout)


class Limiter:
    """Token bucket per model, sized from the registry's per-team RPM."""
    def __init__(self):
        self.b, self.lock = {}, threading.Lock()

    @staticmethod
    def rpm(model):
        return 100 if model.endswith("-contributor") else 150 if model == "muse-image-1.0" else 3000

    def take(self, model):
        cap = self.rpm(model)
        with self.lock:
            tokens, t = self.b.get(model, (cap, time.monotonic()))
            now = time.monotonic(); tokens = min(cap, tokens + (now - t) * cap / 60.0)
            if tokens < 1:
                self.b[model] = (tokens, now); return False
            self.b[model] = (tokens - 1, now); return True


def normalize(body, model, effort):
    out = {k: v for k, v in body.items() if k in PASS_KEYS}
    if "max_tokens" in body and "max_completion_tokens" not in out:
        out["max_completion_tokens"] = body["max_tokens"]
    out["model"] = model
    if effort:
        out["reasoning_effort"] = effort
    return out


def check_tool_pairs(messages):
    """Meta returns 400 unless every assistant tool_call is answered by a tool message with its id. Catch it locally."""
    pending = set()
    for m in messages:
        if m.get("role") == "assistant":
            if pending:
                break
            pending = {tc["id"] for tc in m.get("tool_calls") or []}
        elif m.get("role") == "tool":
            pending.discard(m.get("tool_call_id"))
        elif pending:
            break
    if pending:
        raise GatewayError(400, f"unanswered tool_call ids: {sorted(pending)}")


def redact_messages(messages, redact):
    counts = {}
    out = []
    for m in messages:
        m = dict(m)
        if isinstance(m.get("content"), str):
            m["content"], c = redact(m["content"])
            for k, v in c.items():
                counts[k] = counts.get(k, 0) + v
        out.append(m)
    return out, counts


class Gateway:
    def __init__(self, registry, upstream, bus, redact=None, spend_limit=None, sleep=time.sleep):
        self.reg, self.up, self.bus, self.redact = registry, upstream, bus, redact
        self.spend_limit, self.spent, self.lim, self.sleep, self.lock = spend_limit, 0.0, Limiter(), sleep, threading.Lock()

    def _record(self, rid, role, model, t0, status, usage=None, error=None, attempt=1):
        cost = self.reg.cost(model, usage) if usage else None
        with self.lock:
            self.spent += cost or 0.0
        self.bus.emit("gateway.call", {"request_id": rid, "role": role, "model": model, "attempt": attempt, "status": status,
                                       "latency_ms": round((time.monotonic() - t0) * 1000), "usage": usage, "cost_usd": cost,
                                       "spent_usd": round(self.spent, 6), "error": error}, "runtime.gateway", correlation_id=rid)

    def prepare(self, body):
        role, model = body.get("role"), body.get("model")
        if isinstance(model, str) and model.startswith("meta/"):
            model = model[5:]
        try:
            chain = self.reg.chain(role=role, model=model)
        except LookupError as e:
            raise GatewayError(400, str(e))
        if role and role.startswith("agent.") and self.spend_limit is not None and self.spent >= self.spend_limit:
            raise GatewayError(402, f"spend limit reached (${self.spent:.4f} >= ${self.spend_limit:.2f}); background agents paused")
        msgs = body.get("messages")
        if not isinstance(msgs, list) or not msgs:
            raise GatewayError(400, "messages must be a non-empty list")
        check_tool_pairs(msgs)
        redactions = {}
        if self.redact:
            msgs, redactions = redact_messages(msgs, self.redact)
        return role, chain, dict(body, messages=msgs), redactions

    def open(self, body):
        """Try each model in the chain with bounded retries. Returns (response, model, rid, t0, role, attempt)."""
        role, chain, body, redactions = self.prepare(body)
        rid = "req_" + uuid.uuid4().hex[:16]
        if redactions:
            self.bus.emit("gateway.redacted", {"request_id": rid, "counts": redactions}, "runtime.gateway", correlation_id=rid)
        last = None
        for model in chain:
            req = normalize(body, model, self.reg.effort(role, model, body.get("effort")))
            floor = self.reg.bindings.get(role or "", {}).get("min_completion_tokens")
            if floor and req.get("max_completion_tokens", floor) < floor:
                req["max_completion_tokens"] = floor  # hidden reasoning counts against the cap; never let it eat the answer
            for attempt in range(1, 4):
                t0 = time.monotonic()
                if not self.lim.take(model):
                    last = GatewayError(429, f"local rate limit for {model}"); self._record(rid, role, model, t0, 429, error="local-limit", attempt=attempt); break
                try:
                    return self.up.post("/chat/completions", req), model, rid, t0, role, attempt
                except urllib.error.HTTPError as e:
                    detail = e.read().decode(errors="replace")[:300]
                    self._record(rid, role, model, t0, e.code, error=detail, attempt=attempt)
                    last = GatewayError(e.code, detail)
                    if e.code not in RETRY_STATUS:
                        if e.code in (400, 401, 403, 422):
                            raise last
                        break
                    ra = e.headers.get("Retry-After")
                    self.sleep(min(float(ra), 10.0) if ra and ra.replace(".", "", 1).isdigit() else random.uniform(0, 0.5 * 2 ** attempt))
                except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                    self._record(rid, role, model, t0, 0, error=repr(e)[:200], attempt=attempt)
                    last = GatewayError(502, f"upstream unreachable: {e}")
                    self.sleep(random.uniform(0, 0.5 * 2 ** attempt))
        raise last or GatewayError(502, "no model answered")

    def complete(self, body):
        resp, model, rid, t0, role, attempt = self.open(dict(body, stream=False))
        data = json.load(resp)
        self._record(rid, role, model, t0, 200, usage=data.get("usage"), attempt=attempt)
        return data, model, rid


INGEST_PREFIXES = ("telemetry.", "activity.", "attention.", "narration.", "consent.")


def ingest(bus, body):
    """Sensor events from the person's own desktop. Only telemetry-shaped types, and ledger entries marked auto,
    so a sensor can never forge a manual entry, a model call or a voice turn. Returns (status, response)."""
    if not isinstance(body, dict) or not isinstance(body.get("events"), list):
        return 400, {"error": "body must be {\"source_host\": str, \"events\": [...]}"}
    evs = body["events"]
    if len(evs) > 200:
        return 413, {"error": "at most 200 events per request"}
    host = str(body.get("source_host") or "unknown")[:64]
    bad = []
    for e in evs:
        t, d = (e.get("type"), e.get("data")) if isinstance(e, dict) else (None, None)
        ok = isinstance(t, str) and isinstance(d, dict) and (t.startswith(INGEST_PREFIXES) or (t == "ledger.event.added" and d.get("origin") == "auto"))
        if not ok:
            bad.append(t if isinstance(t, str) else repr(t)[:40])
    if bad:
        return 400, {"error": "rejected event types", "types": sorted(set(bad))}
    for e in evs:
        bus.emit(e["type"], e["data"], f"sensors@{host}")
    return 200, {"accepted": len(evs)}


SETTINGS_SOURCES = ("window", "input", "pointer", "idle")


def _env_path(env):
    return (env or {}).get("HUMANFLOW_ENV") or os.environ.get(
        "HUMANFLOW_ENV", os.path.expanduser("~/.config/humanflow/runtime.env"))


def _consent_path(env):
    return (env or {}).get("SENSORS_CONSENT") or os.environ.get(
        "SENSORS_CONSENT", os.path.expanduser("~/.config/humanflow/consent.json"))


def store_key(env_path, key):
    """Write MODEL_API_KEY into the external env (0600, atomic).

    The twin of scripts/set_key.write_key and the dev server endpoint:
    returns (length, sha256 fingerprint) and never the key itself.
    """
    key = str(key).strip()
    if len(key) < 20:
        raise ValueError("key looks too short; refusing to save")
    lines, done = [], False
    if os.path.isfile(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f.read().splitlines():
                if line.startswith("MODEL_API_KEY="):
                    lines.append("MODEL_API_KEY=" + key); done = True
                else:
                    lines.append(line)
    if not done:
        lines.append("MODEL_API_KEY=" + key)
    parent = os.path.dirname(os.path.abspath(env_path))
    os.makedirs(parent, exist_ok=True)
    tmp = env_path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, ("\n".join(lines) + "\n").encode())
    finally:
        os.close(fd)
    os.replace(tmp, env_path)
    os.chmod(env_path, 0o600)
    return len(key), hashlib.sha256(key.encode()).hexdigest()[:8]


def _read_consent(path):
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def consent_state(path, now=None, person="owner"):
    """Same grant shape the sensors ConsentStore reads, plus prefs."""
    now = time.time() if now is None else now
    raw = _read_consent(path)
    g = raw.get("grants", {}).get(person) or {}
    src = g.get("sources", {}) if not g.get("revoked") else {}
    return {"sources": {s: bool(src.get(s) and now < src[s])
                        for s in SETTINGS_SOURCES},
            "titles": raw.get("titles")}


def apply_consent(path, action, sources=None, ttl_s=None, titles=None,
                  now=None, person="owner"):
    """Grant/revoke/prefs write in the sensors consent shape (0600).

    Grants need a positive TTL; revoke is immediate. A revoke with no
    sources revokes everything. The titles preference and the grants
    preserve each other across writes from either process.
    """
    now = time.time() if now is None else now
    sources = list(sources or [])
    bad = [s for s in sources if s not in SETTINGS_SOURCES]
    if bad:
        raise ValueError(f"unknown sensor source: {bad}")
    raw = _read_consent(path)
    grants = raw.setdefault("grants", {})
    g = grants.setdefault(person, {"sources": {}, "revoked": False})
    if action == "grant":
        if not ttl_s or ttl_s <= 0:
            raise ValueError("consent needs a positive time limit")
        g["revoked"] = False
        for s in sources:
            g["sources"][s] = now + ttl_s
        changed = sorted(sources)
    elif action == "revoke":
        if sources:
            for s in sources:
                g["sources"].pop(s, None)
            changed = sorted(sources)
        else:
            g["sources"] = {}
            g["revoked"] = True
            changed = sorted(SETTINGS_SOURCES)
    elif action == "set_titles":
        changed = []
    else:
        raise ValueError(f"unknown consent action: {action}")
    if titles is not None:
        raw["titles"] = bool(titles)
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(raw, sort_keys=True).encode())
    finally:
        os.close(fd)
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    return {"person": person, "action": action, "sources": changed,
            "titles": raw.get("titles")}


def make_handler(gw, bus, registry, core=None, env=None):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "meta-coherence-gateway/1"

        def log_message(self, *a):
            pass

        def _send(self, status, obj, headers=None):
            b = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers(); self.wfile.write(b)

        def _guard(self):
            if not _loopback(self.client_address[0]):
                self._send(403, {"error": "gateway answers loopback clients only"}); return False
            return True

        def do_GET(self):
            if not self._guard():
                return
            if self.path == "/healthz":
                return self._send(200, {"ok": True, "key_present": bool(gw.up.key), "upstream": gw.up.base, "spent_usd": round(gw.spent, 6)})
            if self.path == "/v1/models":
                return self._send(200, {"object": "list", "data": [{"id": k, "object": "model", "status": v.get("status"),
                                        "roles": v.get("roles", [])} for k, v in registry.models.items()]})
            if self.path == "/v1/settings/consent":
                return self._send(200, consent_state(_consent_path(env)))
            if self.path.startswith("/v1/events"):
                return self._events()
            page = PAGES.get(self.path.split("?", 1)[0])
            if page and (WEB / page).is_file():
                return self._page(WEB / page)
            self._send(404, {"error": "not found"})

        def _page(self, path):
            b = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline' blob:; "
                             "style-src 'self' 'unsafe-inline'; connect-src 'self' ws://127.0.0.1:8788 ws://localhost:8788; "
                             "worker-src blob: 'self'; img-src 'self' data:")
            self.end_headers(); self.wfile.write(b)

        def _events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache"); self.end_headers()
            idx = 0  # send recent history first, then live events
            try:
                while True:
                    evs, idx = bus.since(idx)
                    for ev in evs:
                        self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                    self.wfile.flush(); bus.wait(15)
                    if not evs:
                        self.wfile.write(b": keepalive\n\n")
            except (BrokenPipeError, ConnectionResetError):
                return

        def do_POST(self):
            if not self._guard():
                return
            if self.path not in ("/v1/chat/completions", "/v1/turn", "/v1/ingest",
                                 "/v1/settings/key", "/v1/settings/consent"):
                return self._send(404, {"error": "not found"})
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if n > 8 * 1024 * 1024:
                    raise GatewayError(413, "body too large")
                body = json.loads(self.rfile.read(n) or b"{}")
                if self.path == "/v1/ingest":
                    return self._send(*ingest(bus, body))
                if self.path == "/v1/settings/key":
                    try:
                        n, fp = store_key(_env_path(env), body.get("api_key", ""))
                    except ValueError as e:
                        raise GatewayError(400, str(e))
                    return self._send(200, {"ok": True, "len": n, "fingerprint": fp})
                if self.path == "/v1/settings/consent":
                    if not isinstance(body, dict):
                        raise GatewayError(400, "body must be an object")
                    ttl = body.get("ttl_s")
                    try:
                        ev = apply_consent(
                            _consent_path(env), body.get("action", ""),
                            sources=body.get("sources") or [],
                            ttl_s=float(ttl) if ttl is not None else None,
                            titles=body.get("titles"))
                    except (ValueError, TypeError) as e:
                        raise GatewayError(400, str(e))
                    bus.emit("consent.changed", ev, "runtime.gateway")
                    return self._send(200, {"ok": True, "event": ev,
                                            "state": consent_state(_consent_path(env))})
                if self.path == "/v1/turn":
                    text = body.get("text") if isinstance(body, dict) else None
                    if core is None or not isinstance(text, str) or not text.strip():
                        raise GatewayError(400, "body must be {\"text\": \"...\"}")
                    return self._send(200, core.turn(text.strip()[:4000]))
                if body.get("stream"):
                    return self._stream(body)
                data, model, rid = gw.complete(body)
                self._send(200, data, {"x-gateway-model": model, "x-request-id": rid})
            except GatewayError as e:
                self._send(e.status, {"error": str(e)})
            except json.JSONDecodeError:
                self._send(400, {"error": "body is not JSON"})

        def _stream(self, body):
            resp, model, rid, t0, role, attempt = gw.open(body)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache")
            self.send_header("x-gateway-model", model); self.send_header("x-request-id", rid); self.end_headers()
            usage, status = None, 200
            try:
                for raw in resp:
                    self.wfile.write(raw); self.wfile.flush()
                    line = raw.decode(errors="replace").strip()
                    if line.startswith("data: {"):
                        try:
                            u = json.loads(line[6:]).get("usage")
                            usage = u or usage
                        except ValueError:
                            pass
            except (BrokenPipeError, ConnectionResetError):
                status = 499
            finally:
                gw._record(rid, role, model, t0, status, usage=usage, attempt=attempt)
            self.close_connection = True

    return H


def serve(env=os.environ):
    host, port = env.get("GATEWAY_BIND", "127.0.0.1:8787").rsplit(":", 1)
    if env.get("RUNTIME_MODE") != "local" or not _loopback(host):
        raise SystemExit("refusing to start: RUNTIME_MODE must be local and GATEWAY_BIND a loopback address")
    allow = [h.strip() for h in env.get("EGRESS_ALLOWLIST", "").split(",") if h.strip()]
    key = env.get("MODEL_API_KEY", "")
    if not key:
        raise SystemExit("refusing to start: MODEL_API_KEY missing (run through scripts/with_env.sh)")
    reg = Registry.load(env.get("REGISTRY_PATH", "docs/spec/models.registry.json"))
    bus = EventBus(env.get("EVENT_LOG", "var/events.jsonl"))
    try:
        from perception.redact import redact
    except ImportError:
        redact = None
    limit = float(env["SPEND_LIMIT_USD"]) if env.get("SPEND_LIMIT_USD") else None
    gw = Gateway(reg, Upstream(env.get("META_BASE_URL", "https://api.meta.ai/v1"), key, allow), bus, redact=redact, spend_limit=limit)
    from runtime.core import VoiceCore
    from runtime.tools import Tools
    bus.seed_recent()
    tools = Tools(bus, owner=env.get("OWNER_ID", "owner"))
    core = VoiceCore(gw, tools, bus)
    srv = ThreadingHTTPServer((host, int(port)), make_handler(gw, bus, reg, core, env=dict(env)))
    srv.daemon_threads = True
    parts = {}
    try:  # background agent pipelines (optional module)
        from runtime.agents import start_agents
        start_agents(bus, gw, tools); parts["agents"] = True
    except ImportError:
        parts["agents"] = False
    try:  # realtime voice bridge (optional module)
        from runtime.voice import start_voice_thread
        start_voice_thread(core, bus, env); parts["voice"] = env.get("VOICE_BIND", "127.0.0.1:8788")
    except ImportError:
        parts["voice"] = False
    bus.emit("gateway.started", {"bind": f"{host}:{port}", "egress": allow, "redaction": bool(redact), **parts}, "runtime.gateway")
    print(f"gateway on http://{host}:{port} -> {gw.up.base} (egress: {','.join(allow)})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    serve()
