# SPDX-License-Identifier: Apache-2.0
"""Local JSON API and static UI. Loopback only. Reads check the Host header (DNS rebinding); writes also need the per-install token."""
import datetime as dt
import hashlib
import hmac
import json
import mimetypes
import os
import queue
import secrets
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import analyze, attention, bundle, calendars, challenges, coach, coherence, consent, daycache, demo, enroll, events, folding, gamify, graphmap, honeycomb, insights, merge, meta, patterns, segment, topics, voicetree

STATIC = os.path.join(os.path.dirname(__file__), "static")
MAX_BODY = 8_000_000   # an agent's catch-up batch can be large; 8 MB is far above a real batch and far below abuse
LOOPBACK_HOSTS = ("127.0.0.1", "localhost")


def _whole(v, name, lo, hi):
    """A whole number lo..hi. Accepts 300 and '300'; rejects booleans, fractions, text and out-of-range values with a clear message."""
    ok = not isinstance(v, bool) and isinstance(v, (int, float, str))
    try:
        f = float(v) if ok else None
    except ValueError:
        f = None
    if f is None or f != int(f) or not lo <= int(f) <= hi:
        raise ValueError(f"{name} must be a whole number {lo}..{hi}")
    return int(f)


def _iso(v, name):
    """YYYY-MM-DD and nothing else (newer Pythons would also accept 20261104 and ISO weeks)."""
    import re
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        raise ValueError(f"{name} must be YYYY-MM-DD")
    try:
        return dt.date.fromisoformat(v)
    except ValueError:
        raise ValueError(f"{name} is not a real date") from None


