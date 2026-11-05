#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Stretto: install and start on macOS or Linux. Plain Python 3.8+, no packages to download, no root needed.
#   sh install.sh            set up and start
#   sh install.sh --no-start set up only
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
DATA="${STRETTO_DATA:-$HOME/.stretto}"
PY=$(command -v python3 || true)
if [ -z "$PY" ] || ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)'; then
  echo "Python 3.8 or newer is required (python3 not found or too old)."; exit 1
fi
mkdir -p "$DATA"
if [ ! -f "$DATA/.env" ]; then
  cp "$HERE/.env.example" "$DATA/.env"
  chmod 600 "$DATA/.env"
  echo "Created $DATA/.env  <- put your Meta Model API key after MODEL_API_KEY= (it stays on this computer)"
fi
cd "$HERE"
"$PY" -m stretto doctor --data "$DATA" || true
[ "${1:-}" = "--no-start" ] && { echo "Set up. Start later with:  sh run.sh"; exit 0; }
exec sh "$HERE/run.sh"
