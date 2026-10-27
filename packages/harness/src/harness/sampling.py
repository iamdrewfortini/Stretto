# SPDX-License-Identifier: Apache-2.0
"""Auto-balancing of sampling effort and thresholds across dimension levels. Stdlib only."""
import math, statistics

def neyman(strata, budget):
    """Optimal allocation of `budget` cost units over strata=[dict(N, sigma, cost)]: n_h ~ N_h*sigma_h/sqrt(c_h), capped at N_h (re-spread), min 2 where sigma>0.
    Minimizes Var(pooled mean) = sum (N_h/N)^2 sigma_h^2 / n_h * (1 - n_h/N_h) subject to sum c_h n_h <= budget."""
    n = [0.0] * len(strata); free = set(range(len(strata))); b = float(budget)
    for i, s in enumerate(strata):
        if s["sigma"] > 0: n[i] = min(2.0, s["N"]); b -= n[i] * s["cost"]
    for _ in range(len(strata) + 1):
        w = {i: strata[i]["N"] * strata[i]["sigma"] / math.sqrt(strata[i]["cost"]) for i in free if strata[i]["sigma"] > 0}
        tot = sum(w[i] * math.sqrt(strata[i]["cost"]) for i in w)
        if tot == 0 or b <= 0: break
        scale = (b + sum(n[i] * strata[i]["cost"] for i in w)) / tot
        new = {i: w[i] * scale for i in w}; over = [i for i in new if new[i] > strata[i]["N"]]
        if not over:
            for i in new: n[i] = max(n[i], new[i]); break
        for i in over: n[i] = strata[i]["N"]; free.discard(i)
        b = budget - sum(n[i] * strata[i]["cost"] for i in range(len(strata)) if n[i])
    return [round(x, 4) for x in n]

def pooled_variance(strata, n):
    N = sum(s["N"] for s in strata)
    return sum((s["N"] / N) ** 2 * s["sigma"] ** 2 / ni * (1 - ni / s["N"]) for s, ni in zip(strata, n) if ni > 0)

def nyquist_interval(period_s, samples_per_cycle=8, floor_s=15, ceil_s=3600, alarm=False):
    """Sampling interval for a metric whose dominant cycle is period_s. >= 2/cycle is the Nyquist limit; 8 keeps amplitude error small. Halved after a change alarm."""
    t = period_s / samples_per_cycle; t = t / 2 if alarm else t
    return min(ceil_s, max(floor_s, t))

class QuantileThreshold:
    """Streaming quantile by stochastic approximation: theta += g_t * (1[x>theta] - (1-q)); g_t = max(gmin, c/t^0.6) * scale. Self-tunes to the metric's own distribution."""
    def __init__(self, q, scale, c=2.0, gmin=0.01):
        self.q, self.scale, self.c, self.gmin, self.t, self.theta = q, scale, c, gmin, 0, None
    def update(self, x):
        self.t += 1
        if self.theta is None: self.theta = x; return self.theta
        g = max(self.gmin, self.c / self.t ** 0.6) * self.scale
        self.theta += g * ((1.0 if x > self.theta else 0.0) - (1 - self.q)); return self.theta

def rate_balance(samples_per_week, target_per_week):
    """Per-level exceedance quantile q_d so every level proposes about target_per_week candidates: q = 1 - target/samples."""
    return {k: max(0.5, min(0.9999, 1 - target_per_week / n)) for k, n in samples_per_week.items()}

class PrecisionController:
    """Adjusts the quantile q so the promote rate of proposals tracks `target`: promoted too rarely -> stricter (q up); too often -> looser."""
    def __init__(self, q=0.9, target=0.7, gain=0.02): self.q, self.target, self.gain = q, target, gain
    def update(self, promoted, proposed):
        if proposed: self.q = min(0.999, max(0.5, self.q + self.gain * (self.target - promoted / proposed)))
        return self.q
