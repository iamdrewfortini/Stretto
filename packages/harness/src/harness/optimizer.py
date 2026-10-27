# SPDX-License-Identifier: Apache-2.0
"""Pattern-driven optimizer with full provenance. observe -> profile -> decide (recorded) -> boundary check -> rollout -> outcome.
decide() is a pure function of (series, history counts, policy): replaying a stored decision must give the identical result."""
import copy, hashlib, math, statistics
from harness.rollout import KNOBS, Ledger, Rollout
from harness.pattern import profile
from harness.boundary import sha, canon, recurring

POLICY = {"version": "1", "threshold": 0.05,
          "rules": [{"id": "mem-pressure", "metric": "mem_pressure", "knobs": ["mem.swappiness", "zfs.arc_max"]},
                    {"id": "io-latency", "metric": "p99_latency_ms", "knobs": ["disk.io_scheduler"]},
                    {"id": "idle-energy", "metric": "cpu_util", "knobs": ["cpu.governor"]},
                    {"id": "net-retrans", "metric": "retransmit_rate", "knobs": ["net.tcp_buffers"]}],
          "values": {"mem.swappiness": 10, "zfs.arc_max": 8, "disk.io_scheduler": 1, "cpu.governor": 1, "net.tcp_buffers": 16}}

def severity(rule, prof):
    m, pk, q = prof["mean"], prof["peak"], prof["quiet"]
    if rule == "mem-pressure": return min(1.0, max(0.0, (m - 0.7) / 0.3)) if m > 0.7 else 0.0
    if rule == "io-latency": return min(1.0, max(0.0, (pk / m - 1.5) / 3.0)) if m and pk > 1.5 * m else 0.0
    if rule == "idle-energy": return min(1.0, (0.3 - m) / 0.3) if (q is not None and m < 0.3) else 0.0     # only claimed when a quiet cycle is proven
    if rule == "net-retrans": return min(1.0, (m - 0.02) / 0.05) if m > 0.02 else 0.0
    return 0.0

def decide(series, counts, policy=POLICY):
    """series: {metric: [floats]}; counts: {knob: [promoted, failed]}. Pure and deterministic. Returns the decision body (no id)."""
    profs = {m: profile(x) for m, x in series.items()}
    cands = []
    for r in policy["rules"]:
        if r["metric"] not in profs:
            for kn in r["knobs"]: cands.append(dict(knob=kn, rule=r["id"], severity=0.0, p_success=0.0, cls=KNOBS[kn]["cls"], score=-1.0, why=f"metric {r['metric']} not measured: cannot justify"))
            continue
        sev = severity(r["id"], profs[r["metric"]])
        for kn in r["knobs"]:
            s, f = counts.get(kn, [0, 0]); p = (1 + s) / (2 + s + f); cls = KNOBS[kn]["cls"]
            score = round(p * sev - (0.02 if cls == "A" else 0.15), 6)
            cands.append(dict(knob=kn, rule=r["id"], severity=round(sev, 4), p_success=round(p, 4), cls=cls, score=score,
                              why=("no evidence of a problem" if sev == 0 else f"{r['metric']} severity {sev:.2f}, posterior success {p:.2f}, class {cls}")))
    cands.sort(key=lambda c: (-c["score"], c["knob"]))
    top = cands[0] if cands and cands[0]["score"] > policy["threshold"] else None
    return dict(profiles={m: {k: v for k, v in p.items() if k != "cycle"} | {"cycle_p": (p["cycle"] or {}).get("pvalue")} for m, p in profs.items()},
                candidates=cands, chosen=(dict(knob=top["knob"], value=policy["values"][top["knob"]], cls=top["cls"]) if top else None))

