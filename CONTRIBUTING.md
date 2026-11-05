# Contributing to Stretto and Humanflow

Thanks for helping. Stretto (apps/stretto) is the app; Humanflow (packages/runtime) is its backend. Both are small on purpose: standard-library Python, one third-party dependency in the runtime (`websockets`), and Meta models reached through one local gateway.

## Ground rules

- **Privacy is a feature, not a setting.** No change may store raw audio, screen pixels or keystroke content, send the owner's per-event data anywhere, or bypass consent. Reviews block on this.
- **Meta models only, through the gateway.** New model use goes into `docs/spec/models.registry.json` and is called with a role via `runtime.gateway`; nothing calls `api.meta.ai` directly except the realtime transcription bridge.
- **Numbers need proof.** A quantitative statement in `README.md` or `docs/*.md` must carry a claim tag `[C:id]` backed by a check in `scripts/verify_claims.py`, or be marked `<!-- no-claim -->` with a pointer to recorded evidence. `python3 scripts/docs_lint.py` enforces it.
- **Not medical advice.** Suggestions are about time and flow, never health, mental-health or wellbeing advice, and never personality profiling.

## Setup

```bash
python3 -m pip install websockets==15.0.1
python3 scripts/run_all_tests.py      # every package, each in its own process
python3 scripts/check_deps.py         # package isolation: imports must match each package's DEPS
python3 scripts/docs_lint.py
python3 scripts/verify_claims.py
```

To run the app you need a Meta Model API key; see the README quick start. Tests never call the network.

## Pull requests

- One change per pull request, with tests that fail without it.
- New `.py` and `.sh` files start with `# SPDX-License-Identifier: Apache-2.0`.
- Keep functions small and comments for the non-obvious reason.
- By contributing you agree your work is licensed under Apache-2.0.

## AI-assisted contributions

Welcome, and please say so in the pull request: which tool (for example Muse Code or Claude Code), and that you reviewed and ran the result yourself.
