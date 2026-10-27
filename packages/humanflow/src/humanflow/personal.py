# SPDX-License-Identifier: Apache-2.0
"""Personal time accounting. The ledger belongs to one person: it is built from their own events and only that person (the owner) can read the per-event detail.
What leaves the ledger is a `Summary` of totals per category that the owner chooses to share. Isolated: standard library only."""
CATEGORIES = ("focus", "meeting", "comms", "search", "wait", "admin", "other")
LOSS = ("wait", "search_failed", "switching", "rework")

def episodes(events, gap_cap_s=300.0):
    """Merge consecutive events with the same activity into episodes. Time between events counts toward the earlier event but is capped (a long silence is not work)."""
    ev = sorted(events, key=lambda e: e["t"]); out = []
    for i, e in enumerate(ev):
        nxt = ev[i + 1]["t"] - e["t"] if i + 1 < len(ev) else e.get("duration_s", 0.0); dur = min(max(nxt, 0.0), gap_cap_s) if e.get("duration_s", 0) == 0 else e["duration_s"]
        act = e["activity"] if e["activity"] in CATEGORIES else "other"
        if out and out[-1]["activity"] == act: out[-1]["seconds"] += dur; out[-1]["events"] += 1
        else: out.append(dict(activity=act, seconds=dur, events=1, t=e["t"], failed_search=bool(e.get("failed_search"))))
    return out

class PersonalLedger:
    def __init__(self, owner): self.owner, self._events = owner, []
    def add(self, ev): self._events.append(dict(ev))
    def detail(self, requester):
        if requester != self.owner: raise PermissionError("per-event detail is readable only by its owner")
        return list(self._events)
    def summary(self, requester, switch_cost_s=None):
        """Totals per category and time-loss components. `switch_cost_s` is the seconds a context switch costs THIS person; unknown (None) means switching is reported as a count only: UNCALIBRATED."""
        if requester != self.owner: raise PermissionError("summary is produced for its owner, who decides what to share")
        eps = episodes(self._events); tot = {c: 0.0 for c in CATEGORIES}
        for e in eps: tot[e["activity"]] += e["seconds"]
        switches = max(0, len(eps) - 1); failed = sum(e["seconds"] for e in eps if e["activity"] == "search" and e["failed_search"])
        loss = {"wait": tot["wait"], "search_failed": failed, "switching": (switches * switch_cost_s) if switch_cost_s is not None else None, "rework": 0.0}
        known = sum(v for v in loss.values() if v is not None)
        return dict(total_s=sum(tot.values()), by_category=tot, switches=switches, loss=loss, loss_s_known=known, switching_calibrated=switch_cost_s is not None)
