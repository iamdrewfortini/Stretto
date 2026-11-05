#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Run a command with the Humanflow runtime env exported into its
# environment only (not the parent shell). The real env file lives
# OUTSIDE every worktree: $HUMANFLOW_ENV, else
# ~/.config/humanflow/runtime.env, else ./env (legacy repo .env).
# Refuses to run if the env check fails, so nothing starts outside
# the local-runtime boundary.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${HUMANFLOW_ENV:-$HOME/.config/humanflow/runtime.env}"
[ -f "$ENV_FILE" ] || ENV_FILE="$root/.env"
export HUMANFLOW_ENV="$ENV_FILE"
python3 "$root/scripts/env_check.py" --quiet ${ALLOW_MISSING_KEY:+--allow-missing-key}
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
exec "$@"
