# SPDX-License-Identifier: Apache-2.0
"""Challenges from grouped, compounded loss. Routing is backend here: findings from many days are grouped by
(kind, places), priced as minutes lost per day, compounded over 7/30 days, and turned into one challenge each —
the simplest solution that removes the pattern, asked Socratically, with an XP reward priced in minutes
reclaimed (the valued metric: time). Pure functions of day objects; no model."""
import json

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


def bind(store):
    store.x("CREATE TABLE IF NOT EXISTS pinned_challenges(id INTEGER PRIMARY KEY, kind TEXT, places TEXT, fix TEXT, xp INTEGER, pinned_date TEXT, status TEXT, completed_date TEXT)")
    store.x("CREATE TABLE IF NOT EXISTS xp_awards(id INTEGER PRIMARY KEY, pin_id INTEGER, xp INTEGER, date TEXT, UNIQUE(pin_id))")


def pin(store, kind, places, fix, xp, today):
    bind(store)
    places = [str(x)[:60] for x in (places or [])[:4]]
    rows = store.q("SELECT id FROM pinned_challenges WHERE kind=? AND places=? AND status='active'", (kind, json.dumps(places)))
    if rows:
        return dict(id=rows[0]["id"], pinned=True, already=True)
    cur = store.ux("INSERT INTO pinned_challenges(kind,places,fix,xp,pinned_date,status) VALUES(?,?,?,?,?,'active')",
                   (str(kind)[:30], json.dumps(places), str(fix)[:280], int(xp), today))
    return dict(id=cur, pinned=True, already=False)


def unpin(store, pin_id):
    bind(store)
    store.x("UPDATE pinned_challenges SET status='dropped' WHERE id=?", (int(pin_id),))
    return dict(id=int(pin_id), pinned=False)


def pins(store):
    bind(store)
    return [dict(r, places=json.loads(r["places"])) for r in store.q("SELECT * FROM pinned_challenges ORDER BY id")]


def check_completion(store, days):
    """A pin completes two verified ways, each awarded once:
    FULL  — first measured day after pinning with no matching finding: full XP.
    HALF  — the pattern still occurs, but its measured minutes/day over the window fell to <=50% of the
            pin-time rate (pin xp == minutes/day at pinning) across >=3 measured days: half XP.
    Absence alone no longer pays without the reduction check when other window days still show the pattern."""
    bind(store)
    done = []
    for p in pins(store):
        if p["status"] != "active":
            continue
        after = [d for d in days if d["date"] > p["pinned_date"] and d["summary"].get("total_s", 1)]
        clean = next((d for d in after if not any(f["kind"] == p["kind"] and list(f["where"][:4]) == p["places"] for f in d["findings"])), None)
        if clean is not None and len(after) >= 1:
            store.x("UPDATE pinned_challenges SET status='completed', completed_date=? WHERE id=?", (clean["date"], p["id"]))
            store.x("INSERT OR IGNORE INTO xp_awards(pin_id,xp,date) VALUES(?,?,?)", (p["id"], p["xp"], clean["date"]))
            done.append(p["id"])
            continue
        if len(after) >= 3 and p["xp"]:
            mins = [sum(f["seconds"] for f in d["findings"] if f["kind"] == p["kind"] and list(f["where"][:4]) == p["places"]) / 60.0 for d in after]
            if sum(mins) / len(mins) <= 0.5 * p["xp"]:
                store.x("UPDATE pinned_challenges SET status='completed', completed_date=? WHERE id=?", (after[-1]["date"], p["id"]))
                store.x("INSERT OR IGNORE INTO xp_awards(pin_id,xp,date) VALUES(?,?,?)", (p["id"], max(1, p["xp"] // 2), after[-1]["date"]))
                done.append(p["id"])
    return done


def bonus_xp(store):
    bind(store)
    return int(store.q("SELECT COALESCE(SUM(xp),0) AS x FROM xp_awards")[0]["x"])


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
