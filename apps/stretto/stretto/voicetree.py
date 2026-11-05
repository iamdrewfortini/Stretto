# SPDX-License-Identifier: Apache-2.0
"""Derivable voice-agent decision tree. A pure function of one measured day: every node, threshold and option
is derived from that day's findings (kind, places, minutes), so the tree a person hears can be re-derived and
audited from the record. The voice agent walks it Socratically — it asks before it acts, and any action node
names the finding it would act on. No model call is needed to build the tree; a model may only phrase it."""

ASK = {
    "detour": "You left {where} for {m} minutes, then came back to {back}. Want to move that to a scheduled break, or keep it as your reset?",
    "ping_pong": "{w0} and {w1} swapped back and forth — {m} minutes on the shorter side. Keep them side by side, or batch the lookups?",
    "repeated_path": "This route repeats: {path}. It ran {runs} times. Want a shortcut for it, or is the walk itself useful thinking time?",
    "fragmented_focus": "{visits} focus stretches were under 2 minutes. Want to batch the short checks, or protect one longer block first?",
}


def derive(day):
    """{root, nodes:{id: node}} for the day. Node: {id, kind, say, finding?, minutes?, options:[{label, next, action?}]}."""
    nodes, order = {}, []
    findings = sorted(day.get("findings", []), key=lambda f: -f["seconds"])
    if not findings:
        nodes["root"] = dict(id="root", kind="affirm", say="No measured leaks today. The day held together — want to log focus, or review the week?",
                             options=[dict(label="Log focus", next="end", action="start_focus"), dict(label="Review week", next="end", action="open_reports")])
        nodes["end"] = dict(id="end", kind="end", say="Done. Nothing changes without your say-so.", options=[])
        return dict(date=day["date"], root="root", nodes=nodes, derived_from=[])
    for i, f in enumerate(findings[:4]):
        nid, nxt = f"n{i}", (f"n{i + 1}" if i + 1 < min(4, len(findings)) else "end")
        w = f["where"]
        say = ASK[f["kind"]].format(where=", ".join(w[:3]), m=max(1, round(f["seconds"] / 60)), back=f.get("returned_to", "focus"),
                                    w0=w[0] if w else "", w1=w[1] if len(w) > 1 else "", path=" > ".join(w),
                                    runs=f.get("runs", ""), visits=f.get("visits", ""))
        nodes[nid] = dict(id=nid, kind="ask", say=say, finding=f"f{i}", minutes=max(1, round(f["seconds"] / 60)),
                          options=[dict(label="Act on it", next=nxt, action=f"act:{f['kind']}"),
                                   dict(label="Skip — show next leak", next=nxt),
                                   dict(label="Stop here", next="end")])
        order.append(nid)
    nodes["root"] = dict(id="root", kind="open",
                         say=f"Your biggest leak cost {max(1, round(findings[0]['seconds'] / 60))} minutes. I will ask about each one; nothing changes unless you pick Act on it.",
                         options=[dict(label="Start", next=order[0]), dict(label="Not now", next="end")])
    nodes["end"] = dict(id="end", kind="end", say="That is the whole tree for today — every question came from a measured finding.", options=[])
    return dict(date=day["date"], root="root", nodes=nodes, derived_from=order)
