# Development swarms through Bifrost

Derived from Drew's 2026-10-28 request to execute and delegate Meta API pipelines and fast feature-development swarms, governed by `~/DEV/handoff/docs/COHERENT-RUBRIC.md`.
Fate: SHARED within the hackathon; unrelated workstreams ISOLATED.

The existing Bifrost gateway owns provider credentials, model calls and provider-side routing. This repository adds a thin client and a development workflow around it; it does not add another gateway or model service.

## Flow and evidence

`plan → {implementation, validation} → review` is the included example. A completion event unlocks dependent work; there is no timed polling. Tasks declare explicit ownership, dependencies, bounded concurrency, capped attempts and the current rubric hash. Overlapping ownership between tasks that could run together is rejected. A failed prerequisite blocks its descendants. Every checked output includes text artifacts, evidence pointers and rubric acknowledgement; the report records artifact hashes and a chained event history.

The included fixtures are deterministic offline proposals, never model-produced code or proof of Handoff's product bar. `CHECKED` means the artifact contract and supplied acceptance callback passed. The command requires named per-artifact static acceptance rules: nonempty text, required literals, Python syntax parsing and JSON object keys. Unknown rules and malformed artifacts fail closed. These checks do not execute generated tests or prove functional correctness. Code review, independent tests in the appropriate execution environment, and owner approval at irreversible boundaries remain required.

## Commands

From the repository root, with the canonical rubric available:

```sh
python3 scripts/development_swarm.py examples/development-swarm/feature-flow.json \
  --rubric ~/DEV/handoff/docs/COHERENT-RUBRIC.md

python3 scripts/development_swarm.py examples/development-swarm/feature-flow.json \
  --rubric ~/DEV/handoff/docs/COHERENT-RUBRIC.md \
  --mode offline-dry-run --output /path/to/new-review-directory
```

The default only plans. Execution requires a new output directory; `report.json` contains the proposed artifacts. Nothing is applied to the checkout and no generated command is executed. The script's callbacks are trusted host code; ownership validation on returned artifacts is not an OS sandbox.

## Gateway contract and live gate

The client takes a configured HTTPS base URL, sends chat completions with `x-bf-vk` and `x-bf-disable-content-logging: true`, and reads the key from a named environment variable at call time. Secrets are absent from flow files and previews. Redirects and inherited HTTP proxies are refused; TLS verification stays enabled. HTTP loopback is available only by explicit transport-test configuration. Non-Meta providers, local-only models, non-chat routes and response model substitutions fail closed.

The contract derives from platform source `daclab-cern-meta-gateway/ops/inference/i4-bifrost.sh` and `daclab-cern/ops/inference/chx-media/measure_gateway.py`. This source and loopback proof do not establish deployed Meta route availability or account entitlement. The example deliberately has an invalid placeholder origin and no eligible endpoints. Do not fill these from guesses or enable reserved credits by default.

A live CLI run additionally requires all of:

- A flow and per-task acknowledgement bound to the canonical rubric hash.
- An offline report with `flow_contract_passed: true` and matching flow/rubric hashes.
- Separate `--circuit-evidence` for the actual recorded-data Phase One circuit, with `scope: handoff-recorded-phase1`, `status: VERIFIED`, matching `rubric_sha256`, source `evidence` and `owner_ratification`. Synthetic development fixtures never satisfy this gate.
- Explicit owner authorization evidence supplied with `--owner-authorization`.
- A `--gateway-contract-evidence` JSON file containing the exact configured `base_url`, `status: VERIFIED` and a nonempty `evidence` pointer for the checked deployment contract.
- Configured eligible Meta API endpoints and a securely supplied virtual key. Credit-consuming endpoints remain disabled unless explicitly allowed under the owner's authorization.

Evidence files and approval declarations are trusted operator inputs, not cryptographic human signatures. They must not be fabricated by a model. Changing the flow or rubric invalidates the prior dry run. The existing live-capture Phase Two hold remains intact; this development flow does not authorize hardware or product model calls.

