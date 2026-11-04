# metacoh-sensors

Consent-gated, local-only desktop activity sensors for Humanflow.
Part of the Meta Coherence Hive (Apache-2.0).

The agent runs on the person's own Linux or macOS desktop, measures
focus-window activity, idle time, pointer and input intensity (counts
only, never content), turns it into attention metrics and timeline
episodes, streams them to the local runtime over `POST /v1/ingest`,
and narrates short, measured suggestions in the dashboard.

```bash
PYTHONPATH=packages/sensors/src python3 -m sensors probe
PYTHONPATH=packages/sensors/src python3 -m sensors grant window idle --ttl 8h
PYTHONPATH=packages/sensors/src python3 -m sensors run --gateway http://127.0.0.1:8787
```

## Privacy bar (enforced in code, checked by tests)

- Consent default-deny per source (`window`, `input`, `pointer`,
  `idle`); stored in `~/.config/humanflow/consent.json` (0600);
  revoke takes effect within one tick.
- Keyboard: counts per window only, never keys or text. Pointer:
  distance and click counts, never coordinates stored. Window titles
  are redacted and truncated to 80 chars; `SENSORS_TITLES=off` drops
  them. No screenshots, no audio, ever.
- Local only: the ingest client refuses a non-loopback gateway.
  Model calls (unknown-app categorisation, once per app, cached
  forever) go only through the runtime gateway, never on the tick
  path, and the agent imports no sibling package so it runs alone.

## Layout

`adapters` (platform probes/polls), `consent`, `redact`, `episodes`
(merging, categories, ledger rules), `metrics` (exact window
definitions in the docstring), `narration` (one line per episode,
suggestions at most once per 5 min citing their number), `ingest`
(batches of at most 200, backoff, 10-minute offline buffer),
`importer` (1 Hz tick, 200 ms adapter budget, p95 work under 5 ms).

## P2 — spec only (not built)

Wayland/GNOME and Windows adapters, and on-device models. Meta's
documented constraints: Muse Glimmer 30B is the smallest Meta
open-weight chat model (Q4 GGUF 16.8 GB, 24 GB GPU recommended,
ExecuTorch has no CPU variant), and Meta publishes no open-weight
embeddings, STT or TTS. On-device sensing therefore stays
deterministic: counting, merging and threshold rules on the desktop,
with narration phrasing (numbers unchanged) as the only optional
model pass, through the gateway.
