#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# metacoh installer (Linux). Verifies the bundle, installs into an isolated virtualenv from the bundled wheelhouse with hash pinning (no network, no index), installs native
# libraries and headers, writes an uninstall receipt, runs `metacoh doctor`, and rolls back on any failure. Re-running upgrades cleanly.
set -euo pipefail

PREFIX=""; USER_MODE=0; DO_UNINSTALL=0; VERIFY_ONLY=0; NATIVE=1; PYTHON="${PYTHON:-python3}"; SIGNERS=""
log() { printf '[metacoh-install] %s\n' "$*"; }
die() { printf '[metacoh-install] ERROR: %s\n' "$*" >&2; exit 1; }
usage() { cat <<'USAGE'
Usage: install.sh [--prefix DIR | --user] [--no-native] [--python PYTHON] [--allowed-signers FILE]
                  [--verify-only] [--uninstall]
  --prefix DIR           install under DIR (default /opt/metacoh)
  --user                 install under ~/.local/share/metacoh (no root needed)
  --no-native            skip the Rust shared/static libraries and C headers
  --allowed-signers FILE OpenSSH allowed_signers file; required if the bundle is signed
  --verify-only          verify checksums (and signature) then stop
  --uninstall            remove everything listed in the install receipt
USAGE
}
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX="${2:?--prefix needs a directory}"; shift 2 ;;
    --user) USER_MODE=1; shift ;;
    --no-native) NATIVE=0; shift ;;
    --python) PYTHON="${2:?--python needs a command}"; shift 2 ;;
    --allowed-signers) SIGNERS="${2:?needs a file}"; shift 2 ;;
    --verify-only) VERIFY_ONLY=1; shift ;;
    --uninstall) DO_UNINSTALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
done
BUNDLE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -z "$PREFIX" ]; then if [ "$USER_MODE" = 1 ]; then PREFIX="$HOME/.local/share/metacoh"; else PREFIX="/opt/metacoh"; fi; fi
RECEIPT="$PREFIX/share/metacoh/receipt.json"

uninstall() {
  [ -f "$RECEIPT" ] || die "no receipt at $RECEIPT; refusing to remove anything"
  "$PYTHON" - "$RECEIPT" <<'PY'
import json, os, shutil, sys
r = json.load(open(sys.argv[1])); prefix = r["prefix"]
for f in r["files"]:
    p = f["path"]
    if os.path.isfile(p) or os.path.islink(p): os.remove(p)
shutil.rmtree(r["venv"], ignore_errors=True)
for d in sorted(r["dirs"], key=len, reverse=True):
    try: os.rmdir(d)
    except OSError: pass
os.remove(sys.argv[1])
for d in (os.path.dirname(sys.argv[1]), os.path.dirname(os.path.dirname(sys.argv[1])), prefix):
    try: os.rmdir(d)
    except OSError: pass
print("removed", len(r["files"]), "files and the virtualenv")
PY
}

verify_bundle() {
  [ -f "$BUNDLE/SHA256SUMS" ] || die "SHA256SUMS missing from the bundle"
  (cd "$BUNDLE" && sha256sum --check --quiet SHA256SUMS) || die "checksum verification FAILED: the bundle is damaged or modified"
  log "checksums OK ($(wc -l < "$BUNDLE/SHA256SUMS") files)"
  if [ -f "$BUNDLE/scripts/why_check.py" ]; then
    "$PYTHON" "$BUNDLE/scripts/why_check.py" "$BUNDLE" || die "why-check FAILED: bundle no longer carries The Why"
  fi
  if [ -f "$BUNDLE/SHA256SUMS.sig" ]; then
    [ -n "$SIGNERS" ] || die "this bundle is signed; pass --allowed-signers FILE to verify it"
    ssh-keygen -Y verify -f "$SIGNERS" -I metacoh-release -n file -s "$BUNDLE/SHA256SUMS.sig" < "$BUNDLE/SHA256SUMS" > /dev/null || die "signature verification FAILED"
    log "signature OK"
  else
    log "WARNING: bundle is unsigned (integrity only, no authenticity)"
  fi
}

