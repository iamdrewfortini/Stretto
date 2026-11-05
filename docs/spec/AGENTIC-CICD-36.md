# SPDX-License-Identifier: Apache-2.0
# Agentic CI/CD: 36 cells, 9 stages, 3 graph loops deep

Implements [#21](https://github.com/iamdrewfortini/Stretto/issues/21), part of epic [#6](https://github.com/iamdrewfortini/Stretto/issues/6).

## Matrix math (exact)

| Quantity | Formula | Value |
|---|---|---|
| Stages | S | 9 |
| Cells per stage | C | 4 |
| Total cells | N = S x C | 36 |
| Loop depth | L (capped) | 3 |
| Stage-passes | S x L | 27 |
| Max cell-passes | N x L | 108 |
| Parallel width | cells per stage-pass | 4 |
| Sequential depth | stage-passes on critical path | 27 |

Actions wiring mirrors this: `agentic-cicd.yml` runs a `pilot` job (the
orchestrator, loops 1..3 in order) plus a `shards` matrix of
`stage: [1..9] x loop: [1..3]` = 27 shard jobs, 4 cells each. `fail-fast`
is off so no cell signal hides another.

## Roster (C01..C36)

| Stage | Cells |
|---|---|
| S1 ingest-diff | C01 diff-scope, C02 issue-link, C03 claim-ids, C04 secret-name-only |
| S2 static-gates | C05 release-check, C06 docs-lint, C07 spdx-license, C08 dependency-pins |
| S3 tests | C09 package-tests, C10 stretto-tests, C11 installer-dryrun, C12 state-coverage |
| S4 claims-metrics | C13 verify-claims, C14 figures-current, C15 fast-path-budget, C16 metrics-repro |
| S5 security-boundary | C17 public-scan, C18 egress-allowlist, C19 loopback-bind, C20 mcp-write-guard |
| S6 calendar-mcp | C21 ics-roundtrip, C22 caldav-fixtures, C23 tzid-dst, C24 mcp-read-tools |
| S7 ux-smoke | C25 pages-render, C26 talk-roundtrip, C27 timer-task, C28 offline-states |
| S8 routing-mapping | C29 finding-issue-map, C30 duplicate-detect, C31 owner-area-map, C32 risk-map |
| S9 weighting-verdict | C33 risk-score, C34 cost-score, C35 confidence-score, C36 final-verdict |

## Routing, weighting, loops

- Weight per cell-pass: `w = (risk x confidence) / (1 + cost)`, each in [0,1].
- Routing into the next loop: every `fail`, plus `pass` cells with `w >= 0.20`.
  `skip` is never routed and never counted as proof.
- Loop 1 runs all 36 cells. Loops 2..3 run only routed cells. The run stops
  early on convergence (identical routing with no failures) and never
  exceeds 3 loops. Termination is therefore guaranteed: at most 108 passes.
- Cells never write source. Outputs are `agentic-summary.json` / `.md`
  artifacts only. Code changes happen only through pull requests.

## Key handling (BYOK)

The Meta key is supplied to Actions as a repo secret named `META_API_KEY`
(maintainer adds it in repo Settings; never in git, logs, or chat) and to
local runs only via the `0600` `.env` through the single Humanflow gateway.
`scripts/agentic_cells.py` reads only the key's *presence* by env-var name.
Model calls stay off unless `--allow-meta` is passed, and then only to
`api.meta.ai`, the registry egress allowlist. Without a key, model-backed
cells report `skip` honestly.

## Running it

```bash
python3 scripts/agentic_cells.py --loops 3
python3 -m unittest tests.test_agentic_cells -v   # from repo root with scripts on path, see test header
```
