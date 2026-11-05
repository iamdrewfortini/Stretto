# SPDX-License-Identifier: Apache-2.0
"""The five atomic points of measurement for time. Everything Stretto reports is composed from these, the way
matter composes from atoms — nothing is measured at a higher level that cannot be traced back to one of them:
  A1 ONSET       when a block starts (phase of day, concentration of starts)
  A2 DWELL       how long one stay lasts (median dwell, fragmentation)
  A3 TRANSITION  each change of place (switch rate, Markov entropy of moves)
  A4 IDLE GAP    dead time and return time (idle share, time back to focus)
  A5 RECURRENCE  when the same shape repeats (repeated-pattern share, regularity)
Each atom yields a health in [0,1]. Energy is the bookkeeping: active minutes are the budget, and the leak is
the share dissipated by unhealthy atoms, priced in minutes — an energy leak, measured, not a metaphor for one.
Balance is learned: five weights, one per atom, updated by multiplicative weights (Hedge) against each day's
realised loss, so the balance keeps mapping this person's patterns, habits, usage and leaks as they change."""
import math
from collections import Counter

NAMES = ["onset", "dwell", "transition", "idle_gap", "recurrence"]
DEFAULT_WEIGHTS = [0.20, 0.25, 0.25, 0.15, 0.15]


def _entropy(counts):
    tot = sum(counts) or 1
    return -sum((c / tot) * math.log2(c / tot) for c in counts if c) / math.log2(max(2, len([c for c in counts if c])))


def measure(blocks, transitions=None):
    """The five atoms for one day's blocks. Returns dict(atom -> dict(value..., health)). Pure, measured only."""
    from . import analyze
    act = [b for b in blocks if b["category"] != "Idle"]
    if not act:
        return {n: dict(health=0.0, value=None) for n in NAMES} | dict(energy=dict(active_min=0, leak_min=0, leak_per_hour=0.0))
    total = sum(b["seconds"] for b in act)
    # A1 onset: starts concentrated in few hours = healthy rhythm
    hours = Counter(int(b["start"] // 3600) % 24 for b in act)
    a1 = 1.0 - _entropy([hours.get(h, 0) for h in range(24)])
    # A2 dwell: median stay and fragmentation share
    dwell = sorted(b["seconds"] for b in act)
    med = dwell[len(dwell) // 2]
    frag = sum(b["seconds"] for b in act if b["seconds"] < 30) / total
    a2 = max(0.0, min(1.0, (med / 900.0)) * (1.0 - frag))
    # A3 transition: switches/hour (capped 60) and move entropy
    trans = transitions if transitions is not None else analyze.transitions(act)
    sph = sum(1 for a, b in zip(act, act[1:]) if analyze.label(a) != analyze.label(b)) / max(1.0, total / 3600)
    a3 = max(0.0, 1.0 - min(1.0, sph / 60.0)) * (1.0 - 0.5 * _entropy([t["count"] for t in trans] or [1]))
    # A4 idle gap: idle share of the whole span + focus return discipline (short detours home)
    span = max(total, act[-1]["end"] - act[0]["start"])
    idle_share = max(0.0, (span - total) / span) if span else 0.0
    a4 = max(0.0, 1.0 - idle_share * 1.5)
    # A5 recurrence: repeated-pattern share of the day (structure that can be automated or broken)
    found, loss = analyze.findings([dict(b) for b in blocks])
    rep = sum(f["seconds"] for f in found if f["kind"] == "repeated_path") / total
    a5 = max(0.0, 1.0 - min(1.0, rep * 3))
    health = [round(x, 4) for x in (a1, a2, a3, a4, a5)]
    return dict(onset=dict(starts=len(act), concentration=round(a1, 4), health=health[0]),
                dwell=dict(median_s=med, fragmented_share=round(frag, 4), health=health[1]),
                transition=dict(switches_per_hour=round(sph, 2), health=health[2]),
                idle_gap=dict(idle_share=round(idle_share, 4), health=health[3]),
                recurrence=dict(repeated_share=round(rep, 4), loss_min=round(loss / 60), health=health[4]),
                health=health)


def leak(measured, weights=None):
    """Energy bookkeeping: leak minutes = active minutes x weighted ill-health. Balanced by learned weights."""
    w = weights or DEFAULT_WEIGHTS
    h = measured.get("health") or [measured[n]["health"] for n in NAMES]
    ill = sum(wi * (1.0 - hi) for wi, hi in zip(w, h))
    return round(ill, 4)


def hedge_update(weights, healths, realised_loss_ratio, eta=0.35):
    """One Hedge step: atoms whose ill-health matched realised loss gain weight; the rest decay. Regret-bounded,
    so the balance tracks a changing person instead of freezing on last month's habits. Returns new weights (sum 1)."""
    out = []
    for w, h in zip(weights, healths):
        pred_ill = 1.0 - h
        loss = abs(pred_ill - realised_loss_ratio)
        out.append(w * math.exp(-eta * loss))
    tot = sum(out) or 1.0
    return [round(x / tot, 6) for x in out]