if [ "$DO_UNINSTALL" = 1 ]; then uninstall; exit 0; fi
verify_bundle
[ "$VERIFY_ONLY" = 1 ] && exit 0

"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || die "Python 3.10 or newer is required (found: $("$PYTHON" -V 2>&1))"
if [ -f "$RECEIPT" ]; then log "existing installation found: removing it first (clean upgrade)"; uninstall; fi

TRACKED=()
rollback() { local rc=$?; if [ $rc -ne 0 ]; then log "install failed (exit $rc): rolling back"; rm -rf "$PREFIX/venv"; for f in "${TRACKED[@]:-}"; do [ -n "$f" ] && rm -f "$f"; done; fi; exit $rc; }
trap rollback EXIT

mkdir -p "$PREFIX/bin" "$PREFIX/share/metacoh"
log "creating virtualenv at $PREFIX/venv"
"$PYTHON" -m venv "$PREFIX/venv"
log "installing from the bundled wheelhouse (offline, hash-pinned)"
"$PREFIX/venv/bin/python" -m pip install --quiet --no-index --find-links "$BUNDLE/wheelhouse" --require-hashes -r "$BUNDLE/wheelhouse/requirements.lock"
ln -sf "$PREFIX/venv/bin/metacoh" "$PREFIX/bin/metacoh"; TRACKED+=("$PREFIX/bin/metacoh")

if [ "$NATIVE" = 1 ] && [ -d "$BUNDLE/native" ]; then
  mkdir -p "$PREFIX/lib/pkgconfig" "$PREFIX/include"
  for f in "$BUNDLE"/native/lib/*; do [ -f "$f" ] && install -m 0755 "$f" "$PREFIX/lib/" && TRACKED+=("$PREFIX/lib/$(basename "$f")"); done
  for f in "$BUNDLE"/native/include/*.h; do install -m 0644 "$f" "$PREFIX/include/" && TRACKED+=("$PREFIX/include/$(basename "$f")"); done
  for f in "$BUNDLE"/native/lib/pkgconfig/*.pc; do sed "s|@PREFIX@|$PREFIX|g" "$f" > "$PREFIX/lib/pkgconfig/$(basename "$f")" && TRACKED+=("$PREFIX/lib/pkgconfig/$(basename "$f")"); done
  log "native libraries and headers installed"
fi

log "running metacoh doctor"
"$PREFIX/bin/metacoh" doctor

"$PYTHON" - "$PREFIX" "$BUNDLE" "$RECEIPT" "${TRACKED[@]}" <<'PY'
import hashlib, json, os, sys, time
prefix, bundle, receipt, *files = sys.argv[1:]
sums = hashlib.sha256(open(os.path.join(bundle, "SHA256SUMS"), "rb").read()).hexdigest()
ent = [{"path": f, "sha256": (hashlib.sha256(open(f, "rb").read()).hexdigest() if os.path.isfile(f) and not os.path.islink(f) else None)} for f in files]
dirs = sorted({os.path.dirname(f) for f in files} | {os.path.join(prefix, "share", "metacoh"), os.path.join(prefix, "share"), os.path.join(prefix, "bin")})
manifest = json.load(open(os.path.join(bundle, "MANIFEST.json")))
json.dump({"name": "metacoh", "version": manifest["version"], "commit": manifest["commit"], "prefix": prefix, "venv": os.path.join(prefix, "venv"), "bundle_sha256sums": sums,
           "installed_epoch": int(time.time()), "files": ent, "dirs": dirs}, open(receipt, "w"), indent=1)
PY
trap - EXIT
log "installed metacoh $("$PREFIX/bin/metacoh" version) to $PREFIX"
log "run the gateway with: $PREFIX/bin/metacoh gateway   (then open http://127.0.0.1:8787/settings)"
log "run the sensors with:  $PREFIX/bin/metacoh sensors probe"
log "uninstall with: $0 --prefix $PREFIX --uninstall"
