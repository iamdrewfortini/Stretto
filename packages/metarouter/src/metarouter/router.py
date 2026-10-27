# SPDX-License-Identifier: Apache-2.0
"""Routers over Meta-only endpoints: role router (planner/coder/embed/...), embedding store, prediction router. Stdlib only.
A router never falls back to a non-Meta model: with no eligible endpoint it returns NO_SIGNAL and names what is missing (WF-13D EXPLICIT-STOP)."""
import heapq, math, random, statistics
from metarouter.policy import CATALOG, EMBED_CANDIDATES

class Endpoint:
    """Per-task-type success counts (Beta posterior) and an online cost estimate (EWMA of observed cost). Specialties are LEARNED, not declared."""
    def __init__(self, name, model, status, cost, roles=None, paid_credits=False, alpha=0.3, via="gateway"):
        if model not in CATALOG: raise ValueError(f"non-Meta or unknown model refused: {model}")
        self.name, self.model, self.status, self.cost, self.paid, self.alpha, self.via = name, model, status, cost, paid_credits, alpha, via
        self.roles = set(roles if roles is not None else CATALOG[model]["roles"]); self.provider = CATALOG[model]["provider"]; self.stats = {}
    def p(self, task, rng=None):
        w, l = self.stats.get(task, [1, 1]); return rng.betavariate(w, l) if rng else w / (w + l)
    def record(self, task, ok, cost):
        w, l = self.stats.get(task, [1, 1]); self.stats[task] = [w + ok, l + (not ok)]; self.cost = (1 - self.alpha) * self.cost + self.alpha * cost

class MetaRouter:
    """status: live | not-deployed | unverified. paid endpoints (Meta Model API credits) are off unless allow_credits (the 150 credits are reserved).
    Choice rule: order by expected cost-per-success c/p for THIS task type (optimal for independent attempts); Thompson sampling (explore=True) samples p so a new
    specialist is discovered. Cheapest model that can do the job wins; a specialist wins exactly when its c/p is lower."""
    def __init__(self, endpoints, allow_credits=False, seed=0, require_gateway=True):
        bad = [e.name for e in endpoints if e.model not in CATALOG]
        if bad: raise ValueError(f"non-Meta or unknown model(s) refused at registration: {bad}")
        self.eps, self.allow_credits, self.history, self.rng, self.require_gateway = list(endpoints), allow_credits, [], random.Random(seed), require_gateway
    def eligible(self, role):
        return [e for e in self.eps if role in e.roles and e.status == "live" and (self.allow_credits or not e.paid) and (e.via == "gateway" or not self.require_gateway)]
    def order(self, role, task="any", explore=False):
        r = self.rng if explore else None; return sorted(self.eligible(role), key=lambda e: (e.cost / max(e.p(task, r), 1e-9), e.name))
    def route(self, role, run, check, task="any", explore=False, measure=None):
        if role == "embed" and not any(e.status == "live" for e in self.eps if "embed" in e.roles):
            return dict(status="NO_SIGNAL", why="no live, evaluated Meta embedding endpoint (Meta Model API has no embeddings route); candidates: " + "; ".join(f"{k}: {v}" for k, v in EMBED_CANDIDATES.items()))
        order = self.order(role, task, explore)
        if not order:
            why = [f"{e.name}: {e.status}" + (" (paid credits off)" if e.paid and not self.allow_credits else "") for e in self.eps if role in e.roles]
            return dict(status="NO_SIGNAL", why=f"no eligible Meta endpoint for role '{role}': " + ("; ".join(why) or "none registered"))
        spent = 0.0
        for e in order:
            out = run(e); c = measure(e, out) if measure else e.cost; spent += c; ok = bool(check(out)); e.record(task, ok, c); self.history.append((role, task, e.name, ok, c))
            if ok: return dict(status="OK", endpoint=e.name, model=e.model, cost=round(spent, 6), output=out)
        return dict(status="FAILED", cost=round(spent, 6), tried=[e.name for e in order])

# ---------------- embedding store: one store, spaces tagged by (model, dim, version); never compare across spaces
class EmbeddingStore:
    def __init__(self): self.spaces = {}
    def add(self, model, version, ident, vec):
        key = (model, len(vec), version); s = self.spaces.setdefault(key, dict(ids=[], full=[], bits=[]))
        n = math.sqrt(sum(x * x for x in vec)) or 1.0; v = [x / n for x in vec]
        s["ids"].append(ident); s["full"].append(v); s["bits"].append(sum(1 << i for i, x in enumerate(v) if x > 0))
    def _space(self, model, version, q):
        key = (model, len(q), version)
        if key not in self.spaces: raise KeyError(f"no space {key}: vectors from different models/dims/versions are never compared")
        return self.spaces[key]
    def search(self, model, version, q, k=10, shortlist=10):
        s = self._space(model, version, q); n = math.sqrt(sum(x * x for x in q)) or 1.0; q = [x / n for x in q]; qb = sum(1 << i for i, x in enumerate(q) if x > 0)
        cand = heapq.nsmallest(min(len(s["ids"]), k * shortlist), range(len(s["ids"])), key=lambda i: bin(s["bits"][i] ^ qb).count("1"))      # binary (Hamming) prefilter
        top = sorted(cand, key=lambda i: -sum(a * b for a, b in zip(q, s["full"][i])))[:k]                                                    # full-precision re-rank
        return [s["ids"][i] for i in top]
    def exact(self, model, version, q, k=10):
        s = self._space(model, version, q); n = math.sqrt(sum(x * x for x in q)) or 1.0; q = [x / n for x in q]
        return [s["ids"][i] for i in sorted(range(len(s["ids"])), key=lambda i: -sum(a * b for a, b in zip(q, s["full"][i])))[:k]]

# ---------------- prediction router: exponential weights (Hedge) over predictors, with an admission gate for learned model predictors
class PredictionRouter:
    def __init__(self, names, horizon):
        self.names, self.w, self.eta = list(names), {n: 1.0 for n in names}, math.sqrt(8 * math.log(len(names)) / horizon)
        self.loss_sum, self.alg_loss = {n: 0.0 for n in names}, 0.0
    def predict(self, forecasts):
        tot = sum(self.w.values()); return sum(self.w[n] / tot * forecasts[n] for n in self.names)
    def update(self, forecasts, truth, scale):
        tot = sum(self.w.values()); mix = sum(self.w[n] / tot * min(1.0, abs(forecasts[n] - truth) / scale) for n in self.names); self.alg_loss += mix
        for n in self.names:
            l = min(1.0, abs(forecasts[n] - truth) / scale); self.loss_sum[n] += l; self.w[n] *= math.exp(-self.eta * l)
    def regret(self): return self.alg_loss - min(self.loss_sum.values())
    def bound(self, T): return math.sqrt(T * math.log(len(self.names)) / 2)
def admit(model_err, baseline_err, margin=0.10, min_n=30):
    """A learned (Meta-model) predictor joins only if its holdout error beats the best baseline by `margin` on at least min_n points."""
    if len(model_err) < min_n: return False, f"need {min_n} holdout points"
    m, b = statistics.fmean(model_err), statistics.fmean(baseline_err); return (m <= (1 - margin) * b), f"model {m:.4f} vs baseline {b:.4f}"
