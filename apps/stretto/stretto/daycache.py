# SPDX-License-Identifier: Apache-2.0
"""Per-day summary cache. A day is summarised once; later reads reuse it until that day's data (or the classification rules) change.

A cached summary is valid only while its FINGERPRINT matches: (cache version, rules signature, number of events that day, newest event id,
total duration). Ingesting, purging, or changing a rule changes the fingerprint, so a stale summary can never be served as current, and no
explicit invalidation is needed. The fingerprint is read BEFORE the events, so if data arrives in between, the stored summary is newer than its
fingerprint and is simply recomputed next time: the failure mode is extra work, never wrong numbers.

Cold start (many days to compute) fans out across worker processes, each reading the database read-only. Warm reads touch no events at all."""
import datetime as dt
import hashlib
import json
import os
import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor

from . import analyze, attention, merge, segment
from .segment import FOCUS

VERSION = 4                       # 4: summaries carry findings_lite for challenge grouping; 3: merged devices; 2: attention_score
PARALLEL_MIN = 12                 # fewer stale days than this: process start-up costs more than it saves (measured, see tools/bench.py)
MAX_WORKERS = 8


def rules_sig(rules):
    return hashlib.sha1((json.dumps([list(r) for r in rules]) + segment.DEFAULT_SIG).encode()).hexdigest()[:12]


def day_range(iso):
    d = dt.date.fromisoformat(iso)
    a = dt.datetime.combine(d, dt.time()).timestamp()
    return a, (dt.datetime.combine(d, dt.time()) + dt.timedelta(days=1)).timestamp()


def summarize(blocks, loss=None):
    """Everything the history views need from one day. Core numbers come from analyze.summary, so they match the uncached path exactly.
    loss: pass the day's already-computed loss_s to avoid analysing the day twice."""
    sm = analyze.summary(blocks)
    hf, hd, ht = [0.0] * 24, [0.0] * 24, [0.0] * 24
    longest = focus_exact = 0.0
    for b in blocks:
        if b["category"] == "Idle":
            continue
        h = dt.datetime.fromtimestamp(b["start"]).hour
        ht[h] += b["seconds"]
        if b["category"] in FOCUS:
            hf[h] += b["seconds"]
            focus_exact += b["seconds"]
            longest = max(longest, b["seconds"])
        elif b["category"] == "Distraction":
            hd[h] += b["seconds"]
    att = attention.measure(blocks)
    if loss is None:
        found, loss = analyze.findings(blocks)
        lite = [dict(kind=f["kind"], where=f["where"], seconds=f["seconds"]) for f in found]
    else:
        lite = []
    return dict(attention_score=att["score"] if att.get("enough") else None,
                total_s=sm["total_s"], idle_s=sm["idle_s"], focus_s=sm["focus_s"], focus_f=round(focus_exact, 3), distraction_s=sm["distraction_s"],
                by_category=sm["by_category"], loss_s=loss, longest_focus_s=round(longest), findings_lite=lite,
                hours_focus=[round(x) for x in hf], hours_distraction=[round(x) for x in hd], hours_total=[round(x) for x in ht])


def compute(events, rules):
    kept, _ = merge.timeline(events)
    return summarize(segment.blocks(kept, rules))


def fingerprints(store, t0, t1, sig):
    """One cheap aggregate per calendar day. Each is an index-only range scan over events(ts, dur): COUNT, MAX(id) (the rowid lives in every
    index entry) and SUM(dur) need no table lookups and no per-row date arithmetic. Grouping with date(ts,'localtime') instead took ~1.2 s per 345k rows."""
    out = {}
    day = dt.date.fromtimestamp(t0 + 1)
    last = dt.date.fromtimestamp(t1 - 1)
    with store.lock:
        while day <= last:
            a, b = day_range(day.isoformat())
            n, m, s = store.db.execute("SELECT COUNT(*), MAX(id), ROUND(SUM(dur),1) FROM events WHERE ts>=? AND ts<?", (a, b)).fetchone()
            if n:
                out[day.isoformat()] = f"{VERSION}|{sig}|{n}|{m}|{s}"
            day += dt.timedelta(days=1)
    return out


def _work(job):
    """Runs in a worker process: read one day read-only, summarise it."""
    path, day, rules = job
    a, b = day_range(day)
    cols = ("id", "ts", "dur", "app", "title", "domain", "idle", "cx", "cy", "src", "device", "ctl", "inp")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = con.execute(f"SELECT {','.join(cols)} FROM events WHERE ts>=? AND ts<? ORDER BY ts", (a, b)).fetchall()
    finally:
        con.close()
    return day, compute([dict(zip(cols, r)) for r in rows], rules)


def _put(store, day, fp, summary):
    store.x("INSERT OR REPLACE INTO day_cache(day,fp,summary,ts) VALUES(?,?,?,?)", (day, fp, json.dumps(summary), time.time()))


def ensure(store, rules, t0, t1, supplied=None, stats=None):
    """Summaries for every day with events in [t0, t1): {iso_day: summary}.
    supplied: {iso_day: summary} the caller already computed (e.g. the day being viewed). Used in the result, NEVER stored: the caller read its
    events before this call took the fingerprint, so data arriving in between could otherwise leave an old summary filed under a newer fingerprint.
    stats: optional dict filled with hits / computed / parallel for tests and benchmarks."""
    stats = stats if stats is not None else {}
    sig = rules_sig(rules)
    fps = fingerprints(store, t0, t1, sig)
    lo, hi = min(fps, default=None), max(fps, default=None)
    cached = {r["day"]: r for r in store.q("SELECT day, fp, summary FROM day_cache WHERE day>=? AND day<=?", (dt.date.fromtimestamp(t0 + 1).isoformat(), dt.date.fromtimestamp(t1 - 1).isoformat()))}
    out, stale = {}, []
    for d, fp in fps.items():
        if supplied and d in supplied:
            out[d] = supplied[d]
        elif d in cached and cached[d]["fp"] == fp:
            out[d] = json.loads(cached[d]["summary"])
        else:
            stale.append(d)
    for d in set(cached) - set(fps):                         # a day that lost all its events (purge) must not linger in the cache
        store.x("DELETE FROM day_cache WHERE day=?", (d,))
    stats.update(hits=len(out), computed=len(stale), parallel=False, days=len(fps))
    if stale:
        done = None
        if len(stale) >= PARALLEL_MIN and getattr(store, "path", ":memory:") != ":memory:" and (os.cpu_count() or 1) > 1:
            try:
                with ProcessPoolExecutor(max_workers=min(os.cpu_count() or 1, MAX_WORKERS)) as ex:
                    done = dict(ex.map(_work, [(store.path, d, rules) for d in stale], chunksize=max(1, len(stale) // (MAX_WORKERS * 2))))
                stats["parallel"] = True
            except Exception:                                # a pool that cannot start must never break a read: fall back to one process
                done = None
        if done is None:
            done = {d: compute(store.events(*day_range(d)), rules) for d in stale}
        for d, s in done.items():
            out[d] = s
            _put(store, d, fps[d], s)
    return out
