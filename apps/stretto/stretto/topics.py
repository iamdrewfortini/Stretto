# SPDX-License-Identifier: Apache-2.0
"""Topic buckets and semantic recall over the person's own work objects, on-device.
Items (tasks, challenges, findings, cached insights) become sparse term vectors (with a small synonym map so
'deep work' recalls 'focus'). Buckets are greedy cosine clusters labelled by their strongest terms; recall ranks
every item against a query vector. Deterministic, private, no model call — semantics at this scale do not need one."""
import json
import math
import re

from . import challenges as _ch
from . import embedder

STOP = set("the a an and or to of in on for with my i it is are be this that from by at as into your you we our".split())
SYN = {"deep": "focus", "coding": "build", "code": "build", "writing": "write", "email": "communication",
       "chat": "communication", "meeting": "communication", "leak": "loss", "wasted": "loss", "distraction": "distraction",
       "phone": "distraction", "planning": "plan", "money": "time", "hours": "time"}


def terms(text):
    out = []
    for w in re.findall(r"[a-z0-9][a-z0-9\-]{1,30}", str(text).lower()):
        if w in STOP or len(w) < 3:
            continue
        out.append(SYN.get(w, w))
    return out


def vector(text):
    v = {}
    for w in terms(text):
        v[w] = v.get(w, 0) + 1
    n = math.sqrt(sum(x * x for x in v.values())) or 1.0
    return {k: round(x / n, 6) for k, x in v.items()}


def cosine(a, b):
    if len(a) > len(b):
        a, b = b, a
    return round(sum(x * b.get(k, 0.0) for k, x in a.items()), 6)


def item(kind, ref, text, extra=None):
    text = str(text)[:280]
    return dict(kind=kind, ref=str(ref), text=text, vec=vector(text), dense=embedder.dense(text, terms(text)), extra=extra or {})


def collect(store, api):
    """Every recallable object the server already holds. api is server.Api (tasks + challenges need it)."""
    out = []
    for t in store.q("SELECT id, title, status FROM tasks ORDER BY id"):
        out.append(item("task", t["id"], t["title"], dict(status=t["status"])))
    for p in _ch.pins(store):
        out.append(item("challenge", p["id"], f"{p['kind']} {' '.join(p['places'])} {p['fix']}", dict(status=p["status"], xp=p["xp"])))
    for r in store.q("SELECT date, result FROM insight_cache ORDER BY date DESC LIMIT 30"):
        try:
            art = json.loads(r["result"])
        except Exception:
            continue
        txt = art.get("headline", "") + " " + " ".join(a.get("title", "") + " " + a.get("how", "") for a in art.get("actions", []))
        if txt.strip():
            out.append(item("insight", r["date"], txt, dict(date=r["date"])))
    day = api.day()
    for i, f in enumerate(day["findings"]):
        out.append(item("finding", f"f{i}", f"{f['kind']} {' '.join(f['where'])} {f.get('suggestion', '')}", dict(minutes=round(f["seconds"] / 60))))
    store.x("CREATE TABLE IF NOT EXISTS turns(id INTEGER PRIMARY KEY, you TEXT, reply TEXT, tools TEXT, ts REAL)")
    for r in store.q("SELECT id, you, reply FROM turns ORDER BY id DESC LIMIT 100"):
        txt = (r["you"] or "") + " " + (r["reply"] or "")
        if txt.strip():
            out.append(item("conversation", r["id"], txt, dict()))
    return out


def buckets(items, threshold=0.22):
    """Greedy: an item joins the first bucket whose centroid it matches, else starts one. Label = top terms."""
    cents, groups = [], []
    for it in items:
        best, bi = threshold, -1
        for i, c in enumerate(cents):
            s = cosine(it["vec"], c)
            if s > best:
                best, bi = s, i
        if bi < 0:
            groups.append([it]); cents.append(dict(it["vec"]))
        else:
            groups[bi].append(it)
            for k, x in it["vec"].items():
                cents[bi][k] = cents[bi].get(k, 0) + x
    out = []
    for g, c in zip(groups, cents):
        label = " · ".join(k for k, _ in sorted(c.items(), key=lambda kv: -kv[1])[:3]) or "misc"
        out.append(dict(label=label, items=[dict(kind=x["kind"], ref=x["ref"], text=x["text"], extra=x["extra"]) for x in g],
                        kinds=sorted({x["kind"] for x in g})))
    out.sort(key=lambda b: -len(b["items"]))
    return out


def recall(items, query, limit=12):
    q = vector(query)
    if not q:
        return []
    scored = [dict(kind=x["kind"], ref=x["ref"], text=x["text"], extra=x["extra"],
                   score=embedder.cosine(embedder.dense(query, terms(query)), x["dense"]) if x.get("dense") else cosine(q, x["vec"])) for x in items]
    return [x for x in sorted(scored, key=lambda y: -y["score"]) if x["score"] > 0][:limit]
