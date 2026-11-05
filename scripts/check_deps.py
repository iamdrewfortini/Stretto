# SPDX-License-Identifier: Apache-2.0
"""Isolation check. Each package lists the sibling packages it may import in packages/<pkg>/DEPS. This script parses every source file with `ast`, fails on any import outside
(standard library + own package + DEPS + the one declared third-party library), and fails if the package dependency graph has a cycle."""
import ast, os, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "packages"); THIRD = {"harness": {"cryptography"}, "runtime": {"websockets", "onepassword"}}
pk = sorted(d for d in os.listdir(ROOT) if os.path.isdir(os.path.join(ROOT, d)))
deps = {p: [x for x in open(os.path.join(ROOT, p, "DEPS")).read().split()] for p in pk}; bad = []
for p in pk:
    for dp, _, fs in os.walk(os.path.join(ROOT, p, "src")):
        for f in fs:
            if not f.endswith(".py"): continue
            for node in ast.walk(ast.parse(open(os.path.join(dp, f), encoding="utf-8").read())):
                mods = [a.name.split(".")[0] for a in node.names] if isinstance(node, ast.Import) else ([node.module.split(".")[0]] if isinstance(node, ast.ImportFrom) and node.module and node.level == 0 else [])
                for m in mods:
                    if m in sys.stdlib_module_names or m == p or m in deps[p] or m in THIRD.get(p, ()): continue
                    bad.append(f"{p}/{f}: imports '{m}' which is not in DEPS ({deps[p]})")
indeg = {p: len(deps[p]) for p in pk}; ready = [p for p in pk if indeg[p] == 0]; order = []
while ready:
    n = ready.pop(); order.append(n)
    for p in pk:
        if n in deps[p]:
            indeg[p] -= 1
            if indeg[p] == 0: ready.append(p)
if len(order) != len(pk): bad.append("dependency cycle among packages")
print("build order:", " -> ".join(order)); [print("FAIL", b) for b in bad]; sys.exit(1 if bad else 0)
