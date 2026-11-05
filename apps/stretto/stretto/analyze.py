"""Loss and path analysis over blocks. Everything here is MEASURED from the recorded blocks; nothing is estimated by a model.
A finding names the blocks it comes from, so a person can check it. A model may later phrase or rank findings, never create them."""
from collections import Counter
from .segment import FOCUS


def label(b):
    return b["domain"] or b["app"].lower().removesuffix(".exe")


def active(blocks):
    return [b for b in blocks if b["category"] != "Idle"]


def summary(blocks):
    by_cat, by_app = Counter(), Counter()
    for b in blocks:
        by_cat[b["category"]] += b["seconds"]
        if b["category"] != "Idle":
            by_app[label(b)] += b["seconds"]
    act = active(blocks)
    return dict(total_s=round(sum(b["seconds"] for b in act)), idle_s=round(by_cat.get("Idle", 0)),
                focus_s=round(sum(v for k, v in by_cat.items() if k in FOCUS)), distraction_s=round(by_cat.get("Distraction", 0)),
                switches=sum(1 for a, b in zip(act, act[1:]) if label(a) != label(b)),
                by_category={k: round(v) for k, v in by_cat.most_common()}, by_app=[(k, round(v)) for k, v in by_app.most_common(12)])


def transitions(blocks):
    """The paths taken: how often each app-to-app move happened and how long the first stay lasted."""
    act = active(blocks)
    c, secs = Counter(), Counter()
    for a, b in zip(act, act[1:]):
        if label(a) != label(b):
            c[(label(a), label(b))] += 1
            secs[(label(a), label(b))] += a["seconds"]
    return [dict(src=a, dst=b, count=n, avg_stay_s=round(secs[(a, b)] / n)) for (a, b), n in c.most_common(15)]


def _ping_pong(act):
    """Runs of A,B,A,B... with short stays: the same two places visited back and forth."""
    found, i = [], 0
    while i < len(act) - 3:
        a, b = label(act[i]), label(act[i + 1])
        j = i + 2
        while j < len(act) and label(act[j]) == (a if (j - i) % 2 == 0 else b) and act[j]["seconds"] < 300:
            j += 1
        if a != b and j - i >= 4 and act[i]["seconds"] < 300 and act[i + 1]["seconds"] < 300:
            idx = list(range(i, j))
            side = {a: 0.0, b: 0.0}
            for k in idx:
                side[label(act[k])] += act[k]["seconds"]
            found.append(dict(kind="ping_pong", where=[a, b], visits=j - i, seconds=round(min(side.values())),
                              span_s=round(sum(side.values())), idx=idx))
            i = j
        else:
            i += 1
    return found


def _repeated_paths(act, lo=3, hi=4, min_runs=3):
    labels = [label(b) for b in act]
    found, used = [], set()
    for n in range(hi, lo - 1, -1):
        seen = Counter(tuple(labels[i:i + n]) for i in range(len(labels) - n + 1) if len(set(labels[i:i + n])) >= 3)
        for seq, cnt in seen.most_common(5):
            if cnt < min_runs:
                continue
            idx, i, taken = [], 0, set()
            while i <= len(labels) - n:
                if tuple(labels[i:i + n]) == seq and not (set(range(i, i + n)) & (used | taken)):
                    idx.append(list(range(i, i + n)))
                    taken.update(range(i, i + n))
                    i += n
                else:
                    i += 1
            if len(idx) >= min_runs:
                used |= taken
                flat = [k for r in idx for k in r]
                total = sum(act[k]["seconds"] for k in flat)
                work = sum(max(act[k]["seconds"] for k in r) for r in idx)
                found.append(dict(kind="repeated_path", where=list(seq), runs=len(idx),
                                  seconds=round(total - work), span_s=round(total), idx=flat))
    return found


def _detours(act):
    """Focus block, then distraction and chatter, then back to focus: the time away and what it cost."""
    found, i = [], 0
    while i < len(act):
        if act[i]["category"] in FOCUS and act[i]["seconds"] >= 120:
            j = i + 1
            while j < len(act) and act[j]["category"] not in FOCUS and act[j]["seconds"] < 900:
                j += 1
            if j > i + 1 and j < len(act) and act[j]["category"] in FOCUS:
                idx = list(range(i + 1, j))
                found.append(dict(kind="detour", where=[label(act[k]) for k in idx], visits=len(idx), returned_to=label(act[j]),
                                  seconds=round(sum(act[k]["seconds"] for k in idx)), idx=idx))
            i = max(j, i + 1)
        else:
            i += 1
    return found


def _fragments(act):
    idx = [k for k, b in enumerate(act) if b["category"] in FOCUS and b["seconds"] < 120]
    return [dict(kind="fragmented_focus", where=[], visits=len(idx), seconds=round(sum(act[k]["seconds"] for k in idx)), idx=idx)] if len(idx) >= 5 else []


SUGGEST = dict(
    ping_pong="Put these two side by side, or batch the lookups: {w0} and {w1} were swapped {visits} times in a row ({m} min on the shorter side).",
    repeated_path="This route repeats: {path}. It ran {runs} times; {m} min of it was moving between places (the longest stop in each run counts as real work). A shortcut, template or script removes that.",
    detour="After focus work you left for {where}: {m} min away, then back to {returned_to}. Move that to a scheduled break.",
    fragmented_focus="{visits} focus stretches were under 2 minutes. Batch short checks so focus blocks stay whole.")


def findings(blocks):
    """Returns (findings, loss_s). loss_s counts every flagged block once, so overlapping findings are not double-counted."""
    act = active(blocks)
    items = _detours(act) + _ping_pong(act) + _repeated_paths(act) + _fragments(act)
    flagged = set()
    for f in items:
        idx = f.pop("idx")
        if f["kind"] != "fragmented_focus":
            flagged.update(idx)
        w = f["where"]
        f["suggestion"] = SUGGEST[f["kind"]].format(w0=w[0] if w else "", w1=w[1] if len(w) > 1 else "", visits=f.get("visits", ""),
                                                    where=", ".join(w[:3]), returned_to=f.get("returned_to", ""), runs=f.get("runs", ""),
                                                    path=" > ".join(w), m=max(1, round(f["seconds"] / 60)))
        f["basis"] = "measured"
        f["blocks"] = [dict(start=act[k]["start"], end=act[k]["end"], what=label(act[k])) for k in idx]
    items.sort(key=lambda f: -f["seconds"])
    return items, round(sum(act[k]["seconds"] for k in flagged))