# SPDX-License-Identifier: Apache-2.0
"""Organism layer: genome (helix + repair), homeostasis, immune system, microbiome population, cost cascade, agent DAGs.
Everything is a pure, testable mechanism. Meta-model planners plug in through plan dicts that are VALIDATED before anything runs. Stdlib only."""
import hashlib, itertools, json, math, random, re, statistics
from harness.boundary import recurring

# ---------------- genome: bases A,C,G,T = 0..3, complement = XOR 3; codon = 3 data bases + 1 parity base; two complementary strands
comp = lambda b: b ^ 3
def to_bases(data: bytes):
    out = []
    for byte in data: out += [(byte >> s) & 3 for s in (6, 4, 2, 0)]
    return out
def from_bases(bases):
    bs = list(bases); bs += [0] * (-len(bs) % 4); return bytes(sum(b << s for b, s in zip(bs[i:i + 4], (6, 4, 2, 0))) for i in range(0, len(bs), 4))
def codons(bases):
    b = list(bases) + [0] * (-len(bases) % 3); return [b[i:i + 3] + [sum(b[i:i + 3]) % 4] for i in range(0, len(b), 3)]
def parity_ok(c): return sum(c[:3]) % 4 == c[3]
class Gene:
    """s1 = data codons with parity; s2 = complement strand with its own parity. n = number of data bases (strips padding)."""
    def __init__(self, name, value: bytes):
        self.name, self.n = name, len(value) * 4; self.s1 = codons(to_bases(value))
        self.s2 = [[comp(b) for b in c[:3]] for c in self.s1]; self.s2 = [c + [sum(c) % 4] for c in self.s2]
    def value(self): return from_bases([b for c in self.s1 for b in c[:3]][:self.n])
def inspect(g):
    """Per codon: ok | repair_s1 | repair_s2 | unrepairable. Never guesses when both strands disagree."""
    out = []
    for c1, c2 in zip(g.s1, g.s2):
        p1, p2 = parity_ok(c1), parity_ok(c2); paired = all(comp(a) == b for a, b in zip(c1[:3], c2[:3]))
        out.append("ok" if p1 and p2 and paired else "repair_s1" if (not p1 and p2) else "repair_s2" if (p1 and not p2) else "unrepairable")
    return out
def repair(g):
    """Splice: rebuild the damaged strand from its intact partner. Returns (repaired_count, unrepairable_count)."""
    fixed = bad = 0
    for i, st in enumerate(inspect(g)):
        if st == "repair_s1": g.s1[i] = [comp(b) for b in g.s2[i][:3]]; g.s1[i].append(sum(g.s1[i]) % 4); fixed += 1
        elif st == "repair_s2": g.s2[i] = [comp(b) for b in g.s1[i][:3]]; g.s2[i].append(sum(g.s2[i]) % 4); fixed += 1
        elif st == "unrepairable": bad += 1
    return fixed, bad
def drift(desired: dict, observed: dict):
    """Unpaired bases between the declared (desired) genome and what is observed: per gene list of base positions that differ."""
    out = {}
    for k in sorted(set(desired) | set(observed)):
        d, o = to_bases(desired.get(k, b"")), to_bases(observed.get(k, b""))
        n = max(len(d), len(o)); diff = [i for i in range(n) if (d[i] if i < len(d) else -1) != (o[i] if i < len(o) else -1)]
        if diff: out[k] = diff
    return out
def splice_plan(desired, observed, allowed):
    """Fixer: one patch per drifted gene, restoring the desired value. Genes outside the boundary are reported, never patched."""
    dr = drift(desired, observed); return [dict(gene=k, to=desired[k], bases_off=len(v)) for k, v in dr.items() if k in allowed and k in desired], [k for k in dr if k not in allowed]

# ---------------- homeostasis: setpoint band, deadband, bounded step, negative feedback
class Homeostat:
    def __init__(self, setpoint, lo, hi, gain=0.5, max_step=1.0): self.sp, self.lo, self.hi, self.gain, self.mx = setpoint, lo, hi, gain, max_step
    def act(self, x):
        if self.lo <= x <= self.hi: return 0.0                    # inside the band: do nothing (no dithering, no wasted energy)
        return max(-self.mx, min(self.mx, self.gain * (self.sp - x)))

# ---------------- immune system: innate rules, adaptive memory, self-tolerance
class Immune:
    def __init__(self, self_set): self.self_set, self.memory, self.log = set(self_set), {}, []
    @staticmethod
    def signature(kind, metric, direction): return hashlib.sha256(f"{kind}|{metric}|{direction}".encode()).hexdigest()[:12]
    def respond(self, event, hard_limit):
        """event: kind, metric, direction, value, target. Returns dict(layer, steps, action)."""
        if event["target"] in self.self_set: r = dict(layer="tolerance", steps=0, action="none (self is protected: no autoimmune attack)")
        elif event["value"] > hard_limit: r = dict(layer="innate", steps=1, action="contain")
        else:
            sig = self.signature(event["kind"], event["metric"], event["direction"])
            if sig in self.memory: r = dict(layer="adaptive-memory", steps=1, action=self.memory[sig])
            else:
                fix = f"fix:{event['metric']}:{event['direction']}"; self.memory[sig] = fix       # learned only after the (simulated) analysis step verified it
                r = dict(layer="adaptive-novel", steps=4, action=fix)
        self.log.append(r); return r

