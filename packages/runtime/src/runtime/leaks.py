# SPDX-License-Identifier: Apache-2.0
"""Real-time leak signals and what they compound to.

A "leak" is tracked time lost to waiting, re-finding (search), context
switching, or admin overhead. ``compute`` turns a ``Tools.t_get_summary``
summary plus the raw ledger events into per-day leak rates, compounded
week/month/year/decade cost, a 0..100 leak score (LOWER IS BETTER: less
leak -> lower score), and the ``assumptions`` dict naming every constant.
``daily_history`` groups events by local date; ``progress`` turns that
history into time won back, XP, and levels.
"""

from datetime import datetime, timezone

DEFAULTS = {
    "switch_cost_min": 5.0,
    "hourly_rate_usd": 100.0,
    "workdays_per_week": 5,
    "weeks_per_month": 4.33,
    "workdays_per_year": 240,
    "years_per_decade": 10,
}

_LEVEL_NAMES = {
    0: "Leaking",
    1: "Noticing",
    2: "Plugging",
    3: "Flowing",
    4: "Compounding",
}


def _level_threshold(n):
    """XP needed to reach level n: 30*n*(n+1)/2 (0, 30, 90, 180, 300, 450, ...)."""
    return 30 * n * (n + 1) // 2


def _level_name(n):
    if n >= 5:
        return "Coherent"
    return _LEVEL_NAMES[n]


def _median(values):
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def _assumptions(params=None):
    cfg = dict(DEFAULTS)
    if params:
        cfg.update(params)
    return cfg


def _day_key(t, tz_offset_s=0):
    return datetime.fromtimestamp(t + tz_offset_s, tz=timezone.utc).date().isoformat()


def _event_leak_min(ev, switch_cost_min=None):
    """Leak minutes for one event (excludes switching, which needs pairs)."""
    dur_min = float(ev.get("duration_s", 0.0) or 0.0) / 60.0
    act = ev.get("activity")
    if act == "wait":
        return dur_min
    if act == "search":
        if ev.get("failed_search"):
            return dur_min
        return 0.5 * dur_min
    if act == "admin":
        return dur_min
    return 0.0


def _day_switches(day_events, switch_cost_min):
    eps = []
    for e in day_events:
        act = e.get("activity")
        if eps and eps[-1] == act:
            continue
        eps.append(act)
    return max(0, len(eps) - 1) * switch_cost_min


