#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""tunefabric: measure -> canary -> staged rollout -> verify -> promote | rollback, for infrastructure knobs.
Design rules (WF-13D): only checked changes count; every change has a restore point; irreversible edges are S2 (human approval).
Stdlib only. This module never executes apply/restore commands: an Executor is injected (Simulator in tests, SSH/API in production,
and production use is gated by approvals.json). Registry commands are UNTESTED against real hardware."""
import hashlib, json, math, random, statistics, time

# ---------- knob registry (declarative). cls: A auto-reversible runtime | B needs approval (persistent or link-affecting) | C never automated
# scope = containment level; units listed small-to-large (rollout order follows dimension d ascending)
KNOBS = {
 "mem.swappiness":      dict(cls="A", scope="node",    obj=("mem_pressure", "down"),   guard=[("p99_latency_ms", .05)],            apply="sysctl -w vm.swappiness={v}", restore="sysctl -w vm.swappiness={old}"),
 "zfs.arc_max":         dict(cls="A", scope="node",    obj=("read_iops", "up"),        guard=[("mem_free_gib", .5), ("mem_pressure", .05)], apply="echo {v} > /sys/module/zfs/parameters/zfs_arc_max", restore="echo {old} > /sys/module/zfs/parameters/zfs_arc_max"),
 "ceph.osd_mem_target": dict(cls="A", scope="node",    obj=("osd_latency_ms", "down"), guard=[("mem_free_gib", .5)],                apply="ceph config set osd/host:{host} osd_memory_target {v}", restore="ceph config rm osd/host:{host} osd_memory_target"),
 "disk.io_scheduler":   dict(cls="A", scope="node",    obj=("p99_latency_ms", "down"), guard=[("read_iops", .03)],                  apply="echo {v} > /sys/block/{dev}/queue/scheduler", restore="echo {old} > /sys/block/{dev}/queue/scheduler"),
 "net.tcp_buffers":     dict(cls="A", scope="node",    obj=("net_goodput_mbps", "up"), guard=[("retransmit_rate", .05)],            apply="sysctl -w net.core.rmem_max={v}", restore="sysctl -w net.core.rmem_max={old}"),
 "cpu.governor":        dict(cls="A", scope="node",    obj=("joules_per_op", "down"),  guard=[("p99_latency_ms", .05)],             apply="cpupower frequency-set -g {v}", restore="cpupower frequency-set -g {old}"),
 "ceph.balancer_upmap": dict(cls="B", scope="cluster", obj=("osd_util_stddev", "down"),guard=[("misplaced_ratio", .05), ("osd_latency_ms", .05)], apply="ceph balancer mode upmap; ceph balancer on", restore="ceph balancer off"),
 "net.mtu":             dict(cls="B", scope="node",    obj=("net_goodput_mbps", "up"), guard=[("retransmit_rate", .02)],            apply="ip link set {nic} mtu {v}", restore="ip link set {nic} mtu {old}"),
 "zfs.recordsize":      dict(cls="B", scope="node",    obj=("read_iops", "up"),        guard=[("p99_latency_ms", .05)],             apply="zfs set recordsize={v} {ds}", restore="(new writes only: cannot restore existing blocks)"),
 "placement.migrate":   dict(cls="B", scope="guest",   obj=("p99_latency_ms", "down"), guard=[("mem_free_gib", .5)],                apply="qm migrate {vmid} {node} --online", restore="qm migrate {vmid} {orig} --online"),
 "disk.partition":      dict(cls="C", scope="node",    obj=("n/a", "up"), guard=[], apply="(never automated: disk and partition tools)", restore="n/a"),
 "pve.snapshot_backup": dict(cls="C", scope="cluster", obj=("n/a", "up"), guard=[], apply="(never automated: Proxmox power, snapshot, backup)", restore="n/a"),
}
Z = {0.05: 1.645, 0.025: 1.960, 0.01: 2.326, 0.80: 0.842, 0.90: 1.282}

def need_n(sigma, delta, alpha=0.025, power=0.80):
    """Samples per arm to detect delta with one-sided alpha: n = ((z_a+z_b) sigma / delta)^2."""
    return math.ceil(((Z[alpha] + Z[power]) * sigma / delta) ** 2)

# ---------- hash-chained ledger
class Ledger:
    def __init__(self): self.rows = []; self.ctx = {}      # ctx (e.g. decision_id) is stamped on every row
    def add(self, **row):
        row = dict(self.ctx, **row)
        prev = self.rows[-1]["h"] if self.rows else "0" * 64
        body = json.dumps(dict(row, prev=prev), sort_keys=True, default=str)
        self.rows.append(dict(row, prev=prev, h=hashlib.sha256(body.encode()).hexdigest()))
    def verify(self):
        prev = "0" * 64
        for r in self.rows:
            body = json.dumps({k: v for k, v in r.items() if k != "h"}, sort_keys=True, default=str)
            if r["prev"] != prev or hashlib.sha256(body.encode()).hexdigest() != r["h"]: return False
            prev = r["h"]
        return True

# ---------- statistics
def did(before_t, after_t, before_c, after_c):
    """Difference-in-differences with a concurrent control: removes common drift. Returns (effect, standard error)."""
    m = lambda x: statistics.fmean(x); v = lambda x: statistics.variance(x) / len(x)
    return (m(after_t) - m(before_t)) - (m(after_c) - m(before_c)), math.sqrt(v(before_t) + v(after_t) + v(before_c) + v(after_c))

# ---------- rollout engine
class Rollout:
    def __init__(self, executor, ledger, approvals=(), n=60, alpha=0.025, dry_run=True):
        self.ex, self.led, self.appr, self.n, self.alpha, self.dry = executor, ledger, set(approvals), n, alpha, dry_run

    def run(self, knob, value, units, stages=None):
        k = KNOBS[knob]; obj, direction = k["obj"]
        if k["cls"] == "C": self.led.add(knob=knob, event="REFUSED", why="class C is never automated"); return "REFUSED"
        if k["cls"] == "B" and knob not in self.appr: self.led.add(knob=knob, event="WAITING_APPROVAL"); return "WAITING_APPROVAL"
        if not self.ex.quiet(): self.led.add(knob=knob, event="DEFERRED", why="cluster not quiescent (recovery, backup or rebalance)"); return "DEFERRED"
        units = list(units)
        if len(units) < 2: self.led.add(knob=knob, event="UNCONTROLLED", why="no concurrent control unit; needs human review"); return "UNCONTROLLED"
        hold = units[-max(1, len(units) // 10):]; body = units[:len(units) - len(hold)]       # holdout stays untreated through every measured stage
        stages = stages or [body[:1], body[1:max(2, len(body) // 3 + 1)], body[max(2, len(body) // 3 + 1):]]
        done, sign = [], (1 if direction == "up" else -1)
        for si, stage in enumerate([s for s in stages if s]):
            ctrl = [u for u in units if u not in done and u not in stage]     # always includes the holdout
            bt = self.ex.sample(stage, obj, self.n); bc = self.ex.sample(ctrl, obj, self.n)
            gbase = {g: (self.ex.sample(stage, g, self.n), self.ex.sample(ctrl, g, self.n)) for g, _ in k["guard"]}   # ALL baselines before apply
            self.led.add(knob=knob, event="APPLY", stage=si, units=stage, value=value, restore=k["restore"], dry=self.dry)
            self.ex.apply(knob, stage, value)
            at = self.ex.sample(stage, obj, self.n); ac = self.ex.sample(ctrl, obj, self.n)
            eff, se = did(bt, at, bc, ac); z = sign * eff / se
            bad = []
            for g, margin in k["guard"]:       # guard metrics: upper confidence bound on harm must stay under margin * baseline level
                gbt, gbc = gbase[g]
                gat, gac = self.ex.sample(stage, g, self.n), self.ex.sample(ctrl, g, self.n)
                ge, gse = did(gbt, gat, gbc, gac); base = abs(statistics.fmean(gbt)) or 1
                worse = (ge if g in ("p99_latency_ms", "osd_latency_ms", "retransmit_rate", "mem_pressure", "misplaced_ratio") else -ge)   # sign: higher is worse for these
                if worse + Z[0.05] * gse > margin * base: bad.append(g)
            ok = z > Z[self.alpha] / 1.0 and not bad
            self.led.add(knob=knob, event="EVAL", stage=si, effect=round(eff, 4), se=round(se, 4), z=round(z, 2), guard_violations=bad, verdict="PASS" if ok else "FAIL")
            if not ok:
                self.ex.restore(knob, done + stage)
                self.led.add(knob=knob, event="ROLLBACK", units=done + stage, reason=("guard " + ",".join(bad)) if bad else "objective not proven")
                return "ROLLED_BACK"
            done += stage
        # holdout: no concurrent control is left, so only a guard check against its own pre-change baseline (drift caveat noted in ledger)
        gb = {g: self.ex.sample(hold, g, self.n) for g, _ in k["guard"]}
        self.ex.apply(knob, hold, value); self.led.add(knob=knob, event="APPLY", stage="holdout", units=hold, value=value, restore=k["restore"], dry=self.dry)
        bad = []
        for g, margin in k["guard"]:
            ga = self.ex.sample(hold, g, self.n); delta = statistics.fmean(ga) - statistics.fmean(gb[g]); base = abs(statistics.fmean(gb[g])) or 1
            se = math.sqrt(statistics.variance(ga) / len(ga) + statistics.variance(gb[g]) / len(ga)); worse = delta if g in ("p99_latency_ms", "osd_latency_ms", "retransmit_rate", "mem_pressure", "misplaced_ratio") else -delta
            if worse + Z[0.05] * se > margin * base: bad.append(g)
        self.led.add(knob=knob, event="EVAL", stage="holdout", guard_violations=bad, verdict="FAIL" if bad else "PASS", note="guard-only, before/after, drift not controlled")
        if bad:
            self.ex.restore(knob, done + hold); self.led.add(knob=knob, event="ROLLBACK", units=done + hold, reason="holdout guard " + ",".join(bad)); return "ROLLED_BACK"
        self.led.add(knob=knob, event="PROMOTED", units=done + hold); return "PROMOTED"

# ---------- deterministic fleet simulator (stand-in for SSH/API)
class Simulator:
    def __init__(self, seed, effects, drift=0.0, quiet=True):
        self.r = random.Random(seed); self.effects = effects   # effects[(knob)] = {metric: fractional change when applied}
        self.applied = {}; self.t = 0; self.drift = drift; self._quiet = quiet; self.log = []
        self.base = dict(mem_pressure=.5, read_iops=1000, osd_latency_ms=4, p99_latency_ms=20, net_goodput_mbps=800, joules_per_op=2.0, osd_util_stddev=8, misplaced_ratio=.01, retransmit_rate=.01, mem_free_gib=5)
    def quiet(self): return self._quiet
    def sample(self, units, metric, n, before=False):
        out = []
        for _ in range(n):
            self.t += 1; u = self.r.choice(units); b = self.base[metric] * (1 + self.drift * self.t / 1000)
            for knob, us in self.applied.items():
                if u in us: b *= 1 + self.effects.get(knob, {}).get(metric, 0)
            out.append(b * (1 + self.r.gauss(0, .05)))
        return out
    def apply(self, knob, units, value): self.applied.setdefault(knob, set()).update(units); self.log.append(("apply", knob, tuple(units)))
    def restore(self, knob, units): self.applied.get(knob, set()).difference_update(units); self.log.append(("restore", knob, tuple(units)))
