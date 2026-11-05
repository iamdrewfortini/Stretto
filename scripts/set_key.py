#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Set MODEL_API_KEY in the external runtime env, without printing it.

Two entry points, neither needs 1Password at runtime:
  python3 scripts/set_key.py            # hidden terminal prompt
  python3 scripts/set_key.py --stdin    # piped value (never echoed)
Writes ~/.config/humanflow/runtime.env (or $HUMANFLOW_ENV) atomically
with mode 0600, preserving every other key. Prints only the value's
length and an 8-hex sha256 fingerprint.
"""
import getpass
import hashlib
import os
import sys
from pathlib import Path

ENV = Path(os.environ.get(
    "HUMANFLOW_ENV", Path.home() / ".config" / "humanflow" / "runtime.env"))


def write_key(path, key):
    key = key.strip()
    if len(key) < 20:
        raise ValueError("key looks too short; refusing to save")
    lines, done = [], False
    if path.is_file():
        for line in path.read_text().splitlines():
            if line.startswith("MODEL_API_KEY="):
                lines.append("MODEL_API_KEY=" + key)
                done = True
            else:
                lines.append(line)
    if not done:
        lines.append("MODEL_API_KEY=" + key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, ("\n".join(lines) + "\n").encode())
    finally:
        os.close(fd)
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    return len(key), hashlib.sha256(key.encode()).hexdigest()[:8]


def main():
    key = sys.stdin.read() if "--stdin" in sys.argv else getpass.getpass(
        "Meta Model API key (hidden, not echoed): ")
    try:
        n, fp = write_key(ENV, key)
    except ValueError as e:
        print(f"set-key: {e}", file=sys.stderr)
        return 1
    print(f"set-key: saved to {ENV} (len={n} sha256:{fp}, mode 600)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
