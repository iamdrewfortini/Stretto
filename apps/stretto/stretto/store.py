"""SQLite store (WAL). One file, local only. Every write goes through here.

Rows from any device or source are idempotent: each carries a uid (hash of device, source, time, app), so an agent that
retries a batch, or re-imports history from an old cursor, can never double-count."""
import hashlib
import os
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts REAL NOT NULL, dur REAL NOT NULL, app TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '', domain TEXT NOT NULL DEFAULT '', idle INTEGER NOT NULL DEFAULT 0,
  cx INTEGER, cy INTEGER, src TEXT NOT NULL DEFAULT 'collector');
CREATE INDEX IF NOT EXISTS ev_ts ON events(ts);
CREATE INDEX IF NOT EXISTS ev_ts_dur ON events(ts, dur);   -- covers the per-day fingerprint (COUNT, MAX(id), SUM(dur)) with no table lookups
CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY, name TEXT NOT NULL, color TEXT NOT NULL DEFAULT '#6d5efc', created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, project_id INTEGER, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'todo',
  est_min INTEGER, due TEXT, planned_start REAL, created REAL NOT NULL, done_at REAL);
CREATE TABLE IF NOT EXISTS timers(id INTEGER PRIMARY KEY, task_id INTEGER, label TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'focus',
  start REAL NOT NULL, end REAL);
