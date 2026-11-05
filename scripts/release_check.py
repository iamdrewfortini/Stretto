#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Release gate: licensing, version consistency, isolation, and public-safety. Exit code 1 on any failure.
Checks: LICENSE is the Apache-2.0 text; NOTICE and THIRD_PARTY exist; every source file carries an SPDX header; every pyproject/Cargo manifest declares Apache-2.0;
all versions equal VERSION; every external dependency is listed in THIRD_PARTY.md; then check_deps.py and public_scan.py."""
import glob, os, re, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..")); bad = []
def need(cond, msg):
    if not cond: bad.append(msg)
version = open(os.path.join(ROOT, "VERSION")).read().strip()
lic = open(os.path.join(ROOT, "LICENSE"), encoding="utf-8").read()
need("Apache License" in lic and "Version 2.0, January 2004" in lic and "END OF TERMS AND CONDITIONS" in lic and len(lic) > 10000, "LICENSE is not the full Apache-2.0 text")
for f in ("NOTICE", "THIRD_PARTY.md", "docs/LICENSE-AND-TERMS.md", "docs/PACKAGING.md"): need(os.path.exists(os.path.join(ROOT, f)), f"missing {f}")
third = open(os.path.join(ROOT, "THIRD_PARTY.md"), encoding="utf-8").read()
SKIP = {".git", "__pycache__", "target", "dist", ".venv"}
for dp, dn, fs in os.walk(ROOT):
    dn[:] = [d for d in dn if d not in SKIP]
    for f in fs:
        if f.endswith((".py", ".rs", ".sh", ".ps1", ".c", ".cpp", ".h")):
            head = "".join(open(os.path.join(dp, f), encoding="utf-8", errors="ignore").readlines()[:3])
            need("SPDX-License-Identifier: Apache-2.0" in head, f"no SPDX header: {os.path.relpath(os.path.join(dp, f), ROOT)}")
for p in glob.glob(os.path.join(ROOT, "packages", "*", "pyproject.toml")):
    t = open(p).read(); n = os.path.relpath(p, ROOT)
    need(f'version = "{version}"' in t, f"{n}: version != VERSION ({version})"); need('license = "Apache-2.0"' in t, f"{n}: license field")
    for dep in re.findall(r'"([A-Za-z0-9_.-]+)(?:[<>=!~][^"]*)?"', t.split("dependencies = [", 1)[1].split("]", 1)[0]) if "dependencies = [" in t else []:
        need(dep.startswith("metacoh-"), f"{n}: external runtime dependency '{dep}' not allowed")
    opt = re.split(r"^\[", t.split("[project.optional-dependencies]", 1)[1].lstrip("\n"), maxsplit=1, flags=re.M)[0] if "[project.optional-dependencies]" in t else ""
    for dep in re.findall(r'^\w+ = \["([A-Za-z0-9_.-]+)"', opt, flags=re.M):
        need(dep.lower() in third.lower(), f"{n}: optional dependency '{dep}' missing from THIRD_PARTY.md")
for p in glob.glob(os.path.join(ROOT, "crates", "*", "Cargo.toml")):
    t = open(p).read(); n = os.path.relpath(p, ROOT); need(f'version = "{version}"' in t, f"{n}: version != VERSION"); need('license = "Apache-2.0"' in t, f"{n}: license field")
lock = os.path.join(ROOT, "crates", "Cargo.lock")
if os.path.exists(lock):
    pk = re.findall(r'^name = "([^"]+)"', open(lock).read(), flags=re.M); ext = [x for x in pk if x not in ("ant", "wf13d-core")]; need(not ext, f"external Rust crates present: {ext} (list them in THIRD_PARTY.md first)")
else: bad.append("crates/Cargo.lock missing (builds must be --locked)")
for script in ("check_deps.py", "public_scan.py"):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", script)], capture_output=True, text=True); need(r.returncode == 0, f"{script} failed:\n{r.stdout[-600:]}")
print(f"release check ({version}): {'FAILED' if bad else 'ok'}"); [print("  -", b) for b in bad]; sys.exit(1 if bad else 0)
