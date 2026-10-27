# SPDX-License-Identifier: Apache-2.0
"""Telemetry store + read-only Proxmox ingest + maturity gate. SQLite (stdlib). Nothing here writes to the cluster."""
import json, math, sqlite3, statistics, time

STEP = 1.4        # fixed capacity step per dimension (recommended option; a cluster above d=14 signals that a level is missing)
def dim(capacity): return max(0.0, math.log(max(capacity, 1.0)) / math.log(STEP))

class Store:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS obs(ts REAL, level INTEGER, unit TEXT, metric TEXT, value REAL, src TEXT)")
        self.db.execute("CREATE INDEX IF NOT EXISTS ix ON obs(unit, metric, ts)")
    def add(self, rows): self.db.executemany("INSERT INTO obs VALUES (?,?,?,?,?,?)", rows); self.db.commit()
    def series(self, unit, metric):
        return self.db.execute("SELECT ts, value FROM obs WHERE unit=? AND metric=? ORDER BY ts", (unit, metric)).fetchall()
    def rate(self, unit, metric):
        s = self.series(unit, metric); return [(t2, max(0.0, (v2 - v1) / (t2 - t1))) for (t1, v1), (t2, v2) in zip(s, s[1:]) if t2 > t1]   # counters -> per-second rates (resets clipped to 0)
    def units(self):
        return self.db.execute("SELECT unit, MAX(level), COUNT(DISTINCT metric), COUNT(*) FROM obs GROUP BY unit").fetchall()
    def span_seconds(self):
        r = self.db.execute("SELECT MIN(ts), MAX(ts) FROM obs").fetchone(); return 0.0 if r[0] is None else r[1] - r[0]
    def count(self): return self.db.execute("SELECT COUNT(*) FROM obs").fetchone()[0]

def ingest_pve(store, inv, ts=None):
    """inv: parsed JSON of `inventory CLI --output json inventory` (data.resources). Returns number of rows written."""
    ts = time.time() if ts is None else ts; res = inv["data"]["resources"]; rows = []
    nodes = [r for r in res if r.get("type") == "node" and r.get("maxcpu")]
    for r in res:
        t = r.get("type"); u = r["id"]
        if t == "node" and r.get("maxcpu"):
            lv = round(dim(r["maxcpu"]))
            rows += [(ts, lv, u, "cpu_frac", float(r.get("cpu", 0)), "pve"), (ts, lv, u, "mem_frac", r["mem"] / r["maxmem"], "pve"), (ts, lv, u, "disk_frac", r["disk"] / r["maxdisk"], "pve")]
        elif t in ("qemu", "lxc") and r.get("status") == "running" and not r.get("template"):
            lv = round(dim(r["maxcpu"]))
            rows += [(ts, lv, u, "cpu_frac", float(r.get("cpu", 0)), "pve"), (ts, lv, u, "mem_frac", r["mem"] / r["maxmem"], "pve")]
            for c in ("netin", "netout", "diskread", "diskwrite"): rows.append((ts, lv, u, c + "_total", float(r.get(c, 0)), "pve"))
    if nodes:
        T = sum(n["maxcpu"] for n in nodes); M = sum(n["maxmem"] for n in nodes); lv = round(dim(T))
        rows += [(ts, lv, "cluster", "cpu_frac", sum(n["cpu"] * n["maxcpu"] for n in nodes) / T, "pve"), (ts, lv, "cluster", "mem_frac", sum(n["mem"] for n in nodes) / M, "pve"),
                 (ts, lv, "cluster", "free_ram_gib", (M - sum(n["mem"] for n in nodes)) / 2 ** 30, "pve")]
    store.add(rows); return len(rows)

def maturity(store, interval_s, candidate_periods_s=(86400, 7 * 86400), need_cycles=3):
    """Quantified readiness: phase and what is missing. Needs >= need_cycles of a period to test it at all."""
    span = store.span_seconds(); n = store.count(); out = dict(samples=n, span_h=round(span / 3600, 3), interval_s=interval_s)
    need = {int(p): max(0.0, need_cycles * p - span) for p in candidate_periods_s}
    out["hours_until_testable"] = {("daily" if p == 86400 else "weekly"): round(v / 3600, 2) for p, v in need.items()}
    out["samples_per_daily_cycle"] = int(86400 / interval_s)
    out["phase"] = "OBSERVE" if span < need_cycles * 86400 else "LEARN"      # PROPOSE/ROLLOUT are earned per metric by forecast skill (forecast.py), not by elapsed time
    return out