def compute(summary, events, now, params=None):
    """Leak rates, compounded cost, score, and assumptions from a summary.

    ``summary`` is a ``Tools.t_get_summary`` dict; ``events`` is the raw
    ``tools.events`` list (used for the day count); ``now`` is accepted for
    forward compatibility and currently unused.
    """
    cfg = _assumptions(params)
    summary = summary or {}
    events = list(events or [])

    by_act = summary.get("by_activity_min") or {}
    lost = summary.get("lost_min") or {}
    switches = summary.get("switches") or 0

    def _num(d, key):
        v = d.get(key)
        return float(v) if v else 0.0

    switching_total = float(switches) * float(cfg["switch_cost_min"])
    if "wait" in by_act:
        waiting_total = _num(by_act, "wait")
    elif "wait" in lost:
        waiting_total = _num(lost, "wait")
    else:
        waiting_total = sum(
            float(e.get("duration_s", 0.0) or 0.0) / 60.0
            for e in events if e.get("activity") == "wait"
        )
    if "search" in by_act or "search_failed" in lost:
        search_total = _num(by_act, "search")
        failed_total = min(_num(lost, "search_failed"), search_total) if search_total else _num(lost, "search_failed")
        refind_total = failed_total + 0.5 * max(0.0, search_total - failed_total)
    else:
        refind_total = sum(_event_leak_min(e) for e in events if e.get("activity") == "search")
    if "admin" in by_act:
        admin_total = _num(by_act, "admin")
    else:
        admin_total = sum(
            float(e.get("duration_s", 0.0) or 0.0) / 60.0
            for e in events if e.get("activity") == "admin"
        )

    if events:
        days_observed = float(len({_day_key(e["t"]) for e in events if "t" in e} or {None}))
    else:
        days_observed = 1.0

    per_day_min = {
        "switching": switching_total / days_observed,
        "waiting": waiting_total / days_observed,
        "re_finding": refind_total / days_observed,
        "admin": admin_total / days_observed,
    }
    per_day_min["total"] = (
        per_day_min["switching"] + per_day_min["waiting"]
        + per_day_min["re_finding"] + per_day_min["admin"]
    )

    total_min = summary.get("total_min")
    tracked_total = float(total_min) if total_min else sum(float(v) for v in by_act.values() if v)
    if not tracked_total and events and not by_act:
        tracked_total = sum(float(e.get("duration_s", 0.0) or 0.0) for e in events) / 60.0
    tracked_per_day_min = tracked_total / days_observed

    leaked_total = per_day_min["total"] * days_observed
    denom = max(tracked_total, leaked_total)
    leak_score = int(max(0, min(100, round(100 * leaked_total / denom)))) if denom else 0

    week_hours = per_day_min["total"] * cfg["workdays_per_week"] / 60.0
    month_hours = week_hours * cfg["weeks_per_month"]
    year_hours = per_day_min["total"] * cfg["workdays_per_year"] / 60.0
    decade_hours = year_hours * cfg["years_per_decade"]
    rate = cfg["hourly_rate_usd"]
    compounded = {
        "week": {"hours": week_hours, "usd": week_hours * rate},
        "month": {"hours": month_hours, "usd": month_hours * rate},
        "year": {"hours": year_hours, "usd": year_hours * rate},
        "decade": {"hours": decade_hours, "usd": decade_hours * rate},
    }
    return {
        "days_observed": days_observed,
        "per_day_min": per_day_min,
        "tracked_per_day_min": tracked_per_day_min,
        "compounded": compounded,
        "leak_score": leak_score,
        "assumptions": cfg,
    }


def daily_history(events, tz_offset_s=0):
    """Group events by local date into per-day leaked vs tracked minutes."""
    by_day = {}
    for e in sorted(events or [], key=lambda v: v.get("t", 0)):
        if "t" not in e:
            continue
        day = _day_key(e["t"], tz_offset_s)
        by_day.setdefault(day, []).append(e)
    out = []
    for day in sorted(by_day):
        day_events = by_day[day]
        leak = sum(_event_leak_min(e) for e in day_events)
        leak += _day_switches(day_events, DEFAULTS["switch_cost_min"])
        tracked = sum(float(e.get("duration_s", 0.0) or 0.0) for e in day_events) / 60.0
        out.append({"date": day, "leak_min": leak, "tracked_min": tracked})
    return out


def progress(history, params=None):
    """Time won back, XP, and level from a ``daily_history`` list."""
    _ = _assumptions(params)
    history = list(history or [])
    if not history:
        return {
            "baseline_min_per_day": 0.0,
            "today_min": 0.0,
            "won_back_min": 0.0,
            "xp": 0,
            "level": 0,
            "level_name": _level_name(0),
            "xp_into_level": 0,
            "xp_for_next": _level_threshold(1),
        }
    leaks = [float(d.get("leak_min", 0.0) or 0.0) for d in history]
    if len(leaks) == 1:
        baseline = leaks[0]
    else:
        baseline = _median(leaks[:-1])
    won_back = sum(max(0.0, baseline - v) for v in leaks[1:])
    xp = int(round(won_back))
    level = 0
    while xp >= _level_threshold(level + 1):
        level += 1
    return {
        "baseline_min_per_day": baseline,
        "today_min": leaks[-1],
        "won_back_min": won_back,
        "xp": xp,
        "level": level,
        "level_name": _level_name(level),
        "xp_into_level": xp - _level_threshold(level),
        "xp_for_next": _level_threshold(level + 1) - xp,
    }
