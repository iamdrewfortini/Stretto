# SPDX-License-Identifier: Apache-2.0
"""Full graph map of a day, derivable from the same blocks the UI draws: places are nodes (sized by minutes,
tagged with their category), moves are weighted edges, and measured findings are overlaid on the places they
cite. Pure function of a day object from Api.day(); no model, no estimation."""
from collections import Counter


def build(day):
    sm = day["summary"]
    cat_of = {}
    for b in day.get("blocks", []):
        cat_of.setdefault(b.get("domain") or (b.get("app") or "").lower().removesuffix(".exe"), b["category"])
    nodes = [dict(id=n, minutes=round(s / 60), category=cat_of.get(n, "Other")) for n, s in sm["by_app"]]
    edges = [dict(src=t["src"], dst=t["dst"], count=t["count"], avg_stay_s=t["avg_stay_s"]) for t in day.get("transitions", [])]
    overlay = []
    for i, f in enumerate(day.get("findings", [])):
        overlay.append(dict(id=f"f{i}", kind=f["kind"], minutes=max(1, round(f["seconds"] / 60)), places=f["where"][:6]))
    deg = Counter()
    for e in edges:
        deg[e["src"]] += e["count"]; deg[e["dst"]] += e["count"]
    return dict(date=day["date"], nodes=nodes, edges=edges, findings=overlay,
                hubs=[dict(id=n, moves=c) for n, c in deg.most_common(5)], simulated=bool(day.get("simulated")))
