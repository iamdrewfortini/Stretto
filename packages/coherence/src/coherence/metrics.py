# SPDX-License-Identifier: Apache-2.0
"""Distance from coherence, D, and the direction it gives every neuron (micro cell). Stdlib only.
Each axis has a gap g_k in [0,1): 0 = at the achievable optimum, toward 1 = far from it. D = sqrt(sum_k w_k g_k^2) over MEASURED axes; an unmeasured axis contributes 0,
so with missing axes D is a LOWER BOUND and is reported as such. Direction = -grad D, projected on the axes a cell owns, scored per unit action cost."""
import math, statistics

AXES = ("speed", "energy", "balance", "scale", "intent")
W = {k: 0.2 for k in AXES}          # equal weights: a POLICY choice, stated, not derived

def jain(x):
    """Jain fairness index of non-negative loads: 1 = perfectly even, 1/n = one unit carries everything."""
    s, q = sum(x), sum(v * v for v in x); return 1.0 if q == 0 else s * s / (len(x) * q)
def ratio_gap(actual, bound):
    """Gap from a certified lower bound: 0 at the bound, 1 - bound/actual otherwise."""
    return 0.0 if actual <= bound else 1.0 - bound / actual
def finish_time_bound(critical_path, total_work, servers): return max(critical_path, total_work / servers)       # the two scheduling lower bounds
def energy_proportionality_gap(power_w, utilization, peak_w):
    """Ideal draw is utilization*peak. Gap = share of actual power that proportionality would not need."""
    return 0.0 if power_w <= 0 else max(0.0, (power_w - utilization * peak_w) / power_w)
def balance_gap(loads, pressure=None):
    """loads: {resource: [load/capacity per unit]} (ratios, NOT absolute amounts: balance means equally loaded relative to capacity); pressure: {resource: weight} (e.g. commitment ratio of the binding resource). Pressure-weighted mean of 1-Jain."""
    p = pressure or {r: 1.0 for r in loads}; tot = sum(p[r] for r in loads); return sum(p[r] * (1 - jain(v)) for r, v in loads.items()) / tot
def scale_gap(capacities, throughputs):
    """Least-squares slope of ln(throughput) on ln(capacity); ideal = 1 (linear scaling). Gap = min(1, |slope-1|). Needs >=3 levels."""
    if len(capacities) < 3: return None
    x, y = [math.log(c) for c in capacities], [math.log(t) for t in throughputs]; mx, my = statistics.fmean(x), statistics.fmean(y)
    b = sum((a - mx) * (c - my) for a, c in zip(x, y)) / sum((a - mx) ** 2 for a in x); return min(1.0, abs(b - 1.0))
def intent_gap(known_bits): return 1.0 - known_bits / 6.0

def distance(gaps, weights=W):
    """gaps: {axis: float | None}. None = not measured."""
    measured = {k: g for k, g in gaps.items() if g is not None}; missing = [k for k in weights if k not in measured]
    D = math.sqrt(sum(weights[k] * g * g for k, g in measured.items()))
    return dict(D=round(D, 6), measured=measured, missing=missing, lower_bound=bool(missing), contribution={k: round(weights[k] * g * g, 6) for k, g in measured.items()})

def gradient(gaps, weights=W):
    D = distance(gaps, weights)["D"]
    return {k: (weights[k] * g / D if D > 0 else 0.0) for k, g in gaps.items() if g is not None}

class EffectModel:
    """effect[action][axis] = expected change of that axis gap per action (negative = improves). Learned online from observed before/after gaps (EWMA)."""
    def __init__(self, prior=None, alpha=0.3): self.e, self.n, self.a = {a: dict(v) for a, v in (prior or {}).items()}, {}, alpha
    def observe(self, action, before, after):
        row = self.e.setdefault(action, {})
        for k in before:
            if k in after: d = after[k] - before[k]; row[k] = (1 - self.a) * row.get(k, d) + self.a * d if k in row else d
        self.n[action] = self.n.get(action, 0) + 1

def direction(gaps, effects, costs, owned=None, weights=W, eps=1e-3):
    """Ranked descent directions for a neuron. score(action) = -sum_k grad_k * effect[action][k] / cost[action], over axes the cell owns.
    Returns [] ('hold') when D < eps or no action is expected to reduce D."""
    if distance(gaps, weights)["D"] < eps: return []
    g = gradient(gaps, weights); out = []
    for a, eff in effects.items():
        s = -sum(g.get(k, 0.0) * v for k, v in eff.items() if (owned is None or k in owned)) / max(costs.get(a, 1.0), 1e-9)
        if s > 1e-12: out.append((a, s))
    return sorted(out, key=lambda t: -t[1])
