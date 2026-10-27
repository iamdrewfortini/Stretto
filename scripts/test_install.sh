#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# End-to-end installer test: build the bundle from the committed tree, tamper-test it, install into a clean prefix with no network, run doctor, reinstall (upgrade), uninstall, and
# prove nothing was left behind. Prints one line starting "INSTALL TEST" on success.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT; cd "$ROOT"
ssh-keygen -q -t ed25519 -N "" -f "$WORK/key" -C release-test; python3 scripts/package.py --out "$WORK/dist" --sign-key "$WORK/key" ${METACOH_ALLOW_DIRTY:+--allow-dirty} > "$WORK/build.log" 2>&1 || { tail -30 "$WORK/build.log"; exit 1; }
TGZ="$(ls "$WORK"/dist/*.tar.gz)"; mkdir "$WORK/x" && tar xzf "$TGZ" -C "$WORK/x"; B="$(ls -d "$WORK"/x/metacoh-*)"
echo "metacoh-release $(cut -d' ' -f1,2 "$WORK/key.pub")" > "$WORK/allowed"
"$B/installer/install.sh" --verify-only --allowed-signers "$WORK/allowed" >/dev/null
"$B/installer/install.sh" --verify-only >/dev/null 2>&1 && { echo "a signed bundle must demand --allowed-signers"; exit 1; } || true
cp -r "$B" "$WORK/tampered"; echo x >> "$WORK/tampered/LICENSE"; "$WORK/tampered/installer/install.sh" --verify-only --allowed-signers "$WORK/allowed" >/dev/null 2>&1 && { echo "tampered bundle accepted"; exit 1; } || true
P="$WORK/prefix"; env -u PIP_INDEX_URL PIP_NO_INDEX=1 "$B/installer/install.sh" --prefix "$P" --allowed-signers "$WORK/allowed" > "$WORK/install.log" 2>&1 || { tail -40 "$WORK/install.log"; exit 1; }
"$P/bin/metacoh" version >/dev/null; "$P/bin/metacoh" doctor | tail -1; test -f "$P/include/wf13d_core.h" && test -f "$P/lib/libwf13d_core.so" && test -f "$P/lib/pkgconfig/ant.pc"
"$B/installer/install.sh" --prefix "$P" --allowed-signers "$WORK/allowed" > "$WORK/upgrade.log" 2>&1 || { tail -20 "$WORK/upgrade.log"; exit 1; }
"$B/installer/install.sh" --prefix "$P" --uninstall >/dev/null; LEFT="$({ find "$P" -mindepth 1 2>/dev/null || true; } | wc -l)"         # a prefix that no longer exists has 0 leftovers
[ "$LEFT" = 0 ] || { echo "files left after uninstall: $LEFT"; find "$P"; exit 1; }
rm -rf "$WORK/fail" && mkdir "$WORK/fail"; cp -r "$B" "$WORK/broken"; sed -i 's/^metacoh==/metacoh-nonexistent==/' "$WORK/broken/wheelhouse/requirements.lock"
( cd "$WORK/broken" && sha256sum wheelhouse/requirements.lock >/dev/null; grep -v ' wheelhouse/requirements.lock$' SHA256SUMS > S && sha256sum wheelhouse/requirements.lock >> S && mv S SHA256SUMS && rm -f SHA256SUMS.sig )
"$WORK/broken/installer/install.sh" --prefix "$WORK/fail/p" >/dev/null 2>&1 && { echo "a broken lockfile must fail"; exit 1; } || true
[ ! -e "$WORK/fail/p/venv" ] || { echo "rollback left a venv behind"; exit 1; }
echo "INSTALL TEST OK: signed bundle verified, tampered bundle rejected, offline hash-pinned install + doctor passed, upgrade clean, uninstall left 0 files, broken install rolled back"
