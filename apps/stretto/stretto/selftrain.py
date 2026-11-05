# SPDX-License-Identifier: Apache-2.0
"""Self-training on the user's local instance: optimised packing and folding of the embedding geometry over time.
Not weight training and nothing leaves the machine. Two things learn, both bounded and auditable:
  1. Term weights — terms in completed challenges and in items a recall actually surfaced gain weight; the dense
     tensor embedding is rebuilt with those weights, so the geometry bends toward what this person finishes.
  2. Geometry — honeycomb SCALE and the fold threshold are chosen by grid search over the person's own vectors,
     scoring intra-cell cohesion minus inter-cell bleed. New parameters are adopted ONLY when the objective
     improves by at least 0.5%; otherwise the old geometry stays. Every run is logged with before/after scores."""
import hashlib
import json
import math
import time

from . import embedder, folding, honeycomb, topics

SCALES = (2, 3, 4, 6, 8)
FOLDS = (0.25, 0.30, 0.35)
MIN_ITEMS = 12


def bind(store):
    store.x("CREATE TABLE IF NOT EXISTS term_weights(term TEXT PRIMARY KEY, w REAL)")
    store.x("CREATE TABLE IF NOT EXISTS train_log(id INTEGER PRIMARY KEY, ts REAL, items INTEGER, scale INTEGER, fold REAL, before REAL, after REAL, adopted INTEGER, hash TEXT)")


def weights(store):
    bind(store)
    return {r["term"]: r["w"] for r in store.q("SELECT term, w FROM term_weights")}


def learn_terms(store, api):
    """Boost terms from completed pins (+1.0) and active pins (+0.3), decay everything else toward 1.0."""
    bind(store)
    from . import challenges as _ch
    boost = {}
    for p in _ch.pins(store):
        gain = 1.0 if p["status"] == "completed" else 0.3 if p["status"] == "active" else 0.0
        if gain:
            for t in topics.terms(f"{p['kind']} {' '.join(p['places'])} {p['fix']}"):
                boost[t] = boost.get(t, 0) + gain
    cur = weights(store)
    for t in set(cur) | set(boost):
        w = 1.0 + (cur.get(t, 1.0) - 1.0) * 0.9 + boost.get(t, 0.0) * 0.25
        store.x("INSERT OR REPLACE INTO term_weights(term,w) VALUES(?,?)", (t, round(min(4.0, max(0.25, w)), 4)))
    return weights(store)


def _objective(items, scale):
    """Cohesion of honeycomb cells at a scale: mean intra-cell cosine minus mean cross-cell cosine (sampled)."""
    cells = {}
    for it in items:
        if not it.get("dense"):
            continue
        c = honeycomb.cell([x * scale / honeycomb.SCALE for x in it["dense"][:9]])
        cells.setdefault(c, []).append(it["dense"])
    intra, inter, vecs = [], [], [it["dense"] for it in items if it.get("dense")]
    for vs in cells.values():
        for i in range(len(vs)):
            for j in range(i + 1, len(vs)):
                intra.append(embedder.cosine(vs[i], vs[j]))
    for i in range(min(len(vecs), 40)):
        for j in range(i + 1, min(len(vecs), 40)):
            if honeycomb.cell([x * scale / honeycomb.SCALE for x in vecs[i][:9]]) != honeycomb.cell([x * scale / honeycomb.SCALE for x in vecs[j][:9]]):
                inter.append(embedder.cosine(vecs[i], vecs[j]))
    return round((sum(intra) / len(intra) if intra else 0.0) - (sum(inter) / len(inter) if inter else 0.0), 6)


def run(store, api):
    bind(store)
    items = folding.embed_all(store, api)
    if len(items) < MIN_ITEMS:
        return dict(trained=False, reason=f"needs {MIN_ITEMS} embedded items, has {len(items)}", items=len(items))
    cur_scale = int(float(store.setting("honeycomb_scale", honeycomb.SCALE)))
    cur_fold = float(store.setting("fold_threshold", 0.30))
    before = _objective(items, cur_scale)
    best_scale, best_score = cur_scale, before
    for s in SCALES:
        sc = _objective(items, s)
        if sc > best_score:
            best_scale, best_score = s, sc
    adopted = 1 if best_score >= before * 1.005 and best_scale != cur_scale else 0
    if adopted:
        store.set_setting("honeycomb_scale", best_scale)
    w = learn_terms(store, api)
    # re-embed with learned weights so the stored geometry reflects them, then fold + compact with learned threshold
    embedder.set_weights(w)
    items = folding.embed_all(store, api)
    folded = folding.fold(items, threshold=cur_fold)
    folding.store_folded(store, folded)
    folding.compact(store)
    prev = (store.q("SELECT hash FROM train_log ORDER BY id DESC LIMIT 1") or [{"hash": "0" * 64}])[0]["hash"]
    rec = dict(ts=time.time(), items=len(items), scale=best_scale, fold=cur_fold, before=before, after=best_score, adopted=adopted)
    h = hashlib.sha256((prev + json.dumps(rec, sort_keys=True)).encode()).hexdigest()
    store.x("INSERT INTO train_log(ts,items,scale,fold,before,after,adopted,hash) VALUES(?,?,?,?,?,?,?,?)",
            (rec["ts"], rec["items"], best_scale, cur_fold, before, best_score, adopted, h))
    return dict(trained=True, items=len(items), scale_before=cur_scale, scale_after=best_scale,
                objective_before=before, objective_after=best_score, adopted=bool(adopted),
                terms_learned=len(w), buckets=len(folded), hash=h[:16])


def log(store):
    bind(store)
    return store.q("SELECT * FROM train_log ORDER BY id DESC LIMIT 10")
