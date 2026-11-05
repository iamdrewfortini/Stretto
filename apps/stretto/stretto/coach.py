# SPDX-License-Identifier: Apache-2.0
"""Coach: goal horizons learned from the person's own analytics, priced in time reclaimed.
The pattern engine says when focus comes easiest and how much is being lost; this module turns that into a
stretch ramp — reclaim 25% of daily loss in week 1, rising to 65% by week 4. Push till it breaks: a met week
raises the next target 15%, two missed weeks ease it 10%, and the plan says so in plain language. Deterministic;
a model may phrase the plan (Insights) but never sets its numbers."""
import math

RANKS = [(1, "Starter"), (3, "Regular"), (5, "Focused"), (8, "Deep worker"), (12, "Timewright"), (20, "Stretto")]


def rank(level):
    cur, nxt = RANKS[0], None
    for lo, name in RANKS:
        if level >= lo:
            cur = (lo, name)
        elif nxt is None:
            nxt = (lo, name)
    return dict(title=cur[1], next=(dict(level=nxt[0], title=nxt[1]) if nxt else None))


def plan(patterns, avg_loss_min, avg_focus_min, weeks_met=0, weeks_missed=0, horizon_weeks=4):
    """patterns: patterns.profile_from_summaries output (best_window, trend...). Returns the ramp + coaching line."""
    base = [0.25, 0.35, 0.50, 0.65][:horizon_weeks] if horizon_weeks <= 4 else [0.25, 0.35, 0.50, 0.65] + [0.75] * (horizon_weeks - 4)
    adj, note = 1.0, "Set from your measured loss and best focus window."
    if weeks_met >= 1:
        adj, note = 1.15, "Last week was met, so the ramp steepens 15%. Push till it breaks — that break is the data."
    if weeks_missed >= 2:
        adj, note = 0.90, "Two missed weeks: the ramp eases 10%. Iterate the process, not your opinion of yourself."
    ramp = [dict(week=i + 1, reclaim_min=round(avg_loss_min * f * adj), share=round(f * adj, 2)) for i, f in enumerate(base)]
    best = (patterns or {}).get("best_window") or {}
    return dict(metric="time", ramp=ramp, total_reclaim_min=sum(r["reclaim_min"] * 7 for r in ramp),
                best_window=best, avg_loss_min=avg_loss_min, avg_focus_min=avg_focus_min, note=note,
                teach="Protect the best window first, batch the biggest leak second, review every Sunday: keep what reclaimed time, change one thing that did not.")
