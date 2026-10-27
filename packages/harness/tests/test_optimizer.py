# SPDX-License-Identifier: Apache-2.0
import math, os, random, tempfile, unittest, copy
from harness.boundary import Boundary, sign, sha, file_hashes, recurring
from harness.optimizer import Optimizer, decide, replay, verify_provenance, POLICY
from harness.pattern import dominant_period, quiet_phases, cusum_change, profile
from harness.rollout import Simulator
KEY = b"test-key-not-a-secret"
U = [f"g{i}" for i in range(12)]

def diurnal(days=7, T=24, amp=0.4, base=0.5, noise=0.03, seed=1, shift_at=None, shift=0.0):
    r = random.Random(seed); x = []
    for t in range(days * T):
        v = base + amp * math.sin(2 * math.pi * (t % T) / T) + r.gauss(0, noise) + (shift if shift_at is not None and t >= shift_at else 0)
        x.append(v)
    return x
def env(extra=None, protected=None):
    e = dict(allowed_knobs={"mem.swappiness": {"min": 1, "max": 60}, "zfs.arc_max": {"min": 2, "max": 16}, "disk.io_scheduler": {"min": 0, "max": 3}, "cpu.governor": {"min": 0, "max": 3}, "net.tcp_buffers": {"min": 4, "max": 64}},
             forbidden_classes=["C"], max_changes_per_day=3, max_concurrent=1, require_quiet=True, floors={"min_free_ram_gib": 4, "max_cpu_overcommit": 1.5},
             budget={"max_p99_regression_pct": 5, "max_energy_increase_pct": 0}, breaker={"max_consecutive_rollbacks": 2}, protected=protected or {})
    e.update(extra or {}); return e
def bnd(e=None): e = e or env(); return Boundary(e, sign(e, KEY), KEY)
OKSTATE = dict(free_ram_gib=9, cpu_overcommit=1.0)
def series_mem(shift=False):
    s = diurnal(base=0.78, amp=0.1); return {"mem_pressure": s, "load": diurnal(base=0.5, amp=0.4, seed=2)}
def tick_in_quiet(series):
    p = profile(series["load"]); return p["quiet"]["phases"][0] + 24 * 6      # a tick whose phase is quiet

class Patterns(unittest.TestCase):
    def test_period_recovered(self): r = dominant_period(diurnal(), 3); self.assertAlmostEqual(r["period"], 24); self.assertTrue(r["significant"])
    def test_noise_has_no_pattern(self):
        r = random.Random(5); hits = sum(dominant_period([r.gauss(0, 1) for _ in range(168)], 3, perms=49, seed=s)["significant"] for s in range(20)); self.assertLessEqual(hits, 3)   # ~5% expected
    def test_quiet_windows_hold_out(self):
        q = quiet_phases(diurnal(days=8), 24); self.assertGreaterEqual(q["holdout_hit_rate"], 0.9)
        self.assertTrue(all(p >= 12 for p in q["phases"]))        # sin trough is phases 13..23
    def test_no_quiet_claim_without_cycle(self):
        r = random.Random(9); self.assertIsNone(profile([r.gauss(0, 1) for _ in range(168)])["quiet"])
    def test_change_point(self):
        x = diurnal(days=10, amp=0.0, noise=0.03, shift_at=130, shift=0.3); i = cusum_change(x); self.assertTrue(130 <= i <= 140, i)
        fa = sum(cusum_change(diurnal(days=10, amp=0.0, noise=0.03, seed=s)) is not None for s in range(200)); self.assertLessEqual(fa / 200, 0.03)   # one RNG per series

class Decisions(unittest.TestCase):
    def test_pure_and_replayable(self):
        s = series_mem(); a, b = decide(s, {}), decide(s, {}); self.assertEqual(a, b)
        o = Optimizer(bnd(), Simulator(1, {}), code_hash="c"); o.cycle(s, OKSTATE, U, tick=tick_in_quiet(s)); self.assertTrue(replay(o.decisions[0], o.evidence))
    def test_rejected_options_are_recorded_with_reasons(self):
        d = decide(series_mem(), {}); self.assertTrue(any("not measured" in c["why"] for c in d["candidates"]) and all(c["why"] for c in d["candidates"]))
    def test_learns_from_outcomes(self):
        a = decide(series_mem(), {"mem.swappiness": [0, 5]}); b = decide(series_mem(), {"mem.swappiness": [5, 0]})
        pa = next(c["p_success"] for c in a["candidates"] if c["knob"] == "mem.swappiness"); pb = next(c["p_success"] for c in b["candidates"] if c["knob"] == "mem.swappiness"); self.assertLess(pa, pb)
    def test_idle_energy_not_claimed_without_proven_cycle(self):
        r = random.Random(3); d = decide({"cpu_util": [0.1 + 0.02 * r.random() for _ in range(168)]}, {}); self.assertTrue(all(c["severity"] == 0 for c in d["candidates"]))

