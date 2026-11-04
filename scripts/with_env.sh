#!/usr/bin/env bash
# Run a command with the repo's .env exported into its environment only (not the parent shell).
# Refuses to run if the env check fails, so nothing starts outside the local-runtime boundary.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$root/scripts/env_check.py" --quiet
set -a
# shellcheck disable=SC1091
. "$root/.env"
set +a
exec "$@"
