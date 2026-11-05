# SPDX-License-Identifier: Apache-2.0
"""The golden lattice: formal definitions of every matrix in Stretto, frontend and backend, cache and pattern.
A definition is (shape, axes, dtype, invariant, source). check() verifies a live matrix against its definition;
golden datasets under golden/ pin the exact numbers a definition must produce from a fixed input, and
tools/golden.py re-derives them — byte-identical regeneration is the test, so a silent numeric change anywhere
in the chain fails loudly. Meta model *weights* are not extractable and are never claimed: what is pinned from
the Meta API is its contract (message/usage/embedding shapes and the price matrix), which is all a client may know."""
import json
import os

DEFS = {
    # backend measurement
    "transitions": dict(shape="(P,P) counts + (P,P) avg-stay-s over labelled places P (<=12 by_app + destinations)",
                        axes=["src place", "dst place"], dtype="int counts / float seconds",
                        invariant="row sums = out-degree per place; every count >= 1; avg-stay > 0",
                        source="analyze.transitions(blocks)"),
    "by_category": dict(shape="(C) seconds per category, C in segment categories", axes=["category"], dtype="int seconds",
                        invariant="sum(by_category) == total_s + idle accounting of summary()", source="analyze.summary"),
    "attention_weights": dict(shape="(3) [W_FRAG=0.45, W_SHIFT=0.35, W_DIST=0.20]", axes=["fragmented", "shifts/h", "distraction"],
                              dtype="float", invariant="weights sum to 1.0; score in [0,100]", source="attention.measure"),
    "hours_profile": dict(shape="(24,3) focus/distraction/total seconds per hour", axes=["hour 0-23", "metric"], dtype="int seconds",
                          invariant="column sums == day focus/distraction/total within rounding", source="daycache.summarize"),
    "range_matrix": dict(shape="(D,6) per-day [focus, distraction, total, loss, hours24, simulated] for D in 1..90",
                         axes=["day", "metric"], dtype="mixed", invariant="dates strictly increasing, whole calendar days (DST-safe)", source="server.Api.range"),
    # cache / geometry
    "embeddings": dict(shape="(N,128) dense tensor, L2-normalised rows", axes=["item (task/challenge/finding/insight/conversation)", "dim 0-127"],
                       dtype="float6", invariant="every row norm == 1.0 (±1e-3); provider reported (meta|tensor)", source="embedder.dense + folding.embed_all"),
    "honeycomb_cells": dict(shape="axial hex lattice over embedding pairs, cell = round(v*scale) per axis pair",
                            axes=["axis pairs of the 9-dim day vector / 128-dim item vectors"], dtype="int coords",
                            invariant="neighbours differ by exactly 1 on one axis; route() visits rings outward, cap 512", source="honeycomb.cell/route"),
    "kv_cache": dict(shape="(<=1024) content-addressed entries sha256(prefix+payload)[:32]", axes=["key"], dtype="any JSON-able",
                     invariant="same input -> same key across processes; LRU order by last access", source="kvcache"),
    "daycache_fingerprint": dict(shape="(D) 'VERSION|rules_sig|n_events|max_id|sum_dur' per day", axes=["day"], dtype="string",
                                 invariant="any ingest/purge/rule change changes the fingerprint; stale summaries recompute, never serve", source="daycache.fingerprints"),
    # patterns / coaching
    "findings_tensor": dict(shape="(F, [kind, places<=6, minutes, runs]) measured findings", axes=["finding", "field"], dtype="mixed",
                            invariant="every finding cites real block indices; overlaps de-duplicated; sorted by seconds desc", source="analyze.findings"),
    "coach_ramp": dict(shape="(W, [share, reclaim_min]) W=horizon_weeks 1..12", axes=["week", "field"], dtype="float/int",
                       invariant="shares 0.25,0.35,0.50,0.65 (then 0.75); ×1.15 after a met week, ×0.90 after two missed", source="coach.plan"),
    "challenge_groups": dict(shape="(G, [kind, places, min/day, compounded7, compounded30, tier, xp])", axes=["group", "field"], dtype="mixed",
                             invariant="grouped by (kind, places[:4]); xp == minutes-per-day priced in time; sorted by compounded30 desc", source="challenges.group"),
    # frontend rendering (matrices the browser draws)
    "wave_packet": dict(shape="(T) focus-height samples + category note per 10-min bar over the day window", axes=["time bar"], dtype="float",
                        invariant="bar height ∝ focus seconds; dips mark switch density; live dot only for today", source="charts/wave.dayPacket"),
    "harmony_matrix": dict(shape="(T,C) stacked category seconds per 10-min bar, tonic D = focus", axes=["time bar", "category"], dtype="int seconds",
                           invariant="each bar sums to its measured 600s window (minus idle gaps)", source="charts/harmony.harmony"),
    "heatmap": dict(shape="(D,24) focus seconds per day-hour (Reports)", axes=["day", "hour"], dtype="int seconds",
                    invariant="row sums == range hours_focus totals", source="reports heatmap over Api.range"),
    "paths_field": dict(shape="(P) radial nodes sized by minutes + (P,P) edge widths by transition count", axes=["place", "place"], dtype="float",
                        invariant="node radius ∝ minutes; edge width ∝ count; highlight = one finding's places", source="charts/wave.field (backend evidence view)"),
    "atom_balance": dict(shape="(5) [onset, dwell, transition, idle_gap, recurrence] health + (5) learned Hedge weights",
                         axes=["atom"], dtype="float", invariant="health in [0,1]; weights sum to 1; leak = active_min x weighted ill-health", source="atoms.measure/hedge_update"),
    "pheromone": dict(shape="(P,P) pheromone over measured transitions, seeded 1.0, evaporates 12%/generation",
                      axes=["src place", "dst place"], dtype="float", invariant="deterministic for seed=7; strongest trail = optimized circuit", source="ants.simulate"),
    "dna_supercells": dict(shape="2x2 DNA matrix per supercell: [[first cell, count],[cohesion, variance]] + centroid",
                           axes=["supercell x", "supercell y"], dtype="mixed", invariant="centroid is the count-weighted mean of folded hex cells; variance is pooled spread (fold error, reported)", source="tricache.fold_lattice"),
    # Meta API contract (the only 'golden schema' a client may extract from the models)
    "meta_contract": dict(shape="chat: messages[] -> choices[0].message.content + usage{prompt,completion,reasoning,cached}; embeddings: input -> data[0].embedding[128+]",
                          axes=["field"], dtype="JSON", invariant="reply without usage is refused; non-Meta served model is refused; cost = price matrix x tokens",
                          source="meta.chat / embedder._meta against https://api.meta.ai/v1"),
    "price_matrix": dict(shape="(M, [input, cached, output] USD per 1M tokens)", axes=["model", "token kind"], dtype="float",
                         invariant="unknown model -> cost None, never invented", source="meta.PRICES (muse-spark-1.3: 1.25/0.15/4.25)"),
}

