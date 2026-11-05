# SPDX-License-Identifier: Apache-2.0
"""Challenges from grouped, compounded loss. Routing is backend here: findings from many days are grouped by
(kind, places), priced as minutes lost per day, compounded over 7/30 days, and turned into one challenge each —
the simplest solution that removes the pattern, asked Socratically, with an XP reward priced in minutes
reclaimed (the valued metric: time). Pure functions of day objects; no model."""
from .voicetree import ASK

FIX = {
    "detour": "Move the detour to a scheduled break: same pause, on purpose, after the focus block ends.",
    "ping_pong": "Put the two places side by side, or batch every lookup into one pass.",
    "repeated_path": "Make the route one step: a shortcut, template or script for the repeated sequence.",
    "fragmented_focus": "Batch short checks into one slot so focus blocks stay whole for 25 minutes.",
}
TIER = [(120, "Stretch"), (45, "Solid"), (15, "Quick win"), (0, "Warm-up")]


def tier(minutes_per_day):
    for lo, name in TIER:
        if minutes_per_day >= lo:
            return name
    return "Warm-up"


def group(days):
    """days: [Api.day()...] -> grouped loss patterns, biggest compounded loss first, with compounding + challenge."""
    groups, daily = {}, []
    for d in days:
        daily.append(dict(date=d["date"], loss_min=round(d["loss_s"] / 60), simulated=bool(d.get("simulated"))))
        for i, f in enumerate(d["findings"]):
            key = (f["kind"], tuple(f["where"][:4]))
            g = groups.setdefault(key, dict(kind=f["kind"], places=list(key[1]), minutes=0, days=0, sample=f))
            g["minutes"] += round(f["seconds"] / 60)
            g["days"] += 1
    n = max(1, len([d for d in days if d["loss_s"] > 0] or days))
    out = []
    for g in groups.values():
        per_day = round(g["minutes"] / n)
        w = g["sample"]["where"]
        ask = ASK[g["kind"]].format(where=", ".join(w[:3]), m=per_day, back=g["sample"].get("returned_to", "focus"),
                                    w0=w[0] if w else "", w1=w[1] if len(w) > 1 else "", path=" > ".join(w),
                                    runs=g["sample"].get("runs", ""), visits=g["sample"].get("visits", ""))
        out.append(dict(kind=g["kind"], places=g["places"], minutes_total=g["minutes"], days_seen=g["days"],
                        minutes_per_day=per_day, compounded=dict(days7=per_day * 7, days30=per_day * 30),
                        tier=tier(per_day), xp_reward=max(10, per_day), fix=FIX[g["kind"]], ask=ask))
    out.sort(key=lambda x: -x["compounded"]["days30"])
    total_per_day = sum(x["minutes_per_day"] for x in out)
    return dict(days=daily, challenges=out, total=dict(per_day=total_per_day, days7=total_per_day * 7, days30=total_per_day * 30),
                simulated=any(d["simulated"] for d in daily))