class Optimizer:
    def __init__(self, boundary, executor, key_policy=POLICY, code_hash=""):
        self.b, self.ex, self.policy, self.code_hash = boundary, executor, key_policy, code_hash
        self.ledger, self.decisions, self.outcomes, self.evidence = Ledger(), [], {}, {}
        self.counts, self.rollbacks, self.sigs, self.frozen, self.changes_today, self.boundary_hashes = {}, 0, [], False, 0, {boundary.hash}
        self.halted = None
    def unfreeze(self, human): self.frozen = False; self.rollbacks = 0; self.sigs = []; self.ledger.add(event="UNFREEZE", by=human)
    def cycle(self, series, state, units, tick=0, approvals=()):
        bad = self.b.intact()
        if bad: self.halted = bad; self.ledger.add(event="HALT", why=bad); return "HALT"
        ev = {m: sha(x) for m, x in series.items()}
        for m, x in series.items(): self.evidence[ev[m]] = list(x)
        body = decide(series, self.counts, self.policy)
        qp = (body["profiles"].get("load") or {}).get("quiet"); per = (body["profiles"].get("load") or {}).get("period")
        in_quiet = bool(qp and per and (tick % int(round(per))) in qp["phases"])
        d = dict(seq=len(self.decisions), derived_from=(self.decisions[-1]["id"] if self.decisions else None), tick=tick, policy_hash=sha(self.policy), boundary_hash=self.b.hash,
                 code_hash=self.code_hash, inputs=ev, history=copy.deepcopy(self.counts), **body)
        if d["chosen"] is None:
            d["boundary"] = dict(verdict="NONE", violations=[]); d["id"] = sha(d); self.decisions.append(d); self.ledger.add(event="NO_ACTION", decision_id=d["id"]); return "NO_ACTION"
        act = dict(d["chosen"], approved=d["chosen"]["knob"] in approvals)
        st = dict(state, changes_today=self.changes_today, in_flight=0, in_quiet_window=in_quiet, consecutive_rollbacks=self.rollbacks, frozen=self.frozen, recent_signatures=[list(s) for s in self.sigs])
        verdict, viol = self.b.check(act, st); d["boundary"] = dict(verdict=verdict, violations=viol, state=st); d["id"] = sha(d); self.decisions.append(d)
        self.ledger.ctx = dict(decision_id=d["id"])
        if verdict == "DENY": self.ledger.add(event="DENIED", knob=act["knob"], violations=viol); self.ledger.ctx = {}; return "DENIED"
        res = Rollout(self.ex, self.ledger, approvals, n=60).run(act["knob"], act["value"], units); self.ledger.ctx = {}
        self.outcomes[d["id"]] = res; self.changes_today += 1
        s, f = self.counts.get(act["knob"], [0, 0]); self.counts[act["knob"]] = [s + (res == "PROMOTED"), f + (res != "PROMOTED")]
        self.rollbacks = 0 if res == "PROMOTED" else self.rollbacks + 1; self.sigs.append((act["knob"], act["value"], res))
        if self.rollbacks >= self.b.env["breaker"]["max_consecutive_rollbacks"] or recurring(self.sigs): self.frozen = True; self.ledger.add(event="FROZEN", why="breaker or recurrence")
        return res

def replay(d, evidence, policy=POLICY):
    """Recompute a decision from stored evidence; must equal the stored candidates and choice."""
    series = {m: evidence[h] for m, h in d["inputs"].items()}
    b = decide(series, d["history"], policy)
    return b["candidates"] == d["candidates"] and b["chosen"] == d["chosen"]

def verify_provenance(opt):
    """Every APPLY must trace: ledger row -> decision (ALLOW) -> evidence hashes -> policy -> signed envelope. Returns a list of problems."""
    P, byid = [], {d["id"]: d for d in opt.decisions}
    if not opt.ledger.verify(): P.append("ledger hash chain broken")
    prev = None
    for d in opt.decisions:
        body = {k: v for k, v in d.items() if k != "id"}
        if sha(body) != d["id"]: P.append(f"decision {d['seq']} id does not match content")
        if d["derived_from"] != prev: P.append(f"decision {d['seq']} lineage gap")
        prev = d["id"]
        for m, h in d["inputs"].items():
            if h not in opt.evidence or sha(opt.evidence[h]) != h: P.append(f"decision {d['seq']} evidence for {m} missing or altered")
        if d["policy_hash"] != sha(opt.policy): P.append(f"decision {d['seq']} policy differs from current")
        if d["boundary_hash"] not in opt.boundary_hashes: P.append(f"decision {d['seq']} under an unknown envelope")
        if not replay(d, opt.evidence, opt.policy): P.append(f"decision {d['seq']} does not replay")
    for r in opt.ledger.rows:
        if r["event"] == "APPLY":
            d = byid.get(r.get("decision_id"))
            if d is None: P.append("APPLY without a decision"); continue
            if d["chosen"]["knob"] != r["knob"]: P.append("APPLY knob differs from decision")
            if d["boundary"]["verdict"] != "ALLOW": P.append("APPLY under a DENY decision")
    return P