def _unix(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 631_152_000 <= v <= 4_102_444_800:
        raise ValueError(f"{name} must be a unix time in seconds (1990..2100) or null")
    return float(v)


def day_bounds(date=None):
    d = dt.date.fromisoformat(date) if date else dt.date.today()
    t0 = dt.datetime.combine(d, dt.time()).timestamp()
    return d.isoformat(), t0, (dt.datetime.combine(d, dt.time()) + dt.timedelta(days=1)).timestamp()


class Api:
    def __init__(self, store):
        self.s = store
        self.bus = events.Bus()

    def timer(self):
        """The running timer row, or None: exactly the GET /api/timer body."""
        return (self.s.q("SELECT * FROM timers WHERE end IS NULL ORDER BY id DESC LIMIT 1") or [None])[0]

    def rules(self):
        return [(r["field"], r["pattern"], r["category"]) for r in self.s.q("SELECT field,pattern,category FROM rules ORDER BY id")]

    def goal_s(self):
        return int(float(self.s.setting("goal_min", 240)) * 60)

    def goal_week_min(self):
        v = self.s.setting("goal_week_min")
        return int(float(v)) if v is not None else max(60, min(4800, 5 * int(float(self.s.setting("goal_min", 240)))))

    def budgets(self):
        """{category: minutes}. A category that is absent has no budget."""
        try:
            b = json.loads(self.s.setting("budgets", "{}"))
        except ValueError:
            b = {}
        return b if isinstance(b, dict) else {}

    def budget_categories(self):
        """The categories a budget may name: everything the rule set can produce (built-in and the person's own), except Idle."""
        cats = {c for _, _, c in segment.DEFAULT_RULES} | {c for _, _, c in self.rules()} | set(segment.FOCUS) | {"Browsing", "Other"}
        cats.discard("Idle")
        return cats

    def settings(self):
        return dict(goal_min=int(float(self.s.setting("goal_min", 240))), goal_week_min=self.goal_week_min(), budgets=self.budgets(),
                    model=meta.current_model(self.s), save_raw_on_host=self.s.setting("save_raw_on_host", "1") != "0",
                    value_metric=self.s.setting("value_metric", "time"), horizon_weeks=int(float(self.s.setting("horizon_weeks", 4))),
                    coach_met=int(float(self.s.setting("coach_met", 0))), coach_missed=int(float(self.s.setting("coach_missed", 0))))

    def budget_usd(self):
        return float(self.s.setting("insight_budget_usd", 0.25))     # daily cap on Meta spend; direct mode only

    def blocks(self, events):
        """Merge sources by priority, then cut into blocks. Returns (blocks, dropped-per-source)."""
        kept, dropped = merge.timeline(events)
        return segment.blocks(kept, self.rules()), dropped

    @staticmethod
    def window(upto_iso, days):
        """[start of the first day, end of upto_iso) on WHOLE calendar days, so a daylight-saving change can never cut a day in half."""
        first = (dt.date.fromisoformat(upto_iso) - dt.timedelta(days=days - 1)).isoformat()
        return daycache.day_range(first)[0], daycache.day_range(upto_iso)[1]

    def patterns(self, days=90):
        days = max(5, min(int(days), 730))
        return patterns.profile_from_summaries(daycache.ensure(self.s, self.rules(), *self.window(dt.date.today().isoformat(), days)))

    def prev_summary(self, t0):
        """(iso date, cached day summary) of the latest earlier day that has any data, or (None, None). Empty days are skipped."""
        r = self.s.q("SELECT MAX(ts) AS t FROM events WHERE ts<?", (t0,))
        if not r or r[0]["t"] is None:
            return None, None
        d = dt.date.fromtimestamp(r[0]["t"]).isoformat()
        return d, daycache.ensure(self.s, self.rules(), *daycache.day_range(d)).get(d)

    DELTA_KEYS = ("focus_s", "distraction_s", "idle_s", "total_s", "loss_s")

    def summary_out(self, summ, loss, t0, raw):
        """The day summary as the API returns it: the measured summary plus the previous period, the signed change, and cross-device overlap."""
        out = dict(summ)
        # concurrent_*: how much simultaneous multi-computer activity existed in the raw data (measured, resolved onto one timeline, counted once).
        # overlap_*: how much of that is STILL counted twice in the resolved timeline. It is computed, not assumed, so a regression would show here.
        out["concurrent_s"], out["concurrent_devices"] = merge.overlap(raw)
        out["overlap_s"], out["overlap_devices"] = merge.overlap(merge.timeline(raw)[0])
        pd, ps = self.prev_summary(t0)
        if not ps:
            out["prev"] = None                                              # no earlier day with data: delta and delta_pct are absent
            return out
        now = dict(summ, loss_s=loss)
        out["prev"] = dict(date=pd, **{k: ps[k] for k in self.DELTA_KEYS})
        out["delta"] = {k: int(round(now[k] - ps[k])) for k in self.DELTA_KEYS}
        out["delta_pct"] = {k: (round((now[k] - ps[k]) / ps[k], 2) if ps[k] else None) for k in self.DELTA_KEYS}
        return out

    def attention(self, date=None):
        iso, t0, t1 = day_bounds(date)
        bl, _ = self.blocks(self.s.events(t0, t1))
        out = dict(date=iso, **attention.measure(bl))
        _, ps = self.prev_summary(t0)
        prev = ps.get("attention_score") if ps else None
        out["prev_score"] = prev
        out["delta_score"] = (out["score"] - prev) if (prev is not None and out.get("enough")) else None
        return out

    def sources(self):
        rows = self.s.q("SELECT device, src, COUNT(*) AS events, MIN(ts) AS first_ts, MAX(ts+dur) AS last_ts, SUM(dur) AS seconds FROM events GROUP BY device, src ORDER BY device, src")
        cur = {(r["device"], r["src"]): r for r in self.s.q("SELECT * FROM sources")}
        for r in rows:
            c = cur.get((r["device"], r["src"]))
            r.update(cursor_set=bool(c and c["cursor"]), last_run=c["last_run"] if c else None, estimated=r["src"].split(":")[0].endswith("-history"))
        return rows

    def day(self, date=None):
        iso, t0, t1 = day_bounds(date)
        raw = self.s.events(t0, t1)
        bl, dropped = self.blocks(raw)
        used = {}
        for e in raw:
            used[e["src"]] = used.get(e["src"], 0) + 1
        found, loss = analyze.findings(bl)
        summ = analyze.summary(bl)
        fbd = self.focus_history(iso, supplied={iso: daycache.summarize(bl, loss=loss)})
        goal = self.goal_s()
        total_xp = sum(gamify.xp_for_day(v, goal) for v in fbd.values()) + challenges.bonus_xp(self.s)
        longest = max([b["seconds"] for b in bl if b["category"] in segment.FOCUS] or [0])
        st = gamify.streak(fbd, iso, goal)
        return dict(date=iso, goal_s=goal, summary=self.summary_out(summ, loss, t0, raw), loss_s=loss, findings=found, transitions=analyze.transitions(bl),
                    blocks=[{k: v for k, v in b.items() if k != "key"} for b in bl],
                    xp=dict(today=gamify.xp_for_day(summ["focus_s"], goal), **gamify.level(total_xp)), streak=st,
                    badges=gamify.badges(sum(fbd.values()), longest, st),
                    sources=[dict(src=k, events=v, dropped=dropped.get(k, 0), estimated=k.split(":")[0].endswith("-history")) for k, v in sorted(used.items())],
                    simulated=bool(used.get("simulated")))

    def focus_history(self, upto_iso, days=120, supplied=None):
        """Focus seconds per day for the `days` days up to and including upto_iso, from the per-day cache."""
        sums = daycache.ensure(self.s, self.rules(), *self.window(upto_iso, days), supplied=supplied)
        return {d: s["focus_f"] for d, s in sums.items()}

    def range(self, days=7):
        days = max(1, min(int(days), 90))
        iso = dt.date.today().isoformat()
        sums = daycache.ensure(self.s, self.rules(), *self.window(iso, days))
        sim_days = {r["d"] for r in self.s.q("SELECT DISTINCT date(ts,'localtime') AS d FROM events WHERE src='simulated' AND ts>=? AND ts<?", self.window(iso, days))}
        empty = dict(focus_s=0, distraction_s=0, total_s=0, by_category={}, hours_focus=[0] * 24, loss_s=0)
        out = []
        for i in range(days - 1, -1, -1):
            d = (dt.date.fromisoformat(iso) - dt.timedelta(days=i)).isoformat()
            s = sums.get(d, empty)
            out.append(dict(date=d, focus_s=s["focus_s"], distraction_s=s["distraction_s"], total_s=s["total_s"], by_category=s["by_category"],
                            hours=s["hours_focus"], loss_s=s["loss_s"], simulated=d in sim_days))
        before = (dt.date.fromisoformat(iso) - dt.timedelta(days=days)).isoformat()          # the day before the range starts
        prev = daycache.ensure(self.s, self.rules(), *self.window(before, days))
        return dict(days=out, goal_s=self.goal_s(), prev_total_focus_s=sum(v["focus_s"] for v in prev.values()))


class Handler(BaseHTTPRequestHandler):
    server_version = "Stretto"
    api = None
    token = ""
    port = 0
    allowed = ()          # exact Host header values accepted
    remote = False        # listening beyond loopback: every API call needs the token and the page never carries it

    def log_message(self, *a):
        pass

    def _send(self, code, obj=None, raw=None, ctype="application/json", filename=None):
        body = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:")
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self):
        return self.headers.get("Host", "") in self.allowed

    def _token_ok(self):
        return hmac.compare_digest(self.headers.get("X-Stretto-Token", ""), self.token)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("body too large")
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, dict(error="bad host"))
        u = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        if u.path == "/api/events":
            # the live stream needs the same token as a write. EventSource cannot set headers, so ?token= is accepted too.
            if not (self._token_ok() or hmac.compare_digest(q.get("token", ""), self.token)):
                return self._send(403, dict(error="token required"))
            return self._stream(q)
        if u.path.startswith("/api/"):
            p = self._principal()
            if p is None and self.remote:
                return self._send(403, dict(error="token required"))
            if p and p[0] == "device" and not self._device_scope("GET", u.path, q, {}, p[1]):
                return self._send(403, dict(error="out_of_scope", hint="a device key may only read its own cursor and consent state"))
        try:
            return self._route("GET", u.path, q, {})
        except (ValueError, KeyError, TypeError) as e:                 # a bad query parameter is the caller's mistake, not a server fault
            return self._send(400, dict(error=str(e)[:160]))
        except Exception as e:
            return self._send(500, dict(error=type(e).__name__))

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, dict(error="bad host"))
        u = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        try:
            body = self._body()
            if u.path != "/api/agent/register":                 # the one route that is authorised by a one-time code instead
                p = self._principal()
                if p is None:
                    return self._send(403, dict(error="token required"))
                if p[0] == "device" and not self._device_scope("POST", u.path, q, body, p[1]):
                    return self._send(403, dict(error="out_of_scope", hint="a device key may only send its own data and revoke its own consent"))
            return self._route("POST", u.path, q, body)
        except (ValueError, KeyError, TypeError) as e:
            return self._send(400, dict(error=str(e)[:120]))
        except Exception as e:
            return self._send(500, dict(error=type(e).__name__))

    def _stream(self, q):
        """Server-sent events. One thread per connection, blocking on that connection's queue; a heartbeat comment every heartbeat_s."""
        bus = self.api.bus
        raw = self.headers.get("Last-Event-ID") or q.get("last_event_id") or ""
        last = int(raw) if raw.isdigit() else None
        sub, replay = bus.subscribe(last)
        try:
            events.ensure_watcher(self.api, bus)                       # baseline first, so nothing that already exists is announced as new
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(b"retry: 3000\n\n")
            if replay is None:                                         # first connect, or an id we no longer hold: say hello, the client refetches
                self.wfile.write(events.frame((bus.stamp(), "hello", dict(server_ts=time.time(), timer=self.api.timer()))))
            else:
                for msg in replay:
                    self.wfile.write(events.frame(msg))
            self.wfile.flush()
            while True:
                try:
                    self.wfile.write(events.frame(sub.get(timeout=bus.heartbeat_s)))
                except queue.Empty:
                    self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            bus.unsubscribe(sub)

    def _principal(self):
        """('admin', None) for the install's master token, ('device', id) for an enrolled agent's key, else None."""
        if self._token_ok():
            return ("admin", None)
        dev = enroll.device_for_key(self.api.s, self.headers.get("X-Stretto-Device-Key", ""))
        return ("device", dev) if dev else None

    @staticmethod
    def _device_scope(method, path, q, body, dev):
        """What an enrolled agent may do, and only for its own device id."""
        own = lambda v: str(v if v is not None else "local") == dev
        if method == "GET" and path in ("/api/cursor", "/api/consent"):
            return own(q.get("device"))
        if (method, path) == ("GET", "/api/consent/notice"):
            return True
        if (method, path) in (("POST", "/api/ingest"), ("POST", "/api/agent/environment")):
            return own(body.get("device"))
        if (method, path) == ("POST", "/api/consent"):
            return own(body.get("device")) and body.get("action") == "revoke"      # agents can stop, never accept
        return False

    def _route(self, method, path, q, body):
        s, a = self.api.s, self.api
        if method == "GET" and not path.startswith("/api/"):
            return self._static(path)
        if (method, path) == ("GET", "/api/day"):
            return self._send(200, a.day(q.get("date")))
        if (method, path) == ("GET", "/api/range"):
            return self._send(200, a.range(q.get("days", 7)))
        if (method, path) == ("POST", "/api/ingest"):
            dev, src = str(body.get("device", "local")), str(body.get("src", "collector"))
            if not isinstance(body.get("samples", []), list) or not isinstance(body.get("power", []), list):
                raise ValueError("samples and power must be lists")
            for fam in {consent.family_of(src)} | ({"host-system"} if body.get("power") else set()):
                if fam and not consent.active(s, dev, fam):   # no accepted notice, no data: enforced here, not only in the agent
                    return self._send(403, dict(error="consent_required", family=fam, notice_version=consent.VERSION,
                                                hint=f"A person must accept the '{fam}' notice for device '{dev}' first."))
            if body.get("device_name") or body.get("os"):
                s.touch_device(dev, body.get("device_name"), str(body.get("os", "")))
            samples = body.get("samples", [])
            distilled = s.setting("save_raw_on_host", "1") == "0"
            if distilled:   # distillation on the host: keep app + timing, drop window titles, domains and control names before anything is saved
                samples = [dict(x, title="", domain="", ctl="") if isinstance(x, dict) else x for x in samples]
            new = s.ingest(samples, src=src, device=dev, keep_input=consent.active(s, dev, "input-activity"))
            dropped_inp = s.last_input_dropped
            new_p = s.ingest_power(body.get("power", []), device=dev) if body.get("power") else 0
            if isinstance(body.get("apps"), list):
                s.upsert_apps(dev, body["apps"])
            if body.get("cursor") is not None:   # the agent saves its progress with the batch it just sent
                s.set_cursor(dev, src, body["cursor"], new)
            return self._send(200, dict(stored=new, received=len(body.get("samples", [])), power=new_p, input_dropped=dropped_inp, distilled=distilled))
        if (method, path) == ("GET", "/api/apps"):
            return self._send(200, dict(apps=s.q("SELECT device, app, display, publisher, version, ts FROM app_meta WHERE device=? ORDER BY app", (q.get("device", "local"),))))
        if (method, path) == ("GET", "/api/attention"):
            return self._send(200, a.attention(q.get("date")))
        if (method, path) == ("GET", "/api/consent/notice"):
            fam = q.get("family", "")
            if fam not in consent.NOTICES:
                raise ValueError("unknown family")
            return self._send(200, dict(family=fam, version=consent.VERSION, phrase=consent.phrase(fam), **consent.NOTICES[fam]))
        if (method, path) == ("GET", "/api/consent"):
            dev = q.get("device", "local")
            return self._send(200, dict(device=dev, version=consent.VERSION, families=consent.status(s, dev), chain_ok=consent.verify_chain(s)))
        if (method, path) == ("POST", "/api/consent"):
            return self._send(200, consent.record(s, str(body.get("device", "local")), str(body.get("family", "")), str(body.get("action", "")),
                                                  body.get("granted_by", ""), str(body.get("typed", ""))))
        if (method, path) == ("POST", "/api/consent/bulk"):
            return self._send(200, dict(granted=consent.grant_many(s, str(body.get("device", "local")), body.get("families"), body.get("granted_by", ""), str(body.get("typed", ""))),
                                        bulk_phrase=consent.BULK_PHRASE))
        if (method, path) == ("POST", "/api/purge"):
            return self._send(200, consent.purge(s, str(body.get("device", "local")), str(body.get("family", "")), str(body.get("confirm", ""))))
        if (method, path) == ("POST", "/api/agent/enroll"):
            code, exp = enroll.new_code(s)
            return self._send(200, dict(code=code, expires=exp, ttl_s=enroll.CODE_TTL_S, server=f"http://{self.headers.get('Host')}"))
        if (method, path) == ("POST", "/api/agent/register"):
            try:
                key = enroll.register(s, body.get("code", ""), body.get("device", ""), body.get("name", ""))
            except PermissionError as e:
                return self._send(403, dict(error="invalid_code", message=str(e)))
            return self._send(200, dict(device_key=key, device=str(body["device"]).strip()[:60],
                                        note="shown once; stored on the server only as a hash"))
        if (method, path) == ("POST", "/api/agent/environment"):
            dev = str(body.get("device", "local"))
            s.touch_device(dev)
            s.x("INSERT OR REPLACE INTO device_env(device,plan,ts) VALUES(?,?,?)", (dev, json.dumps(enroll.clean_plan(body.get("plan"))), time.time()))
            return self._send(200, dict(ok=True))
        if (method, path) == ("GET", "/api/agent/environment"):
            dev = q.get("device", "local")
            r = s.q("SELECT plan, ts FROM device_env WHERE device=?", (dev,))
            return self._send(200, dict(device=dev, plan=json.loads(r[0]["plan"]) if r else None, ts=r[0]["ts"] if r else None))
        if (method, path) == ("GET", "/api/agent/devices"):
            return self._send(200, dict(devices=enroll.devices(s)))
        if (method, path) == ("POST", "/api/agent/revoke"):
            enroll.revoke(s, str(body["device"]))
            return self._send(200, dict(ok=True))
        if (method, path) == ("POST", "/api/agent/bundle"):
            osn = str(body.get("os", ""))
            if osn not in bundle.TARGETS:
                raise ValueError("os must be one of: " + ", ".join(sorted(bundle.TARGETS)))
            code, _ = enroll.new_code(s)
            data, name = bundle.build(osn, f"http://{self.headers.get('Host')}", code)
            return self._send(200, raw=data, ctype="application/zip", filename=name)
        if (method, path) == ("POST", "/api/turns"):
            s.x("CREATE TABLE IF NOT EXISTS turns(id INTEGER PRIMARY KEY, you TEXT, reply TEXT, tools TEXT, ts REAL)")
            you, reply = str(body.get("you", ""))[:2000], str(body.get("reply", ""))[:4000]
            if not (you.strip() or reply.strip()):
                raise ValueError("a turn needs you and/or reply text")
            tid = s.ux("INSERT INTO turns(you,reply,tools,ts) VALUES(?,?,?,?)", (you, reply, json.dumps(body.get("tools") or [])[:500], time.time()))
            return self._send(200, dict(id=tid))
        if (method, path) == ("GET", "/api/coherence"):
            return self._send(200, coherence.audit(s, a))
        if (method, path) == ("POST", "/api/coherence/run"):
            return self._send(200, coherence.run(s, a))
        if (method, path) == ("GET", "/api/embeddings/stats"):
            folding.bind(s)
            rows = s.q("SELECT kind, COUNT(*) AS n FROM embeddings GROUP BY kind")
            return self._send(200, dict(total=sum(r["n"] for r in rows), by_kind={r["kind"]: r["n"] for r in rows}, honeycomb=honeycomb.stats(s)))
        if (method, path) == ("GET", "/api/topics"):
            items = topics.collect(s, a)
            return self._send(200, dict(buckets=folding.fold(items), counts=dict(items=len(items))))
        if (method, path) == ("GET", "/api/recall"):
            items = topics.collect(s, a)
            return self._send(200, dict(query=q.get("q", ""), results=topics.recall(items, q.get("q", ""))))
        if (method, path) == ("GET", "/api/calendar/providers"):
            return self._send(200, dict(providers=calendars.providers()))
        if (method, path) == ("GET", "/api/calendar/export.ics"):
            tasks = [dict(r) for r in s.q("SELECT id, title, est_min, planned_start FROM tasks WHERE planned_start IS NOT NULL")]
            lo = time.time() - 30 * 86400; hi = time.time() + 30 * 86400
            sessions = [dict(r) for r in s.q("SELECT m.id, m.label, m.start, m.end, t.title AS task_title FROM timers m LEFT JOIN tasks t ON t.id=m.task_id WHERE m.start>=? AND m.start<=?", (lo, hi))]
            return self._send(200, raw=calendars.export_ics(tasks, sessions).encode(), ctype="text/calendar", filename="stretto.ics")
        if (method, path) == ("POST", "/api/calendar/import"):
            events_in = calendars.parse_ics(body.get("ics", ""))
            created = skipped = 0
            for ev in events_in:
                if ev["uid"].startswith("stretto-"):
                    skipped += 1; continue
                if s.q("SELECT id FROM tasks WHERE title=? AND planned_start=?", (ev["title"], ev["start_ts"])):
                    skipped += 1; continue
                s.ux("INSERT INTO tasks(title,planned_start,created) VALUES(?,?,?)", (ev["title"], ev["start_ts"], time.time())); created += 1
            return self._send(200, dict(created=created, skipped=skipped, seen=len(events_in)))
        if (method, path) == ("GET", "/api/challenges"):
            n = max(1, min(int(q.get("days", 7)), 30))
            rng = a.range(n)
            days = [a.day(x["date"]) for x in rng["days"] if x["total_s"] > 0]
            done = challenges.check_completion(s, days)
            out = challenges.group(days)
            out["pins"] = challenges.pins(s)
            out["just_completed"] = done
            out["bonus_xp"] = challenges.bonus_xp(s)
            return self._send(200, out)
        if (method, path) == ("POST", "/api/challenges/pin"):
            return self._send(200, challenges.pin(s, body.get("kind", ""), body.get("places"), body.get("fix", ""),
                                                  int(body.get("xp_reward", 10)), dt.date.today().isoformat()))
        if (method, path) == ("POST", "/api/challenges/unpin"):
            return self._send(200, challenges.unpin(s, body.get("id")))
        if (method, path) == ("GET", "/api/coach/plan"):
            rng = a.range(30)
            act = [x for x in rng["days"] if x["total_s"] > 0] or rng["days"]
            avg_loss = round(sum(x["loss_s"] for x in act) / max(1, len(act)) / 60)
            avg_focus = round(sum(x["focus_s"] for x in act) / max(1, len(act)) / 60)
            plan = coach.plan(a.patterns(90), avg_loss, avg_focus,
                              weeks_met=int(float(s.setting("coach_met", 0))), weeks_missed=int(float(s.setting("coach_missed", 0))),
                              horizon_weeks=max(1, min(int(float(s.setting("horizon_weeks", 4))), 12)))
            xp = a.day()["xp"]
            return self._send(200, dict(plan=plan, xp=xp, metric=s.setting("value_metric", "time")))
        if (method, path) == ("GET", "/api/graph"):
            return self._send(200, graphmap.build(a.day(q.get("date"))))
        if (method, path) == ("GET", "/api/honeycomb/stats"):
            return self._send(200, honeycomb.stats(s))
        if (method, path) == ("GET", "/api/voice/tree"):
            day = a.day(q.get("date"))
            f = insights.facts(day)
            art, info = honeycomb.route(s, f)   # fast grounded fast-path: a cached, signature-matched reply if one exists
            return self._send(200, dict(tree=voicetree.derive(day), graph=graphmap.build(day),
                                        preload=dict(honeycomb=info, grounded_cached=art, model=meta.current_model(s))))
        if (method, path) == ("GET", "/api/meta/status"):
            return self._send(200, meta.status(s, a.budget_usd()))
        if (method, path) == ("GET", "/api/meta/calls"):
            n = max(1, min(int(q.get("limit", 20)), 200))
            return self._send(200, dict(calls=s.q("SELECT id,ts,purpose,model,served,mode,prompt_tokens,completion_tokens,reasoning_tokens,cost_usd,seconds,status,req_sha,hash,reply_text "
                                                  "FROM model_calls ORDER BY id DESC LIMIT ?", (n,)), chain_ok=meta.verify_chain(s)))
        if (method, path) == ("GET", "/api/insights"):
            dev, date = q.get("device", "local"), q.get("date")
            day = a.day(date)
            f = insights.facts(day)
            sha = hashlib.sha256(json.dumps(f, sort_keys=True).encode()).hexdigest()[:20]
            hit = s.q("SELECT result FROM insight_cache WHERE date=? AND device=? AND facts_sha=?", (day["date"], dev, sha))
            if hit:
                return self._send(200, dict(json.loads(hit[0]["result"]), cached=True, available=True))
            why = ("consent" if not consent.active(s, dev, "meta-insights") else "no_model_access" if not meta.mode() else "not_generated_yet")
            return self._send(200, dict(available=False, reason=why, date=day["date"]))
        if (method, path) == ("POST", "/api/insights"):
            dev = str(body.get("device", "local"))
            if not consent.active(s, dev, "meta-insights"):     # nothing goes to Meta until a person has accepted the notice
                return self._send(403, dict(error="consent_required", family="meta-insights", notice_version=consent.VERSION,
                                            hint="A person must accept the 'meta-insights' notice first."))
            try:
                return self._send(200, insights.generate(s, a.day(body.get("date")), dev, a.budget_usd(), bool(body.get("refresh"))))
            except meta.BudgetExceeded as e:
                return self._send(429, dict(error="budget_exceeded", message=str(e)))
            except meta.ModelUnavailable as e:
                return self._send(503, dict(error="model_unavailable", message=str(e)))
        if (method, path) == ("GET", "/api/cursor"):
            return self._send(200, dict(cursor=s.cursor(q.get("device", "local"), q.get("src", "collector"))))
        if (method, path) == ("GET", "/api/sources"):
            return self._send(200, dict(sources=a.sources(), devices=s.q("SELECT * FROM devices ORDER BY first_seen")))
        if (method, path) == ("GET", "/api/patterns"):
            return self._send(200, a.patterns(q.get("days", 90)))
        if (method, path) == ("POST", "/api/demo/seed"):
            day, t0, t1 = day_bounds((dt.date.today() - dt.timedelta(days=1)).isoformat())
            if s.q("SELECT 1 FROM events WHERE ts>=? AND ts<? AND src='simulated' LIMIT 1", (t0, t1)):
                return self._send(200, dict(stored=0, simulated=True, date=day))   # seeding twice must not duplicate the day
            stored = s.ingest(demo.samples(t0), src="simulated")
            s.checkpoint(force=True)                       # a seeded demo day must survive a power cut
            return self._send(200, dict(stored=stored, simulated=True, date=day))
        if (method, path) == ("GET", "/api/settings"):
            return self._send(200, a.settings())
        if (method, path) == ("POST", "/api/settings"):
            if not any(k in body for k in ("goal_min", "goal_week_min", "budgets", "model", "save_raw_on_host", "value_metric", "horizon_weeks", "coach_met", "coach_missed")):
                raise ValueError("send goal_min, goal_week_min, budgets, model, save_raw_on_host, value_metric, horizon_weeks, coach_met and/or coach_missed")
            new = {}                                                    # validate EVERYTHING first: a bad field changes nothing
            if "goal_min" in body:
                new["goal_min"] = _whole(body["goal_min"], "goal_min", 10, 960)
            if "goal_week_min" in body:
                new["goal_week_min"] = _whole(body["goal_week_min"], "goal_week_min", 60, 4800)
            if "budgets" in body:
                b = body["budgets"]
                if not isinstance(b, dict):
                    raise ValueError("budgets must be an object {category: minutes}")
                allowed = a.budget_categories()
                clean = {}
                for cat, mins in b.items():
                    if cat not in allowed:
                        raise ValueError(f"unknown category '{str(cat)[:30]}'; budgets may name: {', '.join(sorted(allowed))}")
                    clean[cat] = _whole(mins, f"budget for {cat}", 0, 960)
                new["budgets"] = json.dumps(clean, sort_keys=True)     # the object REPLACES the previous one; leave a category out to remove its budget
            if "model" in body:
                m = str(body["model"]).strip()[:60]
                if m and not m.startswith(meta.META_PREFIXES):
                    raise ValueError("model must be a Meta model (muse-, sam- or llama-...)")
                new["model"] = m
            if "save_raw_on_host" in body:
                if not isinstance(body["save_raw_on_host"], bool):
                    raise ValueError("save_raw_on_host must be true or false")
                new["save_raw_on_host"] = "1" if body["save_raw_on_host"] else "0"
            if "value_metric" in body:
                if body["value_metric"] != "time":
                    raise ValueError("value_metric is 'time' in this build: minutes reclaimed is the measure")
                new["value_metric"] = "time"
            if "horizon_weeks" in body:
                new["horizon_weeks"] = _whole(body["horizon_weeks"], "horizon_weeks", 1, 12)
            if "coach_met" in body:
                new["coach_met"] = _whole(body["coach_met"], "coach_met", 0, 52)
            if "coach_missed" in body:
                new["coach_missed"] = _whole(body["coach_missed"], "coach_missed", 0, 52)
            for k, v in new.items():
                s.set_setting(k, v)
            return self._send(200, a.settings())
        if (method, path) == ("GET", "/api/sessions"):
            f, t = _iso(q.get("from"), "from"), _iso(q.get("to"), "to")
            if t < f:
                raise ValueError("to must not be before from")
            if (t - f).days > 61:
                raise ValueError("at most 62 days")
            lo, hi = daycache.day_range(f.isoformat())[0], daycache.day_range(t.isoformat())[1]
            rows = s.q("SELECT m.id, m.task_id, m.label, m.kind, m.start, m.end, t.title AS task_title FROM timers m LEFT JOIN tasks t ON t.id = m.task_id "
                       "WHERE m.start < ? AND (m.end IS NULL OR m.end > ?) ORDER BY m.start, m.id", (hi, lo))      # overlapping the range, so a session across midnight shows on both days
            return self._send(200, dict(sessions=rows))
        if (method, path) == ("GET", "/api/goals"):
            r = a.range(q.get("days", 7))
            cats = {}
            for d in r["days"]:
                for c, v in d["by_category"].items():
                    cats[c] = cats.get(c, 0) + v
            return self._send(200, dict(days=r["days"], goal_s=r["goal_s"], budgets=a.budgets(),
                                        week=dict(focus_s=sum(d["focus_s"] for d in r["days"]), total_s=sum(d["total_s"] for d in r["days"]),
                                                  goal_week_s=a.goal_week_min() * 60, by_category=cats)))
        if (method, path) == ("GET", "/api/projects"):
            return self._send(200, s.q("SELECT * FROM projects ORDER BY id"))
        if (method, path) == ("POST", "/api/projects"):
            name = str(body["name"]).strip()[:80]
            if not name:
                raise ValueError("name required")
            return self._send(200, dict(id=s.ux("INSERT INTO projects(name,color,created) VALUES(?,?,?)", (name, str(body.get("color", "#6d5efc"))[:9], time.time()))))
        if (method, path) == ("GET", "/api/tasks"):
            return self._send(200, s.q("SELECT t.*, (SELECT COALESCE(SUM(COALESCE(end,?)-start),0) FROM timers WHERE task_id=t.id) AS tracked_s FROM tasks t ORDER BY t.id", (time.time(),)))
        if (method, path) == ("POST", "/api/tasks"):
            title = str(body["title"]).strip()[:200]
            if not title:
                raise ValueError("title required")
            due = _iso(body["due"], "due").isoformat() if body.get("due") is not None else None
            planned = _unix(body["planned_start"], "planned_start") if body.get("planned_start") is not None else None
            return self._send(200, dict(id=s.ux("INSERT INTO tasks(project_id,title,est_min,due,planned_start,created) VALUES(?,?,?,?,?,?)",
                                               (body.get("project_id"), title, body.get("est_min"), due, planned, time.time()))))
        if method == "POST" and path.startswith("/api/tasks/"):
            tid = int(path.rsplit("/", 1)[1])
            sets, args = [], []
            st = body.get("status")
            if st is not None:
                if st not in ("todo", "next", "doing", "done"):
                    raise ValueError("bad status")
                sets += ["status=?", "done_at=?"]
                args += [st, time.time() if st == "done" else None]
            if "due" in body:                                           # present and null clears it; absent leaves it alone
                sets.append("due=?")
                args.append(None if body["due"] is None else _iso(body["due"], "due").isoformat())
            if "planned_start" in body:
                sets.append("planned_start=?")
                args.append(None if body["planned_start"] is None else _unix(body["planned_start"], "planned_start"))
            if sets:
                if not s.q("SELECT 1 FROM tasks WHERE id=?", (tid,)):
                    return self._send(404, dict(error="no such task"))
                s.ux(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", tuple(args) + (tid,))        # one statement: all fields or none
            return self._send(200, dict(ok=True))
        if (method, path) == ("GET", "/api/timer"):
            return self._send(200, a.timer())
        if (method, path) == ("POST", "/api/timer/start"):
            if body.get("kind", "focus") not in ("focus", "break"):
                raise ValueError("kind must be focus or break")
            s.x("UPDATE timers SET end=? WHERE end IS NULL", (time.time(),))
            tid = s.ux("INSERT INTO timers(task_id,label,kind,start) VALUES(?,?,?,?)",
                      (body.get("task_id"), str(body.get("label", ""))[:120], body.get("kind", "focus"), time.time()))
            a.bus.publish("timer", a.timer())
            return self._send(200, dict(id=tid))
        if (method, path) == ("POST", "/api/timer/stop"):
            s.ux("UPDATE timers SET end=? WHERE end IS NULL", (time.time(),))
            a.bus.publish("timer", a.timer())
            return self._send(200, dict(ok=True))
        if (method, path) == ("GET", "/api/habits"):
            today = dt.date.today().isoformat()
            return self._send(200, [dict(h, done_today=bool(s.q("SELECT 1 FROM habit_log WHERE habit_id=? AND day=?", (h["id"], today))),
                                         days=[r["day"] for r in s.q("SELECT day FROM habit_log WHERE habit_id=? ORDER BY day DESC LIMIT 60", (h["id"],))])
                                    for h in s.q("SELECT * FROM habits ORDER BY id")])
        if (method, path) == ("POST", "/api/habits"):
            return self._send(200, dict(id=s.ux("INSERT INTO habits(name,why,created) VALUES(?,?,?)", (str(body["name"]).strip()[:80], str(body.get("why", ""))[:200], time.time()))))
        if method == "POST" and path.startswith("/api/habits/") and path.endswith("/log"):
            hid = int(path.split("/")[3])
            day = dt.date.fromisoformat(body.get("day") or dt.date.today().isoformat()).isoformat()
            if s.q("SELECT 1 FROM habit_log WHERE habit_id=? AND day=?", (hid, day)):
                s.ux("DELETE FROM habit_log WHERE habit_id=? AND day=?", (hid, day))
            else:
                s.ux("INSERT INTO habit_log(habit_id,day) VALUES(?,?)", (hid, day))
            return self._send(200, dict(ok=True))
        if (method, path) == ("GET", "/api/rules"):
            return self._send(200, s.q("SELECT * FROM rules ORDER BY id"))
        if (method, path) == ("POST", "/api/rules"):
            import re
            re.compile(body["pattern"])
            if body["field"] not in ("app", "domain", "title"):
                raise ValueError("bad field")
            return self._send(200, dict(id=s.ux("INSERT INTO rules(field,pattern,category) VALUES(?,?,?)", (body["field"], body["pattern"][:200], str(body["category"])[:30]))))
        return self._send(404, dict(error="not found"))

    def _static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.realpath(os.path.join(STATIC, rel))
        if not full.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(full):
            return self._send(404, dict(error="not found"))
        if rel == "index.html":   # the shell carries the per-install token: never cached
            with open(full, "rb") as fh:
                data = fh.read()
            return self._send(200, raw=data.replace(b"__TOKEN__", b"" if self.remote else self.token.encode()),
                              ctype="text/html")
        st = os.stat(full)   # assets are immutable per build: ETag + an hour of cache turns reloads into 304s
        etag = f'"{st.st_mtime_ns}-{st.st_size}"'
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            return
        with open(full, "rb") as fh:
            data = fh.read()
        body = data
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(full)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "public, max-age=3600")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:")
        self.end_headers()
        self.wfile.write(body)


def make_server(store, port=8760, token=None, host="127.0.0.1", allow_hosts=()):
    """Loopback by default. Any other bind address needs allow_hosts (the exact Host header values you will use, e.g.
    'mac.tailnet.ts.net:8760') and turns on remote mode: the token is required on every API call."""
    remote = host not in LOOPBACK_HOSTS
    if remote and not allow_hosts:
        raise ValueError("listening beyond loopback needs at least one allowed Host value")
    tok = token or secrets.token_urlsafe(24)
    srv = ThreadingHTTPServer((host, port), type("H", (Handler,), {}))
    h, p = srv.RequestHandlerClass, srv.server_address[1]
    h.api, h.token, h.port, h.remote = Api(store), tok, p, remote
    h.allowed = tuple({f"127.0.0.1:{p}", f"localhost:{p}", *allow_hosts})
    return srv, tok