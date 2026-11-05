# SPDX-License-Identifier: Apache-2.0
"""XP, levels, streaks, badges. Deterministic arithmetic over measured focus time. No model involved."""
import datetime as dt
import math


def xp_for_day(focus_s, goal_s):
    return int(focus_s // 60) + (25 if goal_s and focus_s >= goal_s else 0)


def level(xp):
    lv = int(math.sqrt(max(xp, 0) / 50)) + 1
    return dict(level=lv, xp=xp, floor=50 * (lv - 1) ** 2, next=50 * lv ** 2)


def streak(focus_by_day, today, goal_s, rest_per_week=1):
    """Consecutive goal days ending today. One rest day per rolling week does not break it. Today unmet does not count against you yet."""
    d, n, rests, walked = dt.date.fromisoformat(today), 0, [], 0
    if focus_by_day.get(d.isoformat(), 0) < goal_s:
        d -= dt.timedelta(days=1)
    while walked < 400:
        met = focus_by_day.get(d.isoformat(), 0) >= goal_s
        if met:
            n += 1
        else:
            rests = [r for r in rests if (d - r).days < 7]
            if len(rests) >= rest_per_week:
                break
            rests.append(d)
        d -= dt.timedelta(days=1)
        walked += 1
    return n


def badges(total_focus_s, longest_block_s, streak_days):
    out = []
    for ok, name in ((total_focus_s >= 3600, "First hour"), (longest_block_s >= 3000, "Deep block (50 min)"),
                     (streak_days >= 3, "3-day streak"), (streak_days >= 7, "7-day streak"), (streak_days >= 30, "30-day streak")):
        if ok:
            out.append(name)
    return out