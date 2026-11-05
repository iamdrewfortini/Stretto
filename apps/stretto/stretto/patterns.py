"""Historical patterns over many days. Pure, deterministic, measured: hour-of-day and weekday profiles of focus and distraction,
the best focus window, and the trend. A pattern needs enough days to mean anything, so each result says how many days stand behind it.

Works from per-day SUMMARIES (see daycache), so it never touches raw events. `profile(days_of_blocks)` is kept for callers that have blocks."""
import datetime as dt

MIN_DAYS = 5


def _slope(ys):
    n = len(ys)
    if n < 3:
        return 0.0
    mx, my = (n - 1) / 2, sum(ys) / n
    den = sum((i - mx) ** 2 for i in range(n))
    return sum((i - mx) * (y - my) for i, y in enumerate(ys)) / den if den else 0.0


def profile_from_summaries(sums):
    """sums: {iso_day: summary} from daycache.summarize. Same output as profile() over the same days (hour arrays differ by under 1 s from rounding)."""
    active = {d: s for d, s in sums.items() if s["total_s"] > 0 or sum(s["hours_total"]) > 0}
    n = len(active)
    hour_focus, hour_dist, hour_total = [0.0] * 24, [0.0] * 24, [0.0] * 24
    wd_focus, wd_days = [0.0] * 7, [0] * 7
    daily = []
    for d in sorted(active):
        s = active[d]
        for h in range(24):
            hour_focus[h] += s["hours_focus"][h]
            hour_dist[h] += s["hours_distraction"][h]
            hour_total[h] += s["hours_total"][h]
        wd = dt.date.fromisoformat(d).weekday()
        wd_focus[wd] += s["focus_s"]
        wd_days[wd] += 1
        daily.append((d, s["focus_s"]))
    avg = lambda xs: [round(x / n) for x in xs] if n else [0] * len(xs)
    best = max(range(24), key=lambda h: sum(hour_focus[(h + k) % 24] for k in range(3))) if n else 0
    worst = max(range(24), key=lambda h: hour_dist[h] / hour_total[h] if hour_total[h] > 600 else -1) if n else 0
    return dict(
        days=n, enough=n >= MIN_DAYS,
        first_day=min(active) if n else None, last_day=max(active) if n else None,
        hour_focus_s=avg(hour_focus), hour_distraction_s=avg(hour_dist),
        weekday_focus_s=[round(wd_focus[i] / wd_days[i]) if wd_days[i] else 0 for i in range(7)], weekday_days=wd_days,
        best_window=dict(start_hour=best, end_hour=(best + 3) % 24, avg_focus_s=round(sum(hour_focus[(best + k) % 24] for k in range(3)) / n)) if n else None,
        most_distracted_hour=worst if n and hour_total[worst] > 600 else None,
        trend_s_per_day=round(_slope([f for _, f in daily])), daily_focus=[dict(day=d, focus_s=round(f)) for d, f in daily[-120:]])


def profile(days):
    """days: {iso_day: [block, ...]}. Summarises each day, then delegates."""
    from .daycache import summarize
    return profile_from_summaries({d: summarize(bs) for d, bs in days.items()})