CREATE TABLE IF NOT EXISTS habits(id INTEGER PRIMARY KEY, name TEXT NOT NULL, why TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS habit_log(habit_id INTEGER NOT NULL, day TEXT NOT NULL, PRIMARY KEY(habit_id, day));
CREATE TABLE IF NOT EXISTS rules(id INTEGER PRIMARY KEY, field TEXT NOT NULL, pattern TEXT NOT NULL, category TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, name TEXT NOT NULL, os TEXT NOT NULL DEFAULT '', first_seen REAL NOT NULL, last_seen REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sources(device TEXT NOT NULL, src TEXT NOT NULL, cursor TEXT NOT NULL DEFAULT '', rows INTEGER NOT NULL DEFAULT 0,
  last_run REAL, PRIMARY KEY(device, src));
CREATE TABLE IF NOT EXISTS power(id INTEGER PRIMARY KEY, device TEXT NOT NULL, ts REAL NOT NULL, kind TEXT NOT NULL, uid TEXT NOT NULL UNIQUE);
CREATE INDEX IF NOT EXISTS pw_ts ON power(ts);
CREATE TABLE IF NOT EXISTS model_calls(id INTEGER PRIMARY KEY, ts REAL NOT NULL, purpose TEXT, model TEXT, served TEXT, mode TEXT,
  prompt_tokens INTEGER, completion_tokens INTEGER, reasoning_tokens INTEGER, cost_usd REAL, seconds REAL, status TEXT, req_sha TEXT,
  reply_text TEXT, prev TEXT NOT NULL, hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS insight_cache(date TEXT NOT NULL, device TEXT NOT NULL, facts_sha TEXT NOT NULL, result TEXT NOT NULL, ts REAL NOT NULL,
  PRIMARY KEY(date, device, facts_sha));
CREATE TABLE IF NOT EXISTS day_cache(day TEXT PRIMARY KEY, fp TEXT NOT NULL, summary TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS app_meta(device TEXT NOT NULL, app TEXT NOT NULL, display TEXT NOT NULL DEFAULT '', publisher TEXT NOT NULL DEFAULT '',
  version TEXT NOT NULL DEFAULT '', ts REAL NOT NULL, PRIMARY KEY(device, app));
CREATE TABLE IF NOT EXISTS device_env(device TEXT PRIMARY KEY, plan TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS device_keys(device TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', key_hash TEXT NOT NULL, created REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS enroll_codes(code_hash TEXT PRIMARY KEY, created REAL NOT NULL, expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS consent(id INTEGER PRIMARY KEY, device TEXT NOT NULL, family TEXT NOT NULL, version INTEGER NOT NULL,
  action TEXT NOT NULL, granted_by TEXT NOT NULL, ts REAL NOT NULL, prev TEXT NOT NULL, hash TEXT NOT NULL);
"""

LIMITS = dict(app=80, title=300, domain=120, device=60, src=60)
# When two sources cover the same moment, the higher number wins: live capture beats OS usage logs beats inferred history.
PRIORITY = {"collector": 3, "simulated": 3, "activities-cache": 2}
POWER_KINDS = {"boot", "shutdown", "sleep", "resume", "crash", "lock", "unlock"}


def priority(src):
    return PRIORITY.get(src.split(":")[0], 1)


def _uid(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:20]


class Store:
    def __init__(self, path):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self._last_ckpt = 0.0
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            # Durability across POWER LOSS, not just a crashed process. WAL with synchronous=NORMAL can lose transactions that were reported as
            # committed. On macOS plain fsync() does not flush the drive's own cache (only F_FULLFSYNC does), so fullfsync is switched on too.
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA fullfsync=ON")
            self.db.execute("PRAGMA checkpoint_fullfsync=ON")
            self.db.executescript(SCHEMA)
            cols = {r["name"] for r in self.db.execute("PRAGMA table_info(events)")}
            for name, ddl in (("device", "TEXT NOT NULL DEFAULT 'local'"), ("uid", "TEXT"), ("ctl", "TEXT NOT NULL DEFAULT ''"), ("inp", "INTEGER")):   # migrate older databases
                if name not in cols:
                    self.db.execute(f"ALTER TABLE events ADD COLUMN {name} {ddl}")
            self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS ev_uid ON events(uid) WHERE uid IS NOT NULL")

    CHECKPOINT_EVERY_S = 10.0

    def durability(self):
        """The settings that decide whether a committed write survives a power cut. Shown by `doctor` and checked by tests."""
        with self.lock:
            g = lambda p: self.db.execute(f"PRAGMA {p}").fetchone()[0]
            return dict(journal_mode=g("journal_mode"), synchronous={0: "OFF", 1: "NORMAL", 2: "FULL", 3: "EXTRA"}.get(g("synchronous"), "?"),
                        fullfsync=bool(g("fullfsync")), checkpoint_fullfsync=bool(g("checkpoint_fullfsync")))

    def checkpoint(self, force=False):
        """Move the write-ahead log into the main database file and truncate it, so committed data does not sit only in the log.
        Throttled to once per CHECKPOINT_EVERY_S unless forced (consent records, seeds, shutdown)."""
        if self.path == ":memory:":
            return
        now = time.time()
        if not force and now - self._last_ckpt < self.CHECKPOINT_EVERY_S:
            return
        with self.lock:
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")       # returns busy/log/checkpointed instead of raising if a reader holds it
            self._last_ckpt = time.time()

    def close(self):
        """Clean shutdown: checkpoint, then close."""
        try:
            self.checkpoint(force=True)
        finally:
            with self.lock:
                self.db.close()

    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args)]

    def x(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args).lastrowid

    def ux(self, sql, args=()):
        """A write the PERSON made (a task, a habit, a rule, a setting, a key, a purge): committed with synchronous=FULL, then moved into the main
        database file at once. Rare and valuable, so the cost is irrelevant; machine traffic (ingest) uses the throttled checkpoint instead."""
        rid = self.x(sql, args)
        self.checkpoint(force=True)
        return rid

    def setting(self, k, default=None):
        r = self.q("SELECT v FROM settings WHERE k=?", (k,))
        return r[0]["v"] if r else default

    def set_setting(self, k, v):
        self.ux("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))

    # ---- devices, sources, cursors
    def touch_device(self, device, name=None, os_name=""):
        now = time.time()
        self.x("INSERT INTO devices(id,name,os,first_seen,last_seen) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen, "
               "name=COALESCE(NULLIF(excluded.name,''), name), os=COALESCE(NULLIF(excluded.os,''), os)", (device, (name or device)[:LIMITS["device"]], os_name[:40], now, now))

    def cursor(self, device, src):
        r = self.q("SELECT cursor FROM sources WHERE device=? AND src=?", (device, src))
        return r[0]["cursor"] if r else ""

    def set_cursor(self, device, src, cursor, added=0):
        self.x("INSERT INTO sources(device,src,cursor,rows,last_run) VALUES(?,?,?,?,?) ON CONFLICT(device,src) DO UPDATE SET "
               "cursor=excluded.cursor, rows=rows+?, last_run=excluded.last_run", (device, src, str(cursor)[:200], added, time.time(), added))

    # ---- ingest
    def ingest(self, samples, src="collector", device="local", keep_input=False):
        """Validate and insert samples. Duplicates (same uid) are ignored. Returns how many were NEW.
        Input-event counts ('inp') are kept only when keep_input is True, i.e. the person accepted the input-activity notice."""
        device, src = (str(device)[:LIMITS["device"]] or "local"), (str(src)[:LIMITS["src"]] or "collector")
        now, rows = time.time(), []
        self.last_input_dropped = 0
        for s in samples:
            try:
                ts, dur = float(s["ts"]), float(s.get("dur", 5))
                app = str(s["app"])[:LIMITS["app"]].strip()
            except (KeyError, TypeError, ValueError):
                continue
            if not app or not (631_152_000 < ts < now + 3600) or not (0 < dur <= 3600):   # 1990 .. now: history may be years old
                continue
            cx, cy = s.get("cx"), s.get("cy")
            inp = s.get("inp")
            if isinstance(inp, (int, float)) and not isinstance(inp, bool):
                if keep_input:
                    inp = max(0, min(int(inp), 100_000))
                else:
                    inp, self.last_input_dropped = None, self.last_input_dropped + 1      # counts without an accepted notice are discarded here
            else:
                inp = None
            rows.append((ts, dur, app, str(s.get("title", ""))[:LIMITS["title"]], str(s.get("domain", "")).lower()[:LIMITS["domain"]],
                         1 if s.get("idle") else 0, int(cx) if isinstance(cx, (int, float)) else None, int(cy) if isinstance(cy, (int, float)) else None,
                         src, device, _uid(device, src, round(ts, 1), app, s.get("title", "")), str(s.get("ctl", ""))[:60], inp))
        with self.lock:
            before = self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            self.db.execute("BEGIN")
            self.db.executemany("INSERT OR IGNORE INTO events(ts,dur,app,title,domain,idle,cx,cy,src,device,uid,ctl,inp) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            self.db.execute("COMMIT")
            added = self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] - before
        if rows:
            self.touch_device(device)
            self.checkpoint()
        return added

    def ingest_power(self, items, device="local"):
        """items: [{ts, kind}] system on/off/sleep/wake/lock events. Idempotent."""
        device, now, added = (str(device)[:LIMITS["device"]] or "local"), time.time(), 0
        for it in items:
            try:
                ts, kind = float(it["ts"]), str(it["kind"])
            except (KeyError, TypeError, ValueError):
                continue
            if kind not in POWER_KINDS or not (631_152_000 < ts < now + 3600):
                continue
            with self.lock:
                cur = self.db.execute("INSERT OR IGNORE INTO power(device,ts,kind,uid) VALUES(?,?,?,?)", (device, ts, kind, _uid(device, round(ts, 1), kind)))
                added += cur.rowcount
        if items:
            self.touch_device(device)
        return added

    EVENT_COLS = ("id", "ts", "dur", "app", "title", "domain", "idle", "cx", "cy", "src", "device", "ctl", "inp")

    def upsert_apps(self, device, apps):
        """Names and versions of the programs seen on a device. Metadata about software, not about the person."""
        n = 0
        for a in apps[:500]:
            try:
                app = str(a["app"])[:LIMITS["app"]].strip()
            except (KeyError, TypeError):
                continue
            if app:
                self.x("INSERT INTO app_meta(device,app,display,publisher,version,ts) VALUES(?,?,?,?,?,?) ON CONFLICT(device,app) DO UPDATE SET "
                       "display=excluded.display, publisher=excluded.publisher, version=excluded.version, ts=excluded.ts",
                       (device, app, str(a.get("display", ""))[:120], str(a.get("publisher", ""))[:120], str(a.get("version", ""))[:40], time.time()))
                n += 1
        return n

    def events(self, t0, t1):
        """Events in [t0, t1) as dicts. Rows come back as plain tuples: much cheaper than sqlite3.Row for hundreds of thousands of rows."""
        with self.lock:
            cur = self.db.cursor()
            cur.row_factory = None
            rows = cur.execute(f"SELECT {','.join(self.EVENT_COLS)} FROM events WHERE ts>=? AND ts<? ORDER BY ts", (t0, t1)).fetchall()
        cols = self.EVENT_COLS
        return [dict(zip(cols, r)) for r in rows]
