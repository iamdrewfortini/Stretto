# Security policy

Humanflow handles a person's own time and activity data and a Meta Model API key, so security reports are taken seriously.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private reporting: the repository's **Security** tab → **Report a vulnerability**. Include what you found, how to reproduce it, and the impact you expect. You will get an acknowledgement as soon as the maintainer sees it, and a fix or mitigation plan before any public disclosure.

## What is in scope

- Anything that lets data leave the machine other than calls to `api.meta.ai` through the runtime gateway.
- Ways to bypass the gateway's boundary: listening off loopback, answering non-local clients, calling hosts outside `EGRESS_ALLOWLIST`, following redirects, or serving models outside the registry.
- Leaks of `MODEL_API_KEY` into logs, events, pages, git history or process arguments.
- Consent bypasses in sensors, or any path that stores raw audio, screen pixels or keystroke content.
- Forged events through `POST /v1/ingest` that are not telemetry-shaped (manual ledger entries, model calls, voice turns).

## Supported versions

The latest commit on `main` is supported. This is a hackathon project; there are no long-term support branches yet.
