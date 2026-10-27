# Licensing and the hackathon's Official Rules

This is an engineering checklist, **not legal advice**. It records what the repository does about each rule that touches code, data, ownership or licensing in the Meta Global AI Developer Hackathon "Official Rules and Event Waiver" and Participant Guide.

## What this repository is licensed under

All original code, documentation and figures: **Apache License 2.0** (`LICENSE`, with `NOTICE`). Every source file carries `SPDX-License-Identifier: Apache-2.0`; every package manifest declares it; `scripts/release_check.py` fails the build if any of that is missing [C:release-gates].

Why Apache-2.0 for this event:

| Need from the rules | How Apache-2.0 fits |
|---|---|
| "Repositories must be public" | a public repo needs an open license so others can legally read, run and fork it |
| Entrant keeps ownership of the Submission | Apache-2.0 is a non-exclusive grant; copyright stays with the author |
| Organizers get a perpetual, irrevocable, worldwide, royalty-free, non-exclusive license to use the Submission for any purpose | that license is a separate grant the entrant makes in the Rules. Apache-2.0 imposes no field-of-use, non-commercial or copyleft restriction that could narrow it, so the two grants do not conflict. **Do not add any such restriction.** |
| Open-source components allowed if their licenses are followed | permissive, with a patent grant; compatible with the optional dependency (`cryptography`, Apache-2.0 OR BSD-3-Clause) and with Rust's standard library (MIT OR Apache-2.0). See `THIRD_PARTY.md`. |
| The open-weight model Muse Glimmer | reported to be Apache-2.0; confirm on the model card before relying on it. This repository does **not** redistribute any model weights. |

If you ever want a different license, change it before the first public push: relicensing later does not withdraw what others already received.

## Rule-by-rule

| Rule (summary) | What the repository does | Evidence |
|---|---|---|
| **One track, one problem statement** per submission | The submission declares **Indie Developer** and **Push the Frontier** (as in the application). The story explains why both ideas matter, but it is not a second entry. | `docs/STORY.md`, `docs/HACKATHON.md` |
| **New work only; identify what was built during the event** | Authorship dates are listed per component, and the git history separates the 2026-10-26 groundwork from the building period | `docs/HACKATHON.md`, `git log` |
| **Original work; no code, data or assets you lack rights to** | No third-party code, data, images, fonts or weights are included. The algorithms used (Langton's ant, Erlang C, Jain's index, Jensen-Shannon divergence, Hedge, Johnson-Lindenstrauss) are public ideas implemented from their definitions. The Apache-2.0 text is the unmodified standard form. | `THIRD_PARTY.md`, release gate [C:release-gates] |
| **Open-source licenses followed** | All dependencies are listed with their licenses; the release gate rejects any unlisted external dependency | `scripts/release_check.py` |
| **Materials are not confidential** | Nothing secret or proprietary is in the repository. The public-safety scan blocks private addresses, e-mail addresses, personal paths and key shapes | `scripts/public_scan.py` [C:release-gates] |
| **Use Meta's models** | Every learned model in the runtime must be a Meta model, enforced in code. No API key is stored; live calls are made by the person running it, with their own credentials. | `metarouter.policy` [C:meta-only-policy] |
| **Meta Model API / credit terms** | These are separate agreements between you and Meta (including the 10-day credit window and the card pre-authorization). Nothing in this repository changes or replaces them. | n/a |
| **Meta trademarks** | "Meta", "Muse", "Glimmer" and "SAM" are used only to name the models. No logos or brand assets are included, and the project is independent and not endorsed by Meta (see `NOTICE`). | `NOTICE` |
| **Recording and likeness** | The Rules let Organizers use recordings and screen shares of participants. If the demo video shows another person, get their written consent first. This project's own pipeline is consent-first and stores no raw media. | `docs/PRIVACY.md` [C:no-raw-media-stored] |
| **Representations and warranties on Submission** | Only the author can make them. If any part was written under an employer's or client's IP assignment, resolve that before submitting. | not checkable by code |
| **Development tooling** | Most code was written with an AI coding assistant (Claude Code), directed and reviewed by the author, not with Meta's Muse Code. Disclosed in `docs/HACKATHON.md`. | `docs/HACKATHON.md` |
| **Eligibility, sanctions, age, tax forms, waiver** | Personal obligations of the participant, handled outside the repository | n/a |

## Before the first public push

1. Confirm the copyright holder named in `NOTICE` (currently the public handle "iamdrewfortini and contributors").
2. Check any employer or client agreement that could claim the code.
3. Re-run `python scripts/release_check.py` and `python scripts/verify_claims.py --require-all`.
4. Read the current Official Rules once more: they may be modified, and they control.