class Boundaries(unittest.TestCase):
    def run_cycle(self, b, eff, state=OKSTATE, series=None, approvals=()):
        s = series or series_mem(); o = Optimizer(b, Simulator(2, eff), code_hash="c"); r = o.cycle(s, state, U, tick=tick_in_quiet(s), approvals=approvals); return o, r
    EFF = {"mem.swappiness": {"mem_pressure": -.2}, "zfs.arc_max": {"read_iops": .1}}
    def test_allowed_change_promotes_with_full_provenance(self):
        o, r = self.run_cycle(bnd(), self.EFF); self.assertEqual(r, "PROMOTED"); self.assertEqual(verify_provenance(o), [])
    def test_outside_quiet_window_denied(self):
        s = series_mem(); o = Optimizer(bnd(), Simulator(2, self.EFF), code_hash="c"); bad_tick = [p for p in range(24) if p not in profile(s["load"])["quiet"]["phases"]][0]
        self.assertEqual(o.cycle(s, OKSTATE, U, tick=bad_tick), "DENIED"); self.assertIn("not inside a measured quiet window", o.decisions[0]["boundary"]["violations"])
    def test_ram_floor_denies(self):
        o, r = self.run_cycle(bnd(), self.EFF, state=dict(free_ram_gib=2, cpu_overcommit=1.0)); self.assertEqual(r, "DENIED")
    def test_value_out_of_range_denied(self):
        e = env(); e["allowed_knobs"]["mem.swappiness"] = {"min": 50, "max": 60}; o, r = self.run_cycle(bnd(e), self.EFF); self.assertEqual(r, "DENIED")
    def test_unsigned_edit_halts(self):
        e = env(); b = bnd(e); b.env["max_changes_per_day"] = 999          # optimizer (or anyone) edits the envelope without the key
        o = Optimizer(b, Simulator(2, self.EFF), code_hash="c"); self.assertEqual(o.cycle(series_mem(), OKSTATE, U), "HALT"); self.assertEqual(o.ex.log, [])
    def test_self_modification_halts(self):
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f: f.write("# gate code\n"); p = f.name
        b = bnd(env(protected=file_hashes([p]))); self.assertIsNone(b.intact())
        open(p, "a").write("# optimizer weakens its own gate\n"); self.assertIn("protected file changed", b.intact())
        o = Optimizer(b, Simulator(2, self.EFF), code_hash="c"); self.assertEqual(o.cycle(series_mem(), OKSTATE, U), "HALT"); os.unlink(p)
    def test_class_b_needs_recorded_approval_and_c_forbidden(self):
        b = bnd(); self.assertEqual(b.check(dict(knob="net.mtu", cls="B", value=9000), dict(changes_today=0, in_flight=0, in_quiet_window=True, free_ram_gib=9, cpu_overcommit=1, consecutive_rollbacks=0, frozen=False))[0], "DENY")
        self.assertIn("class C forbidden", b.check(dict(knob="disk.partition", cls="C", value=None), dict(changes_today=0, in_flight=0, in_quiet_window=True, free_ram_gib=9, cpu_overcommit=1, consecutive_rollbacks=0, frozen=False))[1])
    def test_circuit_breaker_freezes_then_human_unfreezes(self):
        bad = {"mem.swappiness": {"mem_pressure": -.2, "p99_latency_ms": .5}, "zfs.arc_max": {"read_iops": .1, "mem_free_gib": -.8}}
        s = series_mem(); o = Optimizer(bnd(), Simulator(2, bad), code_hash="c"); t = tick_in_quiet(s)
        r1 = o.cycle(s, OKSTATE, U, tick=t); r2 = o.cycle(s, OKSTATE, U, tick=t)
        self.assertEqual((r1, r2), ("ROLLED_BACK", "ROLLED_BACK")); self.assertTrue(o.frozen)
        self.assertEqual(o.cycle(s, OKSTATE, U, tick=t), "DENIED"); o.unfreeze("owner"); self.assertFalse(o.frozen)
    def test_recurrence_detected(self):
        a, b = ("k", 1, "ROLLED_BACK"), ("k2", 1, "ROLLED_BACK")
        self.assertTrue(recurring([a, a, a])); self.assertTrue(recurring([a, b, a, b, a, b])); self.assertFalse(recurring([a, b, a])); self.assertFalse(recurring([a, a]))

class Provenance(unittest.TestCase):
    def build(self):
        s = series_mem(); o = Optimizer(bnd(), Simulator(2, {"mem.swappiness": {"mem_pressure": -.2}}), code_hash="c"); o.cycle(s, OKSTATE, U, tick=tick_in_quiet(s)); return o
    def test_clean(self): self.assertEqual(verify_provenance(self.build()), [])
    def test_tampered_evidence_found(self):
        o = self.build(); h = next(iter(o.evidence)); o.evidence[h][0] += 1; self.assertTrue(any("evidence" in p for p in verify_provenance(o)))
    def test_tampered_decision_found(self):
        o = self.build(); o.decisions[0]["chosen"]["value"] = 99; self.assertTrue(verify_provenance(o))
    def test_apply_without_decision_found(self):
        o = self.build(); o.ledger.add(event="APPLY", knob="mem.swappiness", decision_id="forged"); self.assertTrue(any("APPLY without a decision" in p for p in verify_provenance(o)))
    def test_every_apply_traces(self):
        o = self.build(); applies = [r for r in o.ledger.rows if r["event"] == "APPLY"]; self.assertTrue(applies and all(r["decision_id"] == o.decisions[0]["id"] for r in applies))

if __name__ == "__main__": unittest.main(verbosity=1)
