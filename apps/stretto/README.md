# Stretto

*Stretto: the tightened final passage, where everything comes together.* A local time, focus and efficiency tracker that finds **where your day was lost** (detours, ping-pong between two places, routes you repeat) and uses a **Meta model** to turn those measured findings into a few concrete changes. Everything is recorded on your own computer.

Built for the Meta Global AI Developer Hackathon (Indie developer track, "Build for Your World").

## Run it (Python 3.8+, nothing to download)

```
sh install.sh          # macOS / Linux
.\install.ps1          # Windows (PowerShell)
```

This creates a data folder (`~/.stretto`), copies `.env.example` to `.env`, runs a health check (`python3 -m stretto doctor`) and starts the app at http://127.0.0.1:8760. No packages, no build step, no account.

## Meta models

Every model call at runtime goes to a Meta model through the Meta Model API (`muse-spark-1.3`). Judges use their own key:

1. Create a key at https://dev.meta.ai.
2. Put it in `.env` as `MODEL_API_KEY=...` (the file is created for you; it is git-ignored and never printed).
3. `python3 -m stretto accept meta-insights` (a person types their name and an exact phrase; nothing is sent to Meta before that).

Keyless mode: `STRETTO_REPLAY=<folder>` answers from recorded Meta replies instead of calling the API. `STRETTO_RECORD=<folder>` records them. *No recorded runs are bundled yet.*

What goes to Meta, and what does not: app names, site domains, minutes and Stretto's own measured findings for one day. Never window titles, URLs, screenshots or keystrokes. A reply is checked before it is shown: a suggestion must cite a real finding, any number above 5 must exist in the measured facts, medical or mental-health advice is dropped, and the result is labelled **inferred**. Every call is in a hash-chained ledger (model, tokens, estimated cost) and a daily spend cap applies.

## Your data and consent

Stretto reads nothing from your computer until a person accepts a notice: `browser-history`, `host-system`, `meta-insights`. The server enforces this (it refuses data otherwise), consent is recorded in a tamper-evident log, and you can revoke at any time and delete what was imported. The agent (`agent/`, plain Python, source included) captures the front application, its title, idle time and pointer position every 5 seconds, imports browser history read-only (domain and title only, no paths or queries), and never captures keystrokes, screenshots, the clipboard, microphone or camera. Private/incognito windows are dropped.

Each computer enrols with its own key (a one-time code, shown once, stored only as a hash). A device key can send that device's data and stop recording; it cannot read your data or accept notices. The master token never leaves the server.

## What is real, simulated, and not built

* **Real and tested** (`python3 -m unittest discover -s tests -t .`): store, source merging, loss and path analysis, XP and streaks, patterns, consent, enrolment and scoping, agent bundle, permission plans, the Meta client and its guards, setup scripts.
* **Simulated:** the demo day (`Load a simulated day`) is generated data and is labelled *Simulated* everywhere it appears.
* **Not built yet:** Windows lock/unlock and activity-history importers, a Wayland collector, scheduled-start for the server, TLS for remote mode.
* **Verified only on:** macOS 12 (server, tests) and Windows 10 (agent probe, script parsing). Linux is tested through unit tests only.

## Layout

`stretto/` server (stdlib only) · `stretto/static/` web interface · `agent/` the tracking agent · `tests/` · `.env.example`
