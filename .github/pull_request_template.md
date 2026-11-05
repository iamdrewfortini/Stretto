## What and why

<!-- One change. What it does and the problem it solves. -->

## How it was checked

- [ ] `python3 scripts/run_all_tests.py` passes, and new tests fail without this change
- [ ] `python3 scripts/check_deps.py` and `python3 scripts/docs_lint.py` pass
- [ ] Any new number in the docs has a `[C:id]` claim or a `<!-- no-claim -->` pointer to evidence

## Boundaries

- [ ] No raw audio, screen pixels or keystroke content is stored or sent; consent stays default-deny
- [ ] Model calls go through the runtime gateway with a role; no new egress hosts
- [ ] No secrets in code, tests, logs or events

## AI assistance

<!-- If an AI coding agent helped (for example Muse Code or Claude Code), name it and confirm you reviewed and ran the result. -->
