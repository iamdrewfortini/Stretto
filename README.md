# Humanflow

**A private, voice-first time and focus assistant built on Meta's Muse models.** Say what you are doing; Humanflow logs it, times it, plans your tasks and tells you, with numbers from your own ledger, where your day went.

[![ci](https://github.com/iamdrewfortini/humanflow/actions/workflows/ci.yml/badge.svg)](https://github.com/iamdrewfortini/humanflow/actions/workflows/ci.yml) [![license: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Meta Global AI Developer Hackathon (Cerebral Valley × Meta) · **Indie Developer** track · problem statement **Build for Your World**

## Why

I run a studio, consult as a full-stack IT engineer, and operate my own three-server cluster with fleets of agents on top. Every one of those machines is measured. I can prove what my storage did at three in the morning. When I built a way to measure how far my systems were from doing what I actually wanted, almost all of the distance turned out to be me: about 95% of it was intent the machines could not see [C:intent-dominates-D]. My systems had a record. My day did not.

My time leaks the way everyone's does. Switching between clients and systems. Re-finding what I already knew. Waiting on people and builds. Reconstructing what I did, and for whom, when it is time to bill. It costs me billable hours I cannot account for, work that spills into nights and weekends, days that went to the wrong thing, and a quiet trust gap: I can prove what my machines did, but not what I did.

That is the small version. The bigger one I see with every owner, technician and team I work with: **people cannot even picture how much time they are losing.** There is a learned helplessness around technology. People have tried everything they know, found what works well enough, and decided this is just how it has to be done. So the truth about their work is set by how it feels, not by what is measured. Nobody can reason about a leak they cannot see, let alone what ten minutes a day compounds into: about a full work week every year, and most of a working year over a career.

Humanflow is my answer, built for my own day first. It costs no attention to use: you say what you are doing, out loud, while you do it. It turns that into an honest, owner-only record of where your time went, and it answers in numbers from your own ledger, not in feelings.

**Today** it logs time by voice, runs timers and tasks, tells you where the day went, plans your work with Muse Wonder, and proposes one change at a time with the number behind it.

**Where it is going:** real-time micro-signals that show each leak as it happens and what it compounds to over a week, a month, a year and a decade; small workflow changes ranked by the most time won back for the least time and cost to adopt; your trajectory forecast forward so you can see the future you are choosing; and a game of it, where you drive your leak score down and level up as time comes back. Time is money, and people deserve to see how it compounds.

It is for me first, then for the people I build for: solo owners who wear every hat, consultants who bill across many clients, and technicians whose hands-on work no tool measures at all.

## What it does

- **Talk to it.** "I was in meetings for forty minutes." "Start a focus timer, I'm writing the demo script." "Add a task: record the demo video." "How's my day?" Each request becomes a tool call against your personal ledger, and the answer is spoken back.
- **Plans with Muse Wonder.** When tasks pile up, a planner agent on `muse-wonder-1.0` proposes an order with a one-line rationale. It proposes; you decide.
- **Watches the pattern, not the person.** Background agents look at switches, waiting and failed searches and propose one concrete change at a time, each with the number behind it.
- **Live dashboard.** Minutes by activity, the running timer, tasks, every model call with its latency and cost, and the agents' proposals, all from one event stream.
- **Desktop sensors (in progress).** A consent-gated sensor agent for Linux and macOS that turns focus-window and idle time into timeline entries; see `packages/sensors` when it lands.

## Meta models

| Model | Where Humanflow uses it | Status |
|---|---|---|
| `muse-spark-1.3` | The voice core: one agent you talk to, with tool calling over the ledger | **live** |
| `muse-spark-1.3-contributor` | Background agents (optimizer, summarizer), spend-capped | **live** |
| `muse-wonder-1.0` | Planner and orchestrator agent | **live** |
| `muse-voice-transcribe-1.0` | Realtime speech-in over Meta's streaming websocket | **live** |
| `muse-image-1.0`, `sam-3.1` | In the model registry and router; not used in the demo flow | catalogued |
| Muse Glimmer (open weights) | Evaluated for on-device answers. Meta's docs list its smallest quantized file at 16.8 GB with a 24 GB GPU recommended, so it is not deployed on the demo hardware | evaluated, not deployed |
| Muse Spark Open (open weights) | Multi-GPU class; out of scope for a personal desktop | not deployed |
| **Muse Code** | Wrote three runtime parts headless (`muse exec`, one agent per git worktree): the realtime voice bridge, the agent pipelines and the live dashboard | used to build |

Every model id, endpoint, price, rate limit and role binding lives in one file, [`docs/spec/models.registry.json`](docs/spec/models.registry.json). Meta offers no text-to-speech and no embeddings endpoint, so replies are spoken by the browser on your device and retrieval stays local.

## Speed and cost

- Common commands (greetings, logging time, timers, tasks, "how's my day") are understood and answered locally, with no model call and no cost. The fast path stays under a 100 ms budget at p95, checked on every CI run [C:humanflow-fast-path-budget].
- Recorded live on 2026-11-04 over Meta's realtime transcription: final transcript to spoken reply in 43 to 45 ms for those commands; open questions go to Muse Spark and take a few seconds, of which the network round trip alone was 553 ms. See [`docs/evidence/humanflow-live-2026-11-04.json`](docs/evidence/humanflow-live-2026-11-04.json). <!-- no-claim -->
- Background agents run on the contributor tier and pause at a spend cap you set in `.env`.

## Privacy and boundaries

- **Local only.** All model traffic goes through one runtime gateway that listens on loopback, answers local clients only, calls only `api.meta.ai` over HTTPS and serves only models in the Meta registry [C:humanflow-gateway-boundary]. Your API key lives in a `0600` `.env` and nowhere else; `scripts/env_check.py` proves it.
- **Yours alone.** The ledger belongs to one person. Group views, if you ever share them, are k-anonymous with differential-privacy noise (`packages/humanflow`).
- **Consent first.** Sensors are default-deny per source; no raw audio, screen pixels or keystroke content is ever stored.
- **What Humanflow is not.** It does not give medical, mental-health or wellbeing advice, and it does not profile personality. Its suggestions are about how time is spent, each backed by your own measurements.

## Quick start (Linux or macOS)

```bash
git clone https://github.com/iamdrewfortini/humanflow && cd humanflow
python3 -m pip install websockets==15.0.1     # the only third-party dependency of the runtime
cp .env.example .env && chmod 600 .env         # then set MODEL_API_KEY (Meta Model API dashboard)
python3 scripts/env_check.py                   # proves the env file is private and the boundary is local
scripts/gateway.sh start                       # gateway, voice bridge and agents in one process
# open http://127.0.0.1:8787/ (voice) and http://127.0.0.1:8787/dashboard
```

Running the gateway on another machine? Forward both ports and use the same URLs: `ssh -N -L 8787:127.0.0.1:8787 -L 8788:127.0.0.1:8788 <host>`. Browsers treat `127.0.0.1` as a secure origin, so the microphone works.

Tests: `python3 scripts/run_all_tests.py` · claims: `python3 scripts/verify_claims.py` · design: [`docs/spec/VOICE-RUNTIME-SPEC.md`](docs/spec/VOICE-RUNTIME-SPEC.md).

## How it fits together

Browser mic → voice bridge → Meta realtime transcription → **fast path** (local) or **voice core** (Muse Spark with tools) → ledger tools → event bus → dashboard and background agents (Muse Wonder planner, contributor-tier optimizer and summarizer). Every step is one event in an append-only log, so state rebuilds exactly from the log.

## Built with Meta

Docs: [overview](https://dev.meta.ai/docs/overview) · [quickstart](https://dev.meta.ai/docs/quickstart) · [model list](https://dev.meta.ai/docs/models). Cookbooks: [Meta Model API cookbook](https://github.com/meta-models/meta-model-cookbook) ([API fundamentals](https://github.com/meta-models/meta-model-cookbook/tree/main/01_api_fundamentals), [Muse Code recipes](https://github.com/meta-models/meta-model-cookbook/tree/main/04_muse_code)) · [OSS model cookbook](https://github.com/meta-models/meta-oss-cookbook). Models: [Muse Spark](https://dev.meta.ai/models/muse-spark) · [Muse Wonder](https://dev.meta.ai/models/muse-wonder) · [Muse Voice Transcribe](https://dev.meta.ai/models/muse-voice-transcribe) · [Muse Glimmer](https://dev.meta.ai/models/muse-glimmer) · [Muse Code](https://dev.meta.ai/lp/muse-code).

How it was built, honestly: most of the code was written with an AI coding assistant (Claude Code) directed and reviewed by the author; three runtime parts were written by Meta Muse Code and are marked in the git history. Details in [`docs/HACKATHON.md`](docs/HACKATHON.md).

## Contributing

Issues and pull requests are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md), the [Code of Conduct](CODE_OF_CONDUCT.md) and [SECURITY.md](SECURITY.md). Licensed under [Apache-2.0](LICENSE).

---

## Under the hood: the Meta Coherence Hive

Humanflow runs on a larger system built during the event, kept here because the voice core reuses its consent, redaction, routing and ledger packages.

A system that tells you **how far you are from coherence**, in numbers you can check, and then helps each small agent (and each person) move the right way. It has two tool sets, each coherent alone: one for **infrastructure**, one for **human process** (consent first, every person owning their own data). They meet in a mirror that compares where each side is paying attention. Every learned model it uses is a **Meta model**, reached through one gateway.

![architecture](docs/figures/architecture.svg)

### The problem, as one number

A person who has chosen a direction cannot see their own location. Here that location is a number: the distance from coherence **D**. For one recorded three-node cluster it is at least **0.2297**, and it is a lower bound because three of its five axes have no instrument yet [C:distance-lower-bound]. About 95% of that distance is *intent*, the system not knowing what its human wants, not the machines [C:intent-dominates-D]. See [docs/STORY.md](docs/STORY.md) for the whole story and [docs/figures/](docs/FIGURES.md) for every figure.

![distance from coherence](docs/figures/distance-from-coherence.svg)

### Every claim is a check

Each number in these docs carries a tag like [C:release-gates] that names a check which can fail. `docs/CLAIMS.md` lists them all with their evidence; `scripts/docs_lint.py` fails the build if a number appears without a tag.

```
python scripts/verify_claims.py --require-all
python scripts/docs_lint.py
python scripts/make_figures.py --check
```

### Install

```
tar xzf metacoh-0.1.0-linux-x86_64.tar.gz && cd metacoh-0.1.0
installer/install.sh --user && ~/.local/share/metacoh/bin/metacoh doctor
```

Offline, hash-pinned, rollback-safe, with an uninstall receipt: see [docs/PACKAGING.md](docs/PACKAGING.md). From source: `python scripts/run_all_tests.py`.

### What is in it

| Package | What it does |
|---|---|
| `wf13d` | the WF-13D bridge arithmetic as one 18-bit word, plus a binary lookup table any language can embed [C:wf13d-exhaustive] |
| `coherence` | D and its gradient, the attention mirror and 4-cube, attention and signal tracking, Langton's-ant escape direction (run until locked), ant-colony search, cache-to-cache gossip |
| `metarouter` | Meta-only policy; routing by time to a verified result, including queueing |
| `harness` | staged rollout with a control group, signed outer boundary, provenance, question stream, agent DAG validator |
| `telemetry`, `adapters` | the telemetry store and the only environment-specific code (a read-only inventory sampler) |
| `cells` | a micro cell: WF-13D gating, policy, routing, provenance |
| `perception`, `humanflow`, `assistant`, `finetune` | consent-first capture, owner-only time ledger with private roll-ups, a focus-respecting assistant, a consent-gated fine-tuning gate |
| `handoff` | an expert's work as a verified procedure graph: find gaps, ask one question each, guide a trainee; step scoring with its threshold curve and its blind spots ([docs/SCORING.md](docs/SCORING.md)) |
| `resonate` | present a measurement in the form this person understands; a tone whose beat vanishes when both sides agree; the 88-key frequency layout and the polyrhythm clock ([docs/SOUND.md](docs/SOUND.md)) |
| `metacoh` | umbrella package and the `metacoh doctor` self-check |
| `crates/` | Rust ports of the hot paths with a C ABI, checked bit for bit against Python [C:rust-conformance] |

Packages are isolated: each lists the siblings it may import in `DEPS`, and the build fails on anything else [C:release-gates].

### Privacy in one paragraph

Capture is off until a person turns it on for a named source and purpose, for a limited time, and they can revoke it mid-stream [C:consent-default-deny]. Raw frames are described, redacted and dropped; the event type has no field for pixels [C:no-raw-media-stored]. A person's ledger is readable only by that person [C:owner-only-ledger]; group views need at least five contributors and add noise [C:rollup-privacy]. Read [docs/PRIVACY.md](docs/PRIVACY.md), including what is **not** built yet.

### Honest status

Mechanisms are implemented and checked on synthetic data. No real person has been recorded, no live Meta model call is made by the tests, no wearable SDK adapter exists, and nothing here changes a real cluster. The Handoff success criterion (real recorded jobs) is not yet measured; see the table in the story.

### Licensing and the hackathon

Apache-2.0. See [docs/LICENSE-AND-TERMS.md](docs/LICENSE-AND-TERMS.md) for how the license fits the Official Rules, and [docs/HACKATHON.md](docs/HACKATHON.md) for the models used and a per-component authorship table.
