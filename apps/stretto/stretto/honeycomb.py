# SPDX-License-Identifier: Apache-2.0
"""Honeycomb cache: a hex-cell cache for coaching artifacts and day vectors.

Each day's measured facts become a small vector (an embedding in the plain sense: numbers that place similar
days near each other). The vector is quantised into hexagonal axial cells (two coordinates per cell pair), and
validated coaching artifacts are stored under their cell + facts hash in a local `honeycomb` table. A later day
whose vector lands in the same or a neighbouring cell and whose finding signature matches exactly may reuse the
artifact instead of paying for a new model call; anything else misses. Pure stdlib, no model involved."""
import json
import math
import time

SCALE = 4          # vector units per hex step: days within ~0.25 on two axes share a cell
DIMS = ("focus", "distraction", "idle", "lost", "switches", "detour", "ping_pong", "repeated", "fragmented")


def vector(facts):
    """Deterministic 9-dim day vector in [0,1] from insights.facts(). Similar measured days land near each other."""
    total = max(1, facts.get("active_minutes", 0) + facts.get("idle_minutes", 0))
    kinds = {}
    for f in facts.get("findings", []):
        kinds[f["kind"]] = kinds.get(f["kind"], 0) + f.get("minutes", 0)
    lost = max(1, facts.get("lost_minutes", 0))
    raw = [facts.get("focus_minutes", 0) / total, facts.get("distraction_minutes", 0) / total,
           facts.get("idle_minutes", 0) / total, facts.get("lost_minutes", 0) / total,
           min(1.0, facts.get("switches", 0) / 200.0), kinds.get("detour", 0) / lost,
           kinds.get("ping_pong", 0) / lost, kinds.get("repeated_path", 0) / lost,
           kinds.get("fragmented_focus", 0) / lost]
    n = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [round(x / n, 6) for x in raw]


def signature(facts):
    """What must match exactly before an artifact may be reused: finding kinds + places, in order."""
    return json.dumps([[f["kind"], f.get("places", [])] for f in facts.get("findings", [])], sort_keys=True)


def cell(vec):
    """Axial hex coordinates: one (q, r) pair per two vector axes, plus the leftover axis. Neighbours differ by 1."""
    out = []
    for i in range(0, len(vec) - 1, 2):
        out += [round(vec[i] * SCALE), round(vec[i + 1] * SCALE)]
    if len(vec) % 2:
        out.append(round(vec[-1] * SCALE))
    return tuple(out)


def neighbours(c):
    """The cell itself plus every cell one hex step away on any axis pair."""
    out = {c}
    for i in range(len(c)):
        for d in (-1, 1):
            n = list(c); n[i] += d; out.add(tuple(n))
    return out


def cosine(a, b):
    d = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return d / (na * nb)


def bind(store):
    store.x("CREATE TABLE IF NOT EXISTS honeycomb(cell TEXT, facts_sha TEXT PRIMARY KEY, vec TEXT, sig TEXT, artifact TEXT, ts REAL)")


def put(store, facts_sha, facts, artifact):
    bind(store)
    v, c = vector(facts), None
    c = ",".join(str(x) for x in cell(v))
    store.x("INSERT OR REPLACE INTO honeycomb(cell,facts_sha,vec,sig,artifact,ts) VALUES(?,?,?,?,?,?)",
            (c, facts_sha, json.dumps(v), signature(facts), json.dumps(artifact), time.time()))


def get(store, facts_sha, facts):
    """(artifact, how) or (None, 'miss'). Exact facts hash first, then a same/neighbour-cell vector twin with an identical signature."""
    bind(store)
    rows = store.q("SELECT artifact FROM honeycomb WHERE facts_sha=?", (facts_sha,))
    if rows:
        return json.loads(rows[0]["artifact"]), "exact"
    v, sig = vector(facts), signature(facts)
    cells = {",".join(str(x) for x in c) for c in neighbours(cell(v))}
    for r in store.q("SELECT vec, sig, artifact FROM honeycomb"):
        if r["sig"] != sig:
            continue
        if cosine(v, json.loads(r["vec"])) >= 0.999:
            return json.loads(r["artifact"]), "honeycomb-twin"
    return None, "miss"


def route(store, facts, cost_weight=0.05):
    """Optimised route circuit for a grounded cached response: walk hex rings outward from the day's cell,
    keep only artifacts whose finding signature matches exactly (grounded) — among those, nearest by cosine
    (most accurate) wins, with estimated cost as the tie-break (cheapest). Returns (artifact, info) or (None, info).
    This is the fast path the voice agent takes before any model call is considered."""
    bind(store)
    v, sig, c0 = vector(facts), signature(facts), cell(vector(facts))
    best, visited = None, 0
    rows = store.q("SELECT cell, vec, sig, artifact FROM honeycomb")
    if not rows:
        return None, dict(cells_visited=0, similarity=0.0, grounded=False)
    by_cell = {}
    for r in rows:
        by_cell.setdefault(r["cell"], []).append(r)
    ring, seen = [c0], set()
    for _ in range(SCALE * 2 + 1):
        nxt = []
        for c in ring:
            key = ",".join(str(x) for x in c)
            if key in seen:
                continue
            seen.add(key); visited += 1
            for r in by_cell.get(key, []):
                if r["sig"] != sig:
                    continue
                art = json.loads(r["artifact"])
                sim = cosine(v, json.loads(r["vec"]))
                score = sim - cost_weight * float(art.get("cost_usd") or 0)
                if best is None or score > best[0]:
                    best = (score, art, sim, key)
            nxt.extend(neighbours(c))
        if best is not None or visited > 512:   # hard cap: the voice fast path must stay fast even on a sparse comb
            break
        ring = list(set(nxt) - seen)[:512]
        if not ring:
            break
    if best is None:
        return None, dict(cells_visited=visited, similarity=0.0, grounded=False)
    return best[1], dict(cells_visited=visited, similarity=round(best[2], 6), cell=best[3], grounded=True,
                         est_cost_usd=best[1].get("cost_usd"))


def stats(store):
    bind(store)
    rows = store.q("SELECT cell, COUNT(*) AS n FROM honeycomb GROUP BY cell")
    return dict(cells=len(rows), artifacts=sum(r["n"] for r in rows), dims=list(DIMS), scale=SCALE)
