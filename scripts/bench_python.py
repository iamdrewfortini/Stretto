# SPDX-License-Identifier: Apache-2.0
"""Python side of the native benchmark (same workloads as crates/*/examples/bench.rs). Run on the same machine for a fair comparison."""
import os, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in ("wf13d", "coherence"): sys.path.insert(0, os.path.join(ROOT, "packages", p, "src"))
from wf13d.table import build
from wf13d.bridge import analyze, pack, unpack
from coherence.swarm import langton_until_locked
t = time.perf_counter(); blob = build(); b = time.perf_counter() - t
analyze.cache_clear(); t = time.perf_counter(); [analyze(a) for a in range(1 << 18)]; cold = (time.perf_counter() - t) / (1 << 18)
print(f"python wf13d: build 262,144-entry table {b*1e3:.0f} ms ({len(blob)} bytes); analyze() {cold*1e9:.0f} ns/address cold")
t = time.perf_counter(); r = langton_until_locked(); e = time.perf_counter() - t; print(f"python ant: empty grid {r['status']} steps_run={r['steps_run']} in {e*1e3:.1f} ms ({e/r['steps_run']*1e9:.0f} ns/step)")
lines = [l for l in open(os.path.join(ROOT, "conformance", "ant_golden.txt")) if l.strip()]; tot = 0; t = time.perf_counter()
for l in lines:
    seed = [tuple(int(v) for v in p.split(",")) for p in l.split("|")[0].strip()[4:].strip().split(";") if p]; tot += langton_until_locked(seed, cap=400_000)["steps_run"]
e = time.perf_counter() - t; print(f"python ant: {len(lines)} seeded cells, {tot} total steps in {e*1e3:.1f} ms ({e/tot*1e9:.0f} ns/step)")
