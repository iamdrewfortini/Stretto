# SPDX-License-Identifier: Apache-2.0
"""Signal tracking, attention shifting/focusing, and intentional-focus tracking for a micro cell. Stdlib only."""
import math

class Tracker:
    """EWMA mean/variance tracker. update(x) returns the standardized innovation z (surprise) computed BEFORE the update; 0 during warm-up."""
    def __init__(self, alpha=0.05, warm=20): self.a, self.warm, self.n, self.m, self.v = alpha, warm, 0, 0.0, 1.0
    def update(self, x):
        z = 0.0
        if self.n >= self.warm: z = (x - self.m) / math.sqrt(self.v + 1e-9)
        if self.n == 0: self.m = x; self.v = 1e-6
        else:
            d = x - self.m; self.m += self.a * d; self.v = (1 - self.a) * (self.v + self.a * d * d)
        self.n += 1; return z

class Attention:
    """salience_i = EWMA(|z_i|) * relevance_i / cost_i  (relevance 1 for intent signals, `leak` otherwise).
    SHIFT when the best candidate beats the current focus by `switch_cost` (hysteresis); PREEMPT when an off-intent signal exceeds `preempt_z` (safety interrupt).
    FOCUS: temperature T decays while focus holds (sharper attention), resets to tmax on a shift. Weights = softmax(salience / T)."""
    def __init__(self, signals, intent, cost=None, leak=0.1, beta=0.3, switch_cost=None, switch_sigmas=2.5, tmin=0.25, tmax=2.0, preempt_z=8.0, drift_tau=0.5, drift_n=5):
        self.names, self.intent, self.cost = list(signals), set(intent), cost or {}
        self.leak, self.beta, self.tmin, self.tmax, self.pz, self.dtau, self.dn = leak, beta, tmin, tmax, preempt_z, drift_tau, drift_n
        # Derived hysteresis: under noise |z| has sd ~0.6; its EWMA has sd 0.6*sqrt(beta/(2-beta)); the gap of two signals has sd*sqrt(2). Switch only beyond `switch_sigmas` of that.
        self.sw = switch_cost if switch_cost is not None else switch_sigmas * math.sqrt(2) * 0.6 * math.sqrt(beta / (2 - beta))
        self.tr = {n: Tracker() for n in self.names}; self.sal = {n: 0.0 for n in self.names}; self.focus = next(iter(self.intent), self.names[0]); self.T = tmax
        self.dwell = self.switches = self.steps = self.low_align = 0; self.history = []
    def step(self, obs):
        self.steps += 1; z = {n: self.tr[n].update(obs[n]) for n in self.names}; pre = None
        for n in self.names:
            self.sal[n] = (1 - self.beta) * self.sal[n] + self.beta * abs(z[n]) * (1.0 if n in self.intent else self.leak) / self.cost.get(n, 1.0)
            if n not in self.intent and abs(z[n]) > self.pz and (pre is None or abs(z[n]) > abs(z[pre])): pre = n
        cand = max(self.names, key=lambda n: (self.sal[n], n == self.focus)); shifted = False
        if pre is not None and pre != self.focus: self.focus, shifted = pre, True
        elif cand != self.focus and self.sal[cand] > self.sal[self.focus] + self.sw: self.focus, shifted = cand, True
        if shifted: self.switches += 1; self.T = self.tmax; self.dwell = 0
        else: self.dwell += 1; self.T = max(self.tmin, self.T * 0.92)
        e = {n: math.exp((self.sal[n] - max(self.sal.values())) / self.T) for n in self.names}; Z = sum(e.values()); w = {n: e[n] / Z for n in self.names}
        w[self.focus] += 0.0; ent = -sum(p * math.log(p) for p in w.values() if p > 0); align = sum(w[n] for n in self.intent)
        self.low_align = self.low_align + 1 if align < self.dtau else 0
        row = dict(step=self.steps, focus=self.focus, shifted=shifted, preempted=bool(shifted and pre == self.focus), entropy=round(ent, 4), alignment=round(align, 4), drift=self.low_align >= self.dn, dwell=self.dwell, weights={n: round(p, 4) for n, p in w.items()})
        self.history.append(row); return row
    def intent_report(self):
        h = self.history; return dict(steps=len(h), switch_rate=self.switches / max(1, len(h)), mean_alignment=sum(r["alignment"] for r in h) / max(1, len(h)), drift_steps=sum(r["drift"] for r in h))
