#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Auto-update agent: installer gate against The Why (PR #1, 82efc12).

Run by installer/install.sh during verify_bundle, and standalone:
  python3 scripts/why_check.py [ROOT]
Fails (exit 1) when the shipped tree no longer carries the Why it
promises: the author's Why section, its registered claim, the
suggestion-ranking requirement, and the compounding statement.
Built only from the author's own words in README.md and the spec.
"""
import os
import re
import sys


def check(root):
    bad = []

    def read(rel):
        p = os.path.join(root, rel)
        return open(p, encoding="utf-8").read() if os.path.isfile(p) else ""

    readme = read("README.md")
    if "## Why" not in readme:
        bad.append("README.md: Why section missing")
    if "cannot even picture how much time" not in readme:
        bad.append("README.md: Why lost its core sentence")
    if "[C:intent-dominates-D]" not in readme:
        bad.append("README.md: Why claim tag [C:intent-dominates-D] missing")
    claims = read(os.path.join("scripts", "verify_claims.py"))
    if not re.search(r'@claim\("intent-dominates-D"', claims):
        bad.append("verify_claims.py: intent-dominates-D not registered")
    spec = read(os.path.join("docs", "spec", "VOICE-RUNTIME-SPEC.md"))
    if "Suggestion ranking" not in spec:
        bad.append("VOICE-RUNTIME-SPEC.md: suggestion ranking rule missing")
    if "Never show a suggestion without both numbers" not in spec:
        bad.append("VOICE-RUNTIME-SPEC.md: both-numbers rule missing")
    if "about a full work week every year" not in readme:
        bad.append("README.md: compounding statement missing")
    return bad


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(
        os.path.join(os.path.dirname(__file__), ".."))
    bad = check(root)
    if bad:
        print("why-check: FAILED")
        for b in bad:
            print("  -", b)
        return 1
    print("why-check: ok (Why, claim, ranking rule, compounding present)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
