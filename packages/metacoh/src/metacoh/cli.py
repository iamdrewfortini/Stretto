# SPDX-License-Identifier: Apache-2.0
"""metacoh command line: `metacoh doctor` (self-check of an installed system), `metacoh wf13d c.t.s`, `metacoh ant`, `metacoh version`."""
import argparse, json, sys
from importlib import metadata

PACKAGES = ["wf13d", "coherence", "metarouter", "harness", "telemetry", "cells", "perception", "humanflow", "assistant", "finetune", "handoff", "resonate", "adapters"]
def version():
    try: return metadata.version("metacoh")
    except metadata.PackageNotFoundError: return "0+source"
def doctor():
    from . import doctor as d
    results = d.run_all(); width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results: print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    bad = [n for n, ok, _ in results if not ok]; print(f"\n{len(results) - len(bad)}/{len(results)} checks passed" + (f"; failing: {', '.join(bad)}" if bad else "")); return 1 if bad else 0
def main(argv=None):
    ap = argparse.ArgumentParser(prog="metacoh"); sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("version"); sub.add_parser("doctor"); w = sub.add_parser("wf13d"); w.add_argument("address", help="decimal c.t.s, e.g. 15.07.072"); sub.add_parser("ant")
    a = ap.parse_args(argv)
    if a.cmd == "version": print(version()); return 0
    if a.cmd == "doctor": return doctor()
    if a.cmd == "wf13d":
        from wf13d.bridge import analyze, pack
        c, t, s = (int(x) for x in a.address.split(".")); print(json.dumps(analyze(pack(c, t, s)), indent=1)); return 0
    if a.cmd == "ant":
        from coherence.swarm import langton_until_locked
        print(json.dumps(langton_until_locked(), indent=1, default=str)); return 0
if __name__ == "__main__": sys.exit(main())
