# SPDX-License-Identifier: Apache-2.0
"""Attention and focus measures derived from blocks. Pure, deterministic, and every number can be traced to the blocks it came from.

Definitions (stated so they can be argued with):
  shift        a change from one place (app or site) to a different one, ignoring idle time
  dwell        how long one stay lasted
  fragmented   a stay shorter than 30 s
  return time  after leaving a focus stay for something else, how long until you were back in a focus category
  score        100 x (1 - (0.45 x fragmented share + 0.35 x min(1, shifts per hour / 60) + 0.20 x distraction share)). A summary of three
               measured things, not a medical or psychological measure of attention.
Input intensity (active ticks per minute, at most 240 because the agent samples four times a second) appears only when the person accepted
the input-activity notice. It counts moments with any keyboard or mouse input, not keys or clicks."""
from collections import Counter

from .analyze import label
from .segment import FOCUS

FRAGMENT_S = 30
W_FRAG, W_SHIFT, W_DIST = 0.45, 0.35, 0.20
SHIFTS_PER_HOUR_CAP = 60


_label = label


def _pct(sorted_vals, p):
    if not sorted_vals:
        return 0
    return sorted_vals[min(len(sorted_vals) - 1, int(p * len(sorted_vals)))]


def measure(blocks):
    act = [b for b in blocks if b["category"] != "Idle"]
    total = sum(b["seconds"] for b in act)
    if total < 60:
        return dict(enough=False, reason="less than a minute of active time", formula=_formula())
    hours = total / 3600
    shifts = sum(1 for a, b in zip(act, act[1:]) if _label(a) != _label(b))
    dwell = sorted(b["seconds"] for b in act)
    frag = sum(b["seconds"] for b in act if b["seconds"] < FRAGMENT_S) / total
    dist = sum(b["seconds"] for b in act if b["category"] == "Distraction") / total
    sph = shifts / hours
    score = round(100 * (1 - (W_FRAG * frag + W_SHIFT * min(1.0, sph / SHIFTS_PER_HOUR_CAP) + W_DIST * dist)))
    # whole stays in focus categories, joined across tiny interruptions is NOT done: the longest stay is the longest unbroken one
    longest = max((b for b in act if b["category"] in FOCUS), key=lambda b: b["seconds"], default=None)
    returns, i = [], 0
    while i < len(act):
        if act[i]["category"] in FOCUS:
            j = i + 1
            while j < len(act) and act[j]["category"] not in FOCUS:
                j += 1
            if j > i + 1 and j < len(act):
                returns.append(act[j]["start"] - act[i]["end"])
            i = max(j, i + 1)
        else:
            i += 1
    out = dict(
        enough=True, active_s=round(total), shifts=shifts, shifts_per_hour=round(sph, 1),
        dwell_median_s=round(_pct(dwell, 0.5)), dwell_p90_s=round(_pct(dwell, 0.9)), fragmented_share=round(frag, 3), distraction_share=round(dist, 3),
        longest_focus=dict(seconds=round(longest["seconds"]), start=longest["start"], where=_label(longest)) if longest else None,
        return_time_s=dict(count=len(returns), median=round(_pct(sorted(returns), 0.5)), max=round(max(returns))) if returns else dict(count=0, median=0, max=0),
        score=max(0, min(100, score)), formula=_formula(),
        components=dict(fragmented=round(W_FRAG * frag, 3), shifts=round(W_SHIFT * min(1.0, sph / SHIFTS_PER_HOUR_CAP), 3), distraction=round(W_DIST * dist, 3)))
    # panel focus: which kind of control had the focus, by time. Control types (window classes), never names or text.
    ctl = Counter()
    for b in act:
        if b.get("ctl"):
            ctl[(b["app"], b["ctl"])] += b["seconds"]
    out["focus_controls"] = [dict(app=a, control=c, seconds=round(s)) for (a, c), s in ctl.most_common(10)]
    # input intensity (events per minute), only from blocks that carry counts
    cov = [b for b in act if b.get("inp") is not None and b.get("inp_s", 0) > 0]
    if cov:
        def rate(bs):
            s = sum(b["inp_s"] for b in bs)
            return round(60 * sum(b["inp"] for b in bs) / s, 1) if s else None
        out["input_ticks_per_minute"] = dict(overall=rate(cov), focus=rate([b for b in cov if b["category"] in FOCUS]),
                                       other=rate([b for b in cov if b["category"] not in FOCUS]), covered_s=round(sum(b["inp_s"] for b in cov)))
    return out


def _formula():
    return (f"score = 100 x (1 - ({W_FRAG} x fragmented_share + {W_SHIFT} x min(1, shifts_per_hour/{SHIFTS_PER_HOUR_CAP}) + {W_DIST} x distraction_share)); "
            f"fragmented = stay under {FRAGMENT_S} s")
