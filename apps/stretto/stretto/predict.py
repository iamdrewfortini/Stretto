# SPDX-License-Identifier: Apache-2.0
"""Realtime tensor prediction over the golden lattice. Small dense/sparse matrix ops, pure Python, microseconds:
  next_places  — row-normalise the transition matrix into a Markov chain and read the top next places for 'now'.
  focus_forecast — from the (24,3) hours profile + patterns best window, predict today's remaining focus minutes
                   if the person works their usual next three hours.
  reclaim_eta  — from the coach ramp and pinned challenges, the date the top challenge pays off at the current pace.
Predictions are labelled estimates over measured matrices; they never invent a number the matrices do not contain."""
import datetime as dt


def next_places(transitions, current, top=3):
    """Markov prediction: P(next|current) from measured transition counts."""
    row = {}
    total = 0
    for t in transitions:
        if t["src"] == current:
            row[t["dst"]] = row.get(t["dst"], 0) + t["count"]; total += t["count"]
    if not total:
        return []
    return [dict(place=d, p=round(c / total, 4), avg_stay_s=next((t["avg_stay_s"] for t in transitions if t["src"] == current and t["dst"] == d), 0))
            for d, c in sorted(row.items(), key=lambda kv: -kv[1])[:top]]


def focus_forecast(pat, now_hour=None):
    """pat: patterns.profile_from_summaries output (hour_focus_s is already average seconds per day per hour)."""
    hf = pat.get("hour_focus_s") if isinstance(pat, dict) else None
    if not hf:
        return dict(next3h_focus_min=0, basis="no profile yet")
    h = (now_hour if now_hour is not None else dt.datetime.now().hour) % 24
    nxt = [hf[(h + k) % 24] for k in (1, 2, 3)]
    return dict(next3h_focus_min=round(sum(nxt) / 60), per_hour=[round(x / 60) for x in nxt],
                basis=f"{pat.get('days', 0)} measured days", best_window=pat.get("best_window"))


def reclaim_eta(challenges_out, ramp):
    """When the top pinned-worthy challenge pays for itself: compounded minutes vs the ramp reclaim rate."""
    if not challenges_out.get("challenges") or not ramp:
        return None
    top = challenges_out["challenges"][0]
    rate = max(1, ramp[0]["reclaim_min"])
    days = -(-top["compounded"]["days30"] // max(1, rate * 30))  # months of ramp to offset a month of the leak
    return dict(kind=top["kind"], places=top["places"], leak_30d_min=top["compounded"]["days30"],
                ramp_min_per_day=rate, months_to_offset=days)
