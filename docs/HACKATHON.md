# Hackathon notes (Meta Global AI Developer Hackathon)

**Submission:** Indie Developer track · Push the Frontier. One track, one problem statement, as the Official Rules require. The reasoning behind the project is in [STORY.md](STORY.md); licensing and rules are in [LICENSE-AND-TERMS.md](LICENSE-AND-TERMS.md).

## Meta models and how they are used

| Role | Model | Route | State |
|---|---|---|---|
| Planner / coder / general | `muse-wonder-1.0`, `muse-spark-1.2`, `muse-spark-1.3` | production through the gateway; Muse subscription for interactive use and testing only | catalogued; **no live call is made by this repository's tests** |
| Vision (screen, camera, stream, glasses frames) | `muse-spark-*`, `sam-3.1` | gateway | routing interface only |
| Voice | `muse-voice-transcribe-1.0` | gateway | consent + redaction path verified with stubs |
| Image | `muse-image-1.0` | gateway | catalogued only |
| Open weights / fine-tuning | `muse-glimmer-30b` | on-cluster server | **not deployed**; fine-tuning is a validated job spec |

The runtime refuses any model that is not an allowed Meta model [C:meta-only-policy]. Meta's Model API has no embeddings route that we could find, so the embedding router answers `NO_SIGNAL` until a Meta embedder is deployed and evaluated.

## Development tooling disclosure

Most of this code was written with an AI coding assistant (Claude Code), directed and reviewed by the author. It was **not** written with Meta's Muse Code. Meta models are the *runtime* of the system, not the authoring tool. Say so in the submission.

## New-work disclosure (read before judging)

| Authored | Components |
|---|---|
| **2026-10-26** (kickoff day, before the building period) | `harness` (rollout engine, optimizer, boundary, signing, pattern, forecast, sampling, qms, questions), `telemetry`, the read-only sampler |
| **2026-10-27 onward** | everything else: `wf13d`, `coherence` (including the mirror), `metarouter`, `harness.organism`, `cells`, `perception`, `humanflow`, `assistant`, `finetune`, `handoff`, `resonate`, `metacoh`, `crates/*`, packaging, claims register, figures |

The first group predates the building period by one day. The git history carries it as a separate, earlier commit. Present it as pre-existing groundwork or leave it out of the demo.

## What a judge can run

```
python scripts/verify_claims.py --require-all   # every claim is a check; none may be skipped
python scripts/docs_lint.py                     # no number in the docs without a claim behind it
python scripts/make_figures.py --check          # figures are regenerated from the code
python scripts/release_check.py                 # licensing, isolation, public-safety
metacoh doctor                                  # after installing the bundle
```

## Demo plan (three minutes, only what was built during the event)

1. The problem: a person cannot see their own location. Show `figures/distance-from-coherence.svg` and the one number, with its unmeasured axes named.
2. Handoff: delete a step from a procedure and watch the checker ask the one question that closes the graph.
3. The mirror: two attention distributions, their coherence, and the tone whose beat vanishes when they agree.
4. Trust: consent default-deny, a mid-stream revoke, and the claims register passing live.

Use only your own recordings or people who have given written consent: the Rules let Organizers use recordings of participants.

## Not in this submission

No recorded people, no verified wearable SDK adapter, no deployed local model, no energy measurement, no change applied to a real cluster by the tests.
