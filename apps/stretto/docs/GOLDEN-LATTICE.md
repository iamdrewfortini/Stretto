# The golden lattice

Every matrix Stretto calculates with is defined once in `stretto/lattice.py` (`DEFS`): shape, axes, dtype,
invariant, and the module that produces it. Frontend and backend, cache and pattern — one registry, served
live at `GET /api/lattice` with the checkable invariants run against today's data.

| Layer | Matrices |
|---|---|
| Backend measurement | `transitions` (P×P counts + avg-stay), `by_category`, `attention_weights` (0.45/0.35/0.20, sums to 1), `hours_profile` (24×3), `range_matrix` (D×6, DST-safe whole days) |
| Cache / geometry | `embeddings` (N×128, L2 rows), `honeycomb_cells` (axial hex, ring route cap 512), `kv_cache` (≤1024 content-addressed), `daycache_fingerprint` (any change recomputes, never serves stale) |
| Patterns / coaching | `findings_tensor`, `coach_ramp` (0.25→0.65, ×1.15 met / ×0.90 missed), `challenge_groups` (xp priced in minutes) |
| Frontend rendering | `wave_packet`, `harmony_matrix` (10-min bars), `heatmap` (D×24), `paths_field` (evidence view) |
| Meta API contract | `meta_contract` (usage required, non-Meta refused), `price_matrix` (unknown model → cost None, never invented) |

## Golden datasets

`stretto/golden/*.json` pin the exact output of the real modules on one fixed synthetic day: transitions,
findings, the 9-dim day vector + its hex cell + signature, a 128-dim embedding (first 8 values), grouped
challenges, the coach ramp, and a Markov next-place prediction.

```sh
python3 tools/golden.py          # re-derive and rewrite
python3 tools/golden.py --check  # fail if any number drifted (runs in the test suite)
```

Byte-identical regeneration is the contract: change any constant in the chain and a golden file goes stale
in review, where the diff is the discussion.

## Prediction and improvement

`stretto/predict.py` reads the lattice in real time: Markov next-place from the transition matrix, a
next-3-hours focus forecast from the hours profile, and a reclaim ETA from challenges × ramp. Estimates are
labelled as estimated and contain only numbers the matrices contain. `stretto/selftrain.py` then improves
the geometry over time (term weights, honeycomb scale, fold threshold — adopted only on measured gain), and
`GET /api/coherence` audits every layer, lattice included, in one pass.

## What "extracted from Meta" honestly means

Model weights are not extractable from the Meta Model API and are never claimed here. What the lattice pins
from Meta is the client-visible contract — message, usage (prompt/completion/reasoning/cached tokens) and
embedding shapes, plus the price matrix — verified on every call by `meta.py` (a reply without usage, or
served by a non-Meta model, is refused). Distilled cookbook patterns live in `COOKBOOK-MAP.md`; their
re-derivable shapes are the pipelines in `honeycomb`, `folding`, `kvcache`, `embedder` and `predict`.
