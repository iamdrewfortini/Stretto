# SPDX-License-Identifier: Apache-2.0
"""Resolve overlapping sources. Pure functions.

The same minute can be described by several sources: the live collector, the OS's own usage log, and browser history.
Counting all of them would double the time. The rule is simple and stated in the UI: the highest-priority source wins
a moment; a lower one only fills time the higher ones did not cover."""
import bisect

from .store import priority


def _union(intervals):
    out = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _covered(merged, starts, a, b):
    """True when [a, b) overlaps any merged interval by more than a second."""
    i = bisect.bisect_right(starts, b) - 1
    while i >= 0 and merged[i][1] > a:
        if min(b, merged[i][1]) - max(a, merged[i][0]) > 1.0:
            return True
        i -= 1
    return False


def timeline(events, gap=90.0):
    """One timeline from many devices, counted ONCE. A person uses one computer at a time, so at every moment exactly one active device wins:
      1. each device resolves its own sources first (live capture beats OS logs beats inferred history), as resolve() does;
      2. among devices with a non-idle sample at that moment, live data beats estimated history, then the stay that STARTED most recently wins
         (a focus change is an action, so the newest one is where the person is), then the device id breaks any tie so results are deterministic;
      3. idle samples never mask an active one; if every device is idle the moment is idle, once.
    Events are clipped to the part of their time they win (input ticks scaled in proportion). One device: identical to resolve().
    Returns (events sorted by time, dropped-per-source from the per-device resolve)."""
    by_dev = {}
    for e in events:
        by_dev.setdefault(e.get("device") or "local", []).append(e)
    if len(by_dev) <= 1:
        return resolve(events)
    dropped, items = {}, []
    for dev, es in by_dev.items():
        kept, dr = resolve(es)
        for k, v in dr.items():
            dropped[k] = dropped.get(k, 0) + v
        prev_key, prev_end, start = None, None, None
        for e in kept:
            key = (e["app"], e.get("title"), e.get("ctl"), e.get("domain"), bool(e.get("idle")))
            a, b = e["ts"], e["ts"] + min(float(e.get("dur") or 5), 3600)
            if key != prev_key or prev_end is None or a - prev_end > gap:
                start = a                                               # a new stay: focus moved here at time a
            prev_key, prev_end = key, b if prev_end is None else max(prev_end, b)
            items.append((a, b, priority(e["src"]), start, dev, e, bool(e.get("idle"))))
    items.sort(key=lambda it: (it[0], it[4]))
    bounds = sorted({x for it in items for x in (it[0], it[1])})
    out, active, ptr, last = [], [], 0, None
    for t0, t1 in zip(bounds, bounds[1:]):
        while ptr < len(items) and items[ptr][0] <= t0:
            active.append(items[ptr])
            ptr += 1
        active = [it for it in active if it[1] > t0]
        pool = [it for it in active if not it[6]] or active              # active devices first; idle only when nobody is active
        if not pool:
            last = None
            continue
        win = max(pool, key=lambda it: (it[2], it[3], it[4]))
        if last is not None and last[0] is win[5] and abs(last[1] - t0) < 1e-9:     # the same event continues: extend the clipped piece
            last[1] = t1
            out[-1]["dur"] = t1 - out[-1]["ts"]
            out[-1]["inp"] = _share(win[5], out[-1]["dur"])
        else:
            out.append(dict(win[5], ts=t0, dur=t1 - t0, inp=_share(win[5], t1 - t0)))
            last = [win[5], t1]
    return out, dropped


def _share(event, dur):
    """The input ticks that belong to `dur` seconds of an event that lasted longer: scaled in proportion. None stays None."""
    inp, whole = event.get("inp"), min(float(event.get("dur") or 5), 3600)
    if inp is None or not whole:
        return inp
    return int(round(inp * min(1.0, dur / whole)))


def overlap(events):
    """Seconds during which two or more DEVICES were active at once, and which devices. Measured from live sources only (priority 2 and up):
    estimated history cannot say what was happening at a moment. Idle samples do not count as active. Returns (seconds, [device ids])."""
    by_dev = {}
    for e in events:
        if not e.get("idle") and priority(e["src"]) >= 2:
            by_dev.setdefault(e.get("device") or "local", []).append(e)
    if len(by_dev) < 2:
        return 0, []
    marks = []
    for dev, es in by_dev.items():
        kept, _ = resolve(es)
        for a, b in _union([(e["ts"], e["ts"] + min(float(e.get("dur") or 5), 3600)) for e in kept]):
            marks.append((a, 1, dev))
            marks.append((b, -1, dev))
    marks.sort(key=lambda m: (m[0], m[1]))               # at the same instant an end sorts before a start, so touching stays are not an overlap
    active, total, last, involved = {}, 0.0, None, set()
    for t, k, dev in marks:
        live = [d for d, v in active.items() if v > 0]
        if last is not None and len(live) >= 2:
            total += t - last
            involved.update(live)
        active[dev] = active.get(dev, 0) + k
        last = t
    return round(total), sorted(involved)


def resolve(events):
    """Returns (kept events sorted by time, per-source counts of events dropped because a better source covered them)."""
    by_p = {}
    for e in events:
        by_p.setdefault(priority(e["src"]), []).append(e)
    if len(by_p) <= 1:                  # one priority level: nothing can mask anything. This is the common case, so skip the interval work.
        return sorted(events, key=lambda e: e["ts"]), {}
    cover = {}
    for p, es in by_p.items():
        m = _union([(e["ts"], e["ts"] + min(float(e.get("dur") or 5), 3600)) for e in es])
        cover[p] = (m, [x[0] for x in m])
    kept, dropped = [], {}
    for p, es in by_p.items():
        higher = [cover[q] for q in cover if q > p]
        for e in es:
            a, b = e["ts"], e["ts"] + min(float(e.get("dur") or 5), 3600)
            if any(_covered(m, st, a, b) for m, st in higher):
                dropped[e["src"]] = dropped.get(e["src"], 0) + 1
            else:
                kept.append(e)
    kept.sort(key=lambda e: e["ts"])
    return kept, dropped
