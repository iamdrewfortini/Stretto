#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Runs the Python and Rust benchmarks on this machine and records docs/data/bench.json (or prints it with --print). Needs cargo for the Rust half."""
import glob, json, os, platform, re, subprocess, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in glob.glob(os.path.join(ROOT, "packages", "*", "src")): sys.path.insert(0, p)
def python_side():
    from wf13d.table import build; from wf13d.bridge import analyze; from coherence.swarm import langton_until_locked
    t = time.perf_counter(); build(); table_ms = (time.perf_counter() - t) * 1e3
    analyze.cache_clear(); t = time.perf_counter(); [analyze(a) for a in range(1 << 18)]; word_ns = (time.perf_counter() - t) / (1 << 18) * 1e9
    t = time.perf_counter(); r = langton_until_locked(); ant_ns = (time.perf_counter() - t) / r["steps_run"] * 1e9
    return table_ms, word_ns, ant_ns
def rust_side():
    cm = ["cargo", "run", "--release", "--locked", "-q", "--manifest-path", os.path.join(ROOT, "crates", "Cargo.toml")]
    a = subprocess.run(cm + ["-p", "wf13d-core", "--example", "bench_wf13d"], capture_output=True, text=True, check=True).stdout
    b = subprocess.run(cm + ["-p", "ant", "--example", "bench_ant"], capture_output=True, text=True, check=True).stdout
    return float(re.search(r"table ([\d.]+) ms", a).group(1)), float(re.search(r"word\(\) ([\d.]+) ns", a).group(1)), float(re.search(r"empty grid.*?\(([\d.]+) ns/step\)", b).group(1))
def main():
    pt, pw, pa = python_side(); rt, rw, ra = rust_side()
    out = dict(host=f"{platform.system()} {platform.machine()}, Python {platform.python_version()}", py_table_ms=round(pt, 1), rs_table_ms=round(rt, 2), py_word_ns=round(pw, 0), rs_word_ns=round(rw, 1), py_ant_ns=round(pa, 0), rs_ant_ns=round(ra, 1),
               table_speedup=round(pt / rt, 1), word_speedup=round(pw / rw, 1), ant_speedup=round(pa / ra, 1))
    if "--print" in sys.argv: print(json.dumps(out))
    else:
        os.makedirs(os.path.join(ROOT, "docs", "data"), exist_ok=True); json.dump(out, open(os.path.join(ROOT, "docs", "data", "bench.json"), "w"), indent=1, sort_keys=True); print(json.dumps(out, indent=1))
if __name__ == "__main__": main()