Completion-token reservations are debited before transport and are not refunded after uncertain outcomes. They bound requested output tokens, not prompt tokens, actual billing or energy. No automatic fallback across providers, retry of unknown remote outcomes, or claim of improved efficiency is made.

## Acceptance and limits

Transport acceptance uses a real loopback HTTP server with dummy credentials to check request/auth shape, redirection containment, timeout and response bounds, parsing and safe errors. Workflow acceptance exercises actual thread completion events, dependency failure, ownership collisions, rubric/gate refusal and retry caps. CLI acceptance checks that changed authority and missing live proof refuse execution, and offline fixtures produce only review reports.

The dry-run evidence under `docs/evidence/development-swarm-dry-run.json` proves the included fixture circuit only. Live gateway execution, generated feature quality, deployed swarm operation and Handoff's real-capture evaluation remain UNVERIFIED until separately exercised under their gates.

Flow/config files are trusted, owner-reviewed operator input. Never execute a model-produced flow or treat its chosen origin, credential variable or evidence declarations as authorization. Recorded-data circuit ratification remains an owner gate; the CLI does not manufacture it.

Privacy limitation: the content-logging suppression header is a request, not proof of server settings. Bifrost's `allow_per_request_content_storage_override` and connector content settings must be checked on the deployed gateway before asserting suppression. See the [primary Bifrost client configuration](https://github.com/maximhq/bifrost/blob/dev/docs/deployment-guides/config-json/client.mdx).

Callback functions are trusted host code and enforce their own deadlines. Python worker threads cannot be forcibly terminated safely. The gateway timeout bounds socket inactivity, not total elapsed time under a continuously trickling response. Use an owner-managed process/job deadline for a hard wall-clock limit; this CLI does not claim one.

## Offline-only owner decision

Drew explicitly chose “Keep live calls held; finish offline checks” during this implementation. No live smoke run or credit use is authorized. The integrated transport/workflow test exercises real loopback HTTP with synthetic responses and a dummy key; it proves the components work together, not the upstream Meta service. Independent acceptance of actual feature behavior remains a separate execution check.

## Source binding and failure visibility

Each flow supplies a concrete `feature_request`, explicit `acceptance_criteria`, and hash-pinned `source_files`. The loader admits bounded UTF-8 regular files under the selected canonical source root; traversal, symlinks, hash drift and oversized inputs fail before dispatch. The report records the source-context digest, and live prompts use the same snapshot. The rubric is likewise read once and bound to its digest rather than re-read between tasks.

Configuration, evidence and generated JSON reject duplicate keys, nonfinite values and non-object documents. Invalid static checks, task acknowledgements and held gates fail preflight. Explicit failed runner statuses and status-bearing transport errors cannot become `CHECKED`; terminal or uncertain transport outcomes are not retried. Truncated/filtered responses fail acceptance. CLI failures return nonzero with a safe validation-stage identifier, never a secret-bearing remote payload.

## Cost-floor simulation

```sh
python3 scripts/simulate_development.py --output /path/to/new-simulation-report.json
```

`docs/evidence/development-cost-simulation.json` contains reproducible seeded runs and the exact rational oracle for every supplied policy. The optimizer enumerates the bounded set of distinct-attempt policies, stops on first checked success, and selects minimum expected declared cost subject to the declared success floor. Infeasible floors return `NO_SIGNAL`; they are never weakened. The statistical simulation reports `MISS` and exits nonzero if observations exceed its declared tolerance.

The CLI uses this same optimizer when owner-supplied `success_probability_estimates` and eligible endpoints are present. Its `routing_plans` preserve the estimates, selected policy, assumptions and oracle comparison. Missing estimates/endpoints are visible as `NO_SIGNAL`, including in plan mode. The default example deliberately remains without live endpoints. Known validation failure can advance to the next attempt in the selected policy; an uncertain transport outcome stops rather than being replayed.

This is a floor only within the supplied candidate set, independent-success assumption, declared fixed cost model and bounded attempts. Real failures can be correlated. Real prompt/output billing, provider rate limits, latency and energy remain unmeasured; no claim of a production cost floor follows. Static proposal conformance is not functional feature correctness. The real-capture product bar remains unchanged.
