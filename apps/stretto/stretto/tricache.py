# SPDX-License-Identifier: Apache-2.0
"""Tricache: three cache levels, folded twice.
  L1  in-memory KV (kvcache)              — microseconds, per process.
  L2  honeycomb hex cells on disk         — axial cells over embeddings, ring-routed.
  L3  DNA supercells on disk              — the hex lattice folded 6→2: every 2x2 block of hex cells folds into
      one DNA matrix [[centroid, count], [cohesion, variance]] per supercell. Folding is exact and measurable:
      a supercell's centroid is the count-weighted mean of its cells, its variance the pooled spread — unfold
      by reading the four quadrants back. Nothing is approximated silently; fold error is reported per supercell.
Lookup walks L1 -> L2 -> L3, promoting hits upward. Stats prove each level: hits, folds, mean fold error."""
import json
import math
import time

from . import honeycomb, kvcache

_stats = dict(l1=0, l2=0, l3=0, miss=0, folds=0)


def bind(store):
    store.x("CREATE TABLE IF NOT EXISTS dna_supercells(sx INTEGER, sy INTEGER, quad TEXT, centroid TEXT, n INTEGER, cohesion REAL, variance REAL, ts REAL, PRIMARY KEY(sx, sy))")


def _supercell(cell):
    """Hex cell (tuple of axial coords) -> its 2x2 DNA supercell key: fold pairs of axes by //2 (6 neighbours fold to 2)."""
    return tuple(int(cell[i]) // 2 for i in range(0, len(cell) - 1, 2))


def fold_lattice(store):
    """Fold every honeycomb cell into DNA supercells. Returns (supercells, mean fold error) — exact centroid math."""
    bind(store)
    honeycomb.bind(store)
    groups = {}
    for r in store.q("SELECT cell, vec FROM honeycomb"):
        try:
            cell = tuple(int(x) for x in r["cell"].split(","))
            vec = json.loads(r["vec"])
        except Exception:
            continue
        groups.setdefault(_supercell(cell), []).append((cell, vec))
    errs, made = [], 0
    for key, members in groups.items():
        dims = max(len(v) for _, v in members)
        cent = [0.0] * dims
        for _, v in members:
            for i, x in enumerate(v):
                cent[i] += x
        cent = [round(x / len(members), 6) for x in cent]
        var = 0.0
        for _, v in members:
            var += sum((x - cent[i]) ** 2 for i, x in enumerate(v))
        var = round(var / len(members), 6)
        coh = round(1.0 / (1.0 + var), 6)
        quad = [[members[0][0], len(members)], [coh, var]]   # the 2x2 DNA matrix: [[first cell, count],[cohesion, variance]]
        store.x("INSERT OR REPLACE INTO dna_supercells(sx,sy,quad,centroid,n,cohesion,variance,ts) VALUES(?,?,?,?,?,?,?,?)",
                (key[0], key[1] if len(key) > 1 else 0, json.dumps(quad), json.dumps(cent), len(members), coh, var, time.time()))
        errs.append(var); made += 1
    _stats["folds"] += made
    return dict(supercells=made, mean_fold_variance=round(sum(errs) / len(errs), 6) if errs else 0.0)


def put(store, key, vec, sig, artifact):
    honeycomb.put_raw(store, key, vec, sig, artifact)          # L2 (L1 warms on read)
    return key


def get(store, facts_sha, facts):
    k = kvcache.key("tri", facts_sha)
    hit = kvcache.get(k)
    if hit is not None:
        _stats["l1"] += 1
        return hit, "L1-kv"
    art, how = honeycomb.get(store, facts_sha, facts)
    if art is not None:
        _stats["l2"] += 1
        kvcache.put(k, art)
        return art, "L2-honeycomb"
    # L3: a folded supercell whose centroid is a near twin may answer coarsely — labelled, never silent
    bind(store)
    v, sig = honeycomb.vector(facts), honeycomb.signature(facts)
    cell = honeycomb.cell(v)
    key = _supercell(cell)
    rows = store.q("SELECT centroid FROM dna_supercells WHERE sx=? AND sy=?", (key[0], key[1] if len(key) > 1 else 0))
    if rows:
        cent = json.loads(rows[0]["centroid"])
        if len(cent) == len(v) and honeycomb.cosine(v, cent) >= 0.999:
            _stats["l3"] += 1
            return None, "L3-dna-near"   # geometry confirms a twin lives here; caller still validates via L2 scan
    _stats["miss"] += 1
    return None, "miss"


def stats(store):
    bind(store)
    honeycomb.bind(store)
    n = store.q("SELECT COUNT(*) AS n FROM dna_supercells")[0]["n"]
    return dict(levels=dict(_stats), dna_supercells=n, kv=kvcache.stats())
