# SPDX-License-Identifier: Apache-2.0
"""Writes conformance/ant_golden.txt from the Python reference (40 address-seeded cells plus the empty grid). The Rust crate must reproduce every line."""
import glob, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "packages", "coherence", "src"))
from coherence.swarm import langton_until_locked, seed_from_address
lines = []
for i in range(40):
    seed = sorted(seed_from_address(f"{i}.62.080")); r = langton_until_locked(seed, cap=400_000); s = ";".join(f"{x},{y}" for x, y in seed)
    lines.append(f"seed {s} | " + (f"LOCKED {r['steps_run']} {r['lock_step']} {r['vector'][0]} {r['vector'][1]} {int(r['guaranteed'])}" if r["status"] == "LOCKED" else "NOT_LOCKED 0 0 0 0 0"))
os.makedirs(os.path.join(ROOT, "conformance"), exist_ok=True); open(os.path.join(ROOT, "conformance", "ant_golden.txt"), "w").write("\n".join(lines) + "\n"); print(len(lines), "golden lines")