# ---------------- microbiome: workers with a carrying capacity set by free RAM, drained (not killed) when capacity drops
def carrying_capacity(free_ram_gib, per_worker_gib): return max(0, int(free_ram_gib // per_worker_gib))
def pop_step(n, K, r=0.5, rng=None):
    rng = rng or random.Random(0)
    if n > K: return K, n - K                                      # (new population, workers drained gracefully: they finish the current task first)
    grow = r * n * (1 - n / K) if K else 0; g = int(grow) + (rng.random() < grow - int(grow)); return min(K, max(n + g, 1 if K else 0)), 0

# ---------------- cheapest transaction: cost-ordered cascade
def lane_cost(tokens_usd=0.0, joules=0.0, seconds=0.0, usd_per_kwh=0.15, usd_per_second=0.0):
    return tokens_usd + joules * usd_per_kwh / 3.6e6 + seconds * usd_per_second
def expected_cost(order, lanes):
    """lanes: {name: (cost, p_success)}, independent attempts, stop at first verified success."""
    e, surv = 0.0, 1.0
    for n in order: c, p = lanes[n]; e += c * surv; surv *= 1 - p
    return e, 1 - surv
def best_order(lanes): return sorted(lanes, key=lambda n: (lanes[n][0] / lanes[n][1], n))     # ascending cost/success minimizes expected cost

# ---------------- agent-driven DAGs: validate before run, run by dependency with bounded width and bounded retries
def parse_plan(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m: raise ValueError("no JSON object in model output")
    return json.loads(m.group(0))
OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b}
def validate_plan(plan, allowed_actions, budget, max_nodes=30, max_width=8, lanes=None, metrics=None):
    P = []; nodes = plan.get("nodes") if isinstance(plan, dict) else None
    if not isinstance(nodes, list) or not nodes: return ["plan has no nodes"]
    if len(nodes) > max_nodes: P.append(f"{len(nodes)} nodes exceeds {max_nodes}")
    ids = [n.get("id") for n in nodes]
    if len(set(ids)) != len(ids): P.append("duplicate node ids")
    for n in nodes:
        for f in ("id", "action", "check"):
            if not n.get(f): P.append(f"node {n.get('id')} missing {f}")
        c = n.get("check")
        if metrics is not None and c:      # typed, machine-executable check: {metric, op, value}; prose is rejected
            if not (isinstance(c, dict) and c.get("metric") in metrics and c.get("op") in OPS and isinstance(c.get("value"), (int, float))):
                P.append(f"node {n.get('id')} check must be {{metric in {sorted(metrics)}, op in {sorted(OPS)}, numeric value}}, got {str(c)[:60]!r}")
        if n.get("action") and n["action"] not in allowed_actions: P.append(f"node {n['id']} action '{n['action']}' not allowed")
        for d in n.get("deps", []):
            if d not in ids: P.append(f"node {n['id']} depends on unknown {d}")
    if sum(n.get("est_cost", 0) for n in nodes) > budget: P.append(f"estimated cost {sum(n.get('est_cost',0) for n in nodes):.4f} over budget {budget}")
    if not P:
        order = topo(nodes)
        if order is None: P.append("dependency cycle")
        elif max(len(w) for w in waves(nodes)) > max_width: P.append(f"parallel width {max(len(w) for w in waves(nodes))} exceeds {max_width}")
    return P
def topo(nodes):
    indeg = {n["id"]: len(n.get("deps", [])) for n in nodes}; out, ready = [], sorted(i for i, d in indeg.items() if d == 0)
    kids = {n["id"]: [m["id"] for m in nodes if n["id"] in m.get("deps", [])] for n in nodes}
    while ready:
        i = ready.pop(0); out.append(i)
        for k in kids[i]:
            indeg[k] -= 1
            if indeg[k] == 0: ready.append(k); ready.sort()
    return out if len(out) == len(nodes) else None
def waves(nodes):
    done, rest, out = set(), {n["id"]: n for n in nodes}, []
    while rest:
        w = sorted(i for i, n in rest.items() if set(n.get("deps", [])) <= done)
        if not w: break
        out.append(w); done |= set(w); [rest.pop(i) for i in w]
    return out
def run_dag(plan, lanes, run_lane, check, max_width=8):
    """lanes: {name: (cost, p)}; run_lane(lane, node)->output; check(node, output)->bool. Tries lanes cheapest-per-success first; a node fails only after every lane failed."""
    order = best_order(lanes); nodes = {n["id"]: n for n in plan["nodes"]}; state, cost, trace = {}, 0.0, []
    for wave in waves(plan["nodes"]):
        for i in wave[:max_width]:
            n = nodes[i]
            if any(state.get(d) != "ok" for d in n.get("deps", [])): state[i] = "skipped"; trace.append((i, "skipped", None)); continue
            for lane in order:
                cost += lanes[lane][0]; out = run_lane(lane, n)
                if check(n, out): state[i] = "ok"; trace.append((i, "ok", lane)); break
            else: state[i] = "failed"; trace.append((i, "failed", None))
    return dict(state=state, cost=round(cost, 6), trace=trace)
