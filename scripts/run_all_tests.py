# SPDX-License-Identifier: Apache-2.0
"""Runs every package's tests plus the root integration tests, each in its own process with only the package source dirs on the path. Exit code 1 if anything fails."""
import glob, os, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
env = dict(os.environ, PYTHONPATH=os.pathsep.join(sorted(glob.glob(os.path.join(ROOT, "packages", "*", "src")))), PYTHONWARNINGS="ignore")
total = 0; fail = []
for d in sorted(glob.glob(os.path.join(ROOT, "packages", "*", "tests"))) + [os.path.join(ROOT, "tests")]:
    if not os.path.isdir(d): continue
    r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", d, "-t", d, "-p", "test_*.py"], capture_output=True, text=True, env=env, cwd=d)
    last = [l for l in r.stderr.splitlines() if l.startswith("Ran ")]; n = int(last[0].split()[1]) if last else 0; total += n
    print(f"{'PASS' if r.returncode == 0 else 'FAIL'} {os.path.relpath(d, ROOT):32s} {n:4d} tests");
    if r.returncode: fail.append(d); print(r.stderr[-1500:])
print(f"TOTAL {total} tests, {len(fail)} failing suites"); sys.exit(1 if fail else 0)
