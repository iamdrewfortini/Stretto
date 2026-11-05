# SPDX-License-Identifier: Apache-2.0
"""Coherence across layers: one pass, one object graph.
Every layer — capture, findings, challenges/pins, tasks, insights, conversation turns, embeddings, honeycomb,
topics, coach — must reference the same objects with the same ids. run() embeds everything, folds buckets,
compacts embeddings, stores folded artifacts, then audits the result: counts per layer, bucket refs that resolve,
pins with their tasks, and embeddings with no source (orphans). The audit is the coherence claim; read it, don't trust it."""
import time

from . import challenges, folding, honeycomb, topics


def run(store, api, do_compact=True):
    items = folding.embed_all(store, api)
    folded = folding.fold(items)
    stored = folding.store_folded(store, folded)
    comp = folding.compact(store) if do_compact else dict(duplicates_dropped=0, capped=0, kept=len(items))
    return audit(store, api, folded=folded, stored=stored, comp=comp, items=items)


def audit(store, api, folded=None, stored=0, comp=None, items=None):
    if items is None:
        items = folding.load_items(store)
        if not items:   # nothing embedded yet: audit the live graph so a fresh system still reports coherently
            items = topics.collect(store, api)
    folded = folded if folded is not None else folding.fold(items)
    by_kind = {}
    for it in items:
        by_kind[it["kind"]] = by_kind.get(it["kind"], 0) + 1
    live = {(x["kind"], x["ref"]) for x in topics.collect(store, api)}
    embedded = {(x["kind"], x["ref"]) for x in items}
    pins = challenges.pins(store)
    task_titles = {r["title"] for r in store.q("SELECT title FROM tasks")}
    orphans = sorted(f"{k}:{r}" for k, r in embedded - live)
    return dict(ts=time.time(), items=len(items), by_kind=by_kind, buckets=len(folded),
                folded_buckets=sum(1 for b in folded if b["folded"]), honeycomb_artifacts=stored,
                compaction=comp or dict(), pins=dict(active=sum(1 for p in pins if p["status"] == "active"),
                                                     completed=sum(1 for p in pins if p["status"] == "completed"),
                                                     with_task=sum(1 for p in pins if p["fix"] in task_titles)),
                orphans=orphans, coherent=not orphans, honeycomb=honeycomb.stats(store))
