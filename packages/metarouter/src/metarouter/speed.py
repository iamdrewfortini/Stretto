# SPDX-License-Identifier: Apache-2.0
"""Speed-aware routing. Objective per job: J = E[cost] + price_per_s * E[time to a verified result] + P(fail) * fail_penalty.
Time per attempt = service time + queueing wait (Erlang C, M/M/c). Strategies: sequential cascade or race of the top-k endpoints (first verified result wins, others cancelled)."""
import itertools, math, time
from concurrent.futures import ThreadPoolExecutor, FIRST_COMPLETED, wait
from metarouter.router import Endpoint, MetaRouter

def erlang_c_wait(lam, mu, c):
    """Mean queueing delay Wq of an M/M/c queue (arrival rate lam, per-server rate mu, c servers). inf if unstable."""
    a = lam / mu; rho = a / c
    if lam <= 0: return 0.0
    if rho >= 1: return math.inf
    top = a ** c / math.factorial(c) / (1 - rho); pw = top / (sum(a ** k / math.factorial(k) for k in range(c)) + top)
    return pw / (c * mu - lam)

class TimedEndpoint(Endpoint):
    def __init__(self, name, model, status, cost, service_s, servers=1, arrival_per_s=0.0, **kw):
        super().__init__(name, model, status, cost, **kw); self.svc, self.c, self.lam = service_s, servers, arrival_per_s
    def t_eff(self): return self.svc + erlang_c_wait(self.lam, 1 / self.svc, self.c)
    def record_time(self, secs): self.svc = (1 - self.alpha) * self.svc + self.alpha * secs

def seq_metrics(order, task):
    cost = time_ = 0.0; surv = 1.0
    for e in order: cost += surv * e.cost; time_ += surv * e.t_eff(); surv *= 1 - e.p(task)
    return cost, time_, 1 - surv
def race_metrics(eps, task):
    """Exact over all success patterns (n<=5). Endpoint i bills cost_i * min(1, T/t_i): it is cancelled when the first verified result arrives at T."""
    n = len(eps); ts = [e.t_eff() for e in eps]; ps = [e.p(task) for e in eps]; E_c = E_t = P_ok = 0.0
    for pat in itertools.product((0, 1), repeat=n):
        pr = math.prod(p if s else 1 - p for p, s in zip(ps, pat)); T = min((t for t, s in zip(ts, pat) if s), default=max(ts))
        E_t += pr * T; E_c += pr * sum(e.cost * min(1.0, T / t) for e, t in zip(eps, ts)); P_ok += pr * any(pat)
    return E_c, E_t, P_ok

class SpeedRouter(MetaRouter):
    """mode 'prod': gateway only. mode 'test': the interactive Muse subscription lane (via='direct') is also allowed, and rows are marked with the lane used."""
    def __init__(self, endpoints, mode="prod", **kw):
        super().__init__(endpoints, require_gateway=(mode == "prod"), **kw); self.mode = mode
    def plan(self, role, task, price_per_s, fail_penalty=1.0, max_race=3):
        el = self.eligible(role)
        if not el: return None
        order = sorted(el, key=lambda e: ((e.cost + price_per_s * e.t_eff()) / max(e.p(task), 1e-9), e.name)); opts = []
        c, t, ok = seq_metrics(order, task); opts.append(dict(strategy="sequential", eps=order, cost=c, time=t, p_ok=ok))
        for k in range(2, min(max_race, len(order)) + 1):
            c, t, ok = race_metrics(order[:k], task); opts.append(dict(strategy=f"race{k}", eps=order[:k], cost=c, time=t, p_ok=ok))
        for o in opts: o["J"] = o["cost"] + price_per_s * o["time"] + (1 - o["p_ok"]) * fail_penalty
        return min(opts, key=lambda o: (o["J"], o["strategy"]))
    def execute(self, plan, task, run, check):
        t0 = time.perf_counter()
        if plan["strategy"] == "sequential":
            for e in plan["eps"]:
                s = time.perf_counter(); out = run(e); dt = time.perf_counter() - s; ok = bool(check(out)); e.record(task, ok, e.cost); e.record_time(dt)
                if ok: return dict(status="OK", endpoint=e.name, lane=e.via, secs=time.perf_counter() - t0, strategy="sequential", output=out)
            return dict(status="FAILED", secs=time.perf_counter() - t0, strategy="sequential")
        with ThreadPoolExecutor(len(plan["eps"])) as ex:
            futs = {ex.submit(run, e): e for e in plan["eps"]}; pending = set(futs)
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for f in done:
                    e = futs[f]; out = f.result(); ok = bool(check(out)); e.record(task, ok, e.cost)
                    if ok:
                        for g in pending: g.cancel()
                        return dict(status="OK", endpoint=e.name, lane=e.via, secs=time.perf_counter() - t0, strategy=plan["strategy"], output=out)
        return dict(status="FAILED", secs=time.perf_counter() - t0, strategy=plan["strategy"])
