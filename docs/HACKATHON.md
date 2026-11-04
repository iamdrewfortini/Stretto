# Hackathon notes (Meta Global AI Developer Hackathon)

**Submission:** Indie Developer track · Push the Frontier. One track, one problem statement, as the Official Rules require. The reasoning behind the project is in [STORY.md](STORY.md); licensing and rules are in [LICENSE-AND-TERMS.md](LICENSE-AND-TERMS.md).

## Meta models and how they are used

| Role | Model | Route | State |
|---|---|---|---|
| Voice core (the one agent the person talks to) | `muse-spark-1.3`, fallback `muse-spark-1.2` | local runtime gateway, role `voice.core`, tool calling over the humanflow ledger | **live**: spoken turns call the ledger tools against the Meta Model API |
| Planner / orchestrator agent | `muse-wonder-1.0` | gateway, role `agent.planner`; job pipelines on the event bus | **live**: proposes task order with a rationale |
| Background agents (optimizer, summarizer) | `muse-spark-1.3-contributor` | gateway, role `agent.background`, spend-capped | live, throttled, never speak to the person |
| Speech in | `muse-voice-transcribe-1.0` | realtime websocket bridge in the runtime (endpointing mode) | **live**: streaming partial and final transcripts |
| Speech out | none | browser `speechSynthesis`, on device | Meta offers no text-to-speech; said openly |
| Vision (screen, camera, stream, glasses frames) | `muse-spark-*`, `sam-3.1` | gateway | routing interface only |
| Image | `muse-image-1.0` | gateway | catalogued only |
| Open weights / fine-tuning | `muse-glimmer-30b` | on-cluster server | **not deployed**; fine-tuning is a validated job spec |

The runtime refuses any model that is not an allowed Meta model [C:meta-only-policy]. All model traffic goes through our own local-only runtime gateway (`packages/runtime`), which replaced the Bifrost gateway: it listens on loopback only, calls only `api.meta.ai`, and logs every call with model, latency and cost. Model ids, endpoints, prices and role bindings live in `docs/spec/models.registry.json`. Meta's Model API has no embeddings route that we could find, so the embedding router answers `NO_SIGNAL` until a Meta embedder is deployed and evaluated.

## Development tooling disclosure

Most of this code was written with an AI coding assistant (Claude Code), directed and reviewed by the author. On the final day, three parts of the runtime were written headless by **Meta Muse Code** (`muse exec`, one agent per git worktree, each with its own files and a failing-able test check), then reviewed and merged: the realtime voice bridge and mic page (`muse-spark-1.3`), the agent pipelines (`muse-wonder-1.0`), and the live dashboard (`muse-spark-1.3`). Their commits are marked `Co-Authored-By: Muse Code`. Meta models are also the *runtime* of the system. Say both in the submission.

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

No embeddings: the Meta Model API has no embeddings route, so retrieval stays local and lexical until a Meta embedder is served. 
No recorded people, no verified wearable SDK adapter, no deployed local model, no energy measurement, no change applied to a real cluster by the tests.