PRINCIPLES = {
    "transitions": "You lose it in pieces. Small pieces — so measure the pieces.",
    "findings_tensor": "Each one priced in minutes. Each one proven.",
    "attention_weights": "Not mood. Pattern. And pattern can be changed.",
    "coach_ramp": "Stretto does not choose your life. It holds you to the one you chose.",
    "embeddings": "Teach it your world. Your words. Your rules.",
    "honeycomb_cells": "Day after day, a shape appears.",
    "challenge_groups": "Hunt it down. Cut it out.",
    "meta_contract": "Every cost is written down. Nothing is hidden.",
    "wave_packet": "Live. Measured as it happens.",
}

GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "golden")


def check(name, value):
    """Verify a live value against its definition's checkable invariants. Returns (ok, problems[])."""
    problems = []
    if name == "attention_weights":
        if abs(sum(value) - 1.0) > 1e-9:
            problems.append("weights do not sum to 1.0")
    elif name == "embeddings":
        import math
        for i, row in enumerate(value):
            if len(row) != 128:
                problems.append(f"row {i} has {len(row)} dims, want 128"); break
            if abs(math.sqrt(sum(x * x for x in row)) - 1.0) > 1e-3:
                problems.append(f"row {i} not L2-normalised"); break
    elif name == "coach_ramp":
        shares = [r["share"] for r in value]
        if shares != sorted(shares):
            problems.append("ramp shares not non-decreasing")
    elif name == "price_matrix":
        for m, p in value.items():
            if not all(k in p for k in ("input", "cached", "output")):
                problems.append(f"{m} missing a price component")
    elif name == "transitions":
        for e in value:
            if e["count"] < 1 or e["avg_stay_s"] <= 0:
                problems.append("transition with count<1 or stay<=0"); break
    return (not problems, problems)


def validate_all(live):
    """live: {name: value} -> {name: (ok, problems)} for every name present."""
    return {n: check(n, v) for n, v in live.items() if n in DEFS}


def golden(name):
    with open(os.path.join(GOLDEN_DIR, name + ".json"), encoding="utf-8") as f:
        return json.load(f)
