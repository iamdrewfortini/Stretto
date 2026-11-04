#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Start, stop or check the local runtime gateway. Tracks the process by PID file, never by name.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
pidf="$root/var/gateway.pid"; log="$root/var/gateway.log"
mkdir -p "$root/var"
running() { [[ -f "$pidf" ]] && kill -0 "$(cat "$pidf")" 2>/dev/null; }
case "${1:-status}" in
  start)
    if running; then echo "already running (pid $(cat "$pidf"))"; exit 0; fi
    PYTHONPATH="$(printf '%s:' "$root"/packages/*/src)" setsid nohup "$root/scripts/with_env.sh" python3 -m runtime.gateway >"$log" 2>&1 </dev/null &
    echo $! >"$pidf"; sleep 1.5
    if running; then tail -1 "$log"; else echo "failed to start:"; tail -5 "$log"; exit 1; fi ;;
  stop)
    if running; then kill "$(cat "$pidf")"; echo "stopped"; else echo "not running"; fi
    rm -f "$pidf" ;;
  status)
    if running; then echo "running (pid $(cat "$pidf"))"; curl -s -m 3 http://127.0.0.1:8787/healthz; echo; else echo "not running"; exit 1; fi ;;
  *) echo "usage: $0 start|stop|status"; exit 2 ;;
esac
