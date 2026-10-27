#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Proves the C ABI from real C and C++: builds the two smoke programs against the release shared libraries and checks the printed values against the Python reference.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; LIB="${1:-$ROOT/crates/target/release}"; TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
for CC in gcc g++; do
  SRC="$ROOT/crates/examples-c/smoke.$([ "$CC" = gcc ] && echo c || echo cpp)"
  "$CC" -Wall -Wextra -o "$TMP/smoke-$CC" "$SRC" -I"$ROOT/crates/include" -L"$LIB" -lwf13d_core -lant -Wl,-rpath,"$LIB"
  OUT="$("$TMP/smoke-$CC")"; echo "[$CC] $OUT" | tr '\n' ' '; echo
  want="$(PYTHONPATH="$ROOT/packages/wf13d/src" python3 -c 'from wf13d.table import encode; print(encode((31<<13)|(63<<7)|127))')"
  echo "$OUT" | grep -q "word=$want" || { echo "C ABI word mismatch (python says $want)"; exit 1; }
  echo "$OUT" | grep -q "steps=10608 lock=10088 v=-2,-2 guaranteed=1" || { echo "C ABI ant mismatch"; exit 1; }
done
echo "C ABI OK from C and C++"
