#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Docs lint: every quantitative statement must carry a claim tag [C:id]; every tag must name a registered claim; every registered claim must be cited at least once.
A line is quantitative if it has a number followed by a unit word (%, x, ms, steps, tests, bytes, ...). Mark a deliberate non-claim with <!-- no-claim -->. Fenced code is ignored."""
import glob, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ids = set(re.findall(r'@claim\("([A-Za-z0-9-]+)"', open(os.path.join(ROOT, "scripts", "verify_claims.py"), encoding="utf-8").read()))
QUANT = re.compile(r"\d[\d,.]*\s?(?:×|x\b|%|ms\b|ns\b|µs\b|us\b|steps?\b|tests?\b|files?\b|bytes\b|addresses\b|cells?\b|rounds?\b|MiB\b|KiB\b|GiB\b|Hz\b|dimensions?\b|vertices\b|edges\b|seeds?\b|trials?\b|people\b|contributors\b|questions?\b|alerts?\b|signatures?\b|axes\b|numbers\b)")
docs = [os.path.join(ROOT, "README.md")] + sorted(glob.glob(os.path.join(ROOT, "docs", "*.md"))); skip = {"CLAIMS.md"}
bad, cited = [], set()
for f in docs:
    if os.path.basename(f) in skip: continue
    fence = False
    for i, line in enumerate(open(f, encoding="utf-8"), 1):
        if line.lstrip().startswith("```"): fence = not fence; continue
        if fence or line.startswith("#"): continue
        tags = re.findall(r"\[C:([A-Za-z0-9-]+)\]", line); cited |= set(tags)
        for t in tags:
            if t not in ids: bad.append(f"{os.path.relpath(f, ROOT)}:{i}: unknown claim id '{t}'")
        if QUANT.search(line) and not tags and "no-claim" not in line: bad.append(f"{os.path.relpath(f, ROOT)}:{i}: quantitative line without a claim tag: {line.strip()[:90]}")
for u in sorted(ids - cited): bad.append(f"claim '{u}' is registered but cited nowhere in the docs")
print(f"docs lint: {'FAILED' if bad else 'ok'} ({len(ids)} claims, {len(cited)} cited)"); [print("  -", b) for b in bad[:80]]; sys.exit(1 if bad else 0)
