#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Start Stretto and open it in your browser. Stop with Ctrl-C.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
DATA="${STRETTO_DATA:-$HOME/.stretto}"
PORT="${STRETTO_PORT:-8760}"
cd "$HERE"
( sleep 2; case "$(uname -s)" in Darwin) open "http://127.0.0.1:$PORT" ;; *) command -v xdg-open >/dev/null 2>&1 && xdg-open "http://127.0.0.1:$PORT" || true ;; esac ) &
exec python3 -m stretto --data "$DATA" --port "$PORT"
