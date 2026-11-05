# SPDX-License-Identifier: Apache-2.0
"""Folding and compaction over stored embeddings.
Folding: topic buckets whose centroids are near each other fold into one super-bucket (hierarchy without a model).
Compaction: near-duplicate embeddings of the same kind collapse to the newest, folded buckets are written to the
honeycomb as single artifacts, and the embeddings table is capped — old, unreferenced vectors go first."""
import hashlib
import json
import time

from . import honeycomb, topics


def bind(store):
    store.x("CREATE TABLE IF NOT EXISTS embeddings(kind TEXT, ref TEXT, vec TEXT, text TEXT, cell TEXT, ts REAL, PRIMARY KEY(kind, ref))")


def embed_all(store, api):
    """(Re)embed every recallable item — tasks, challenges, findings, insights, conversation turns — into storage."""
    bind(store)
    items = topics.collect(store, api)
    for it in items:
        cell = ",".join(str(x) for x in honeycomb.cell([it["vec"].get(k, 0.0) for k in sorted(it["vec"])][:9] or [0.0]))
        store.x("INSERT OR REPLACE INTO embeddings(kind,ref,vec,text,cell,ts) VALUES(?,?,?,?,?,?)",
                (it["kind"], it["ref"], json.dumps(it["vec"]), it["text"], cell, time.time()))
    return items


def load_items(store):
    bind(store)
    return [dict(kind=r["kind"], ref=r["ref"], text=r["text"], vec=json.loads(r["vec"]), extra={})
            for r in store.q("SELECT * FROM embeddings ORDER BY ts")]


def fold(items, threshold=0.30):
    """Buckets, then fold buckets whose centroids match: one super-bucket with children, label from both."""
    base = topics.buckets(items)
    cents = []
    for b in base:
        agg = {}
        for it in b["items"]:
            for k, x in topics.vector(it["text"]).items():
                agg[k] = agg.get(k, 0) + x
        cents.append(agg)
    parent = list(range(len(base)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for i in range(len(base)):
        for j in range(i + 1, len(base)):
            if topics.cosine(cents[i], cents[j]) >= threshold:
                parent[find(j)] = find(i)
    merged = {}
    for i, b in enumerate(base):
        merged.setdefault(find(i), []).append(b)
    out = []
    for root, kids in merged.items():
        if len(kids) == 1:
            out.append(dict(kids[0], folded=False, children=1))
        else:
            items_all = [it for k in kids for it in k["items"]]
            label = " + ".join(k["label"].split(" · ")[0] for k in kids[:3])
            out.append(dict(label=label, items=items_all, kinds=sorted({x["kind"] for x in items_all}), folded=True, children=len(kids)))
    out.sort(key=lambda b: -len(b["items"]))
    return out


def compact(store, max_embeddings=500):
    """Collapse near-duplicates (same kind, cosine >= 0.92: keep newest), then cap the table. Returns counts."""
    bind(store)
    rows = store.q("SELECT kind, ref, vec, ts FROM embeddings ORDER BY ts DESC")
    seen, dropped = [], 0
    for r in rows:
        v = json.loads(r["vec"])
        if any(r["kind"] == s[0] and topics.cosine(v, s[1]) >= 0.92 for s in seen):
            store.x("DELETE FROM embeddings WHERE kind=? AND ref=?", (r["kind"], r["ref"])); dropped += 1
        else:
            seen.append((r["kind"], v))
    left = store.q("SELECT kind, ref FROM embeddings ORDER BY ts ASC")
    capped = 0
    for r in left[: max(0, len(left) - max_embeddings)]:
        store.x("DELETE FROM embeddings WHERE kind=? AND ref=?", (r["kind"], r["ref"])); capped += 1
    return dict(duplicates_dropped=dropped, capped=capped, kept=len(store.q("SELECT kind FROM embeddings")))


def store_folded(store, folded):
    """Write each folded bucket to the honeycomb as one artifact, keyed by its label hash, with its centroid vector."""
    n = 0
    for b in folded:
        agg = {}
        for it in b["items"]:
            for k, x in topics.vector(it["text"]).items():
                agg[k] = agg.get(k, 0) + x
        vec = [agg.get(k, 0.0) for k in sorted(agg)][:9]
        key = "bucket:" + hashlib.sha256(b["label"].encode()).hexdigest()[:16]
        honeycomb.put_raw(store, key, vec, b["label"], dict(label=b["label"], kinds=b["kinds"], refs=[[x["kind"], x["ref"]] for x in b["items"]], folded=b["folded"]))
        n += 1
    return n
