# SPDX-License-Identifier: Apache-2.0
import json, math, statistics, unittest
from harness.rollout import KNOBS, Ledger, Rollout, Simulator, need_n, did
U = [f"g{i}" for i in range(12)]

def run(knob, effects, seed=1, drift=0.0, approvals=(), units=U, quiet=True, n=60):
    sim = Simulator(seed, effects, drift, quiet); led = Ledger()
    res = Rollout(sim, led, approvals, n=n).run(knob, "v", units)
    return res, sim, led

class T(unittest.TestCase):
    def test_helpful_knob_promoted_everywhere(self):
        r, sim, led = run("zfs.arc_max", {"zfs.arc_max": {"read_iops": +.15}})
        self.assertEqual(r, "PROMOTED"); self.assertEqual(sim.applied["zfs.arc_max"], set(U))
    def test_harmful_knob_caught_at_canary_and_rolled_back(self):
        r, sim, led = run("cpu.governor", {"cpu.governor": {"joules_per_op": -.10, "p99_latency_ms": +.40}})
        self.assertEqual(r, "ROLLED_BACK")
        self.assertEqual(sim.applied["cpu.governor"], set())                       # nothing left applied
        self.assertEqual(len([x for x in sim.log if x[0] == "apply"]), 1)           # blast radius = canary stage only
        self.assertTrue(any(x["event"] == "ROLLBACK" and "p99_latency_ms" in x["reason"] for x in led.rows))
    def test_guard_violation_beats_objective_gain(self):
        r, *_ = run("zfs.arc_max", {"zfs.arc_max": {"read_iops": +.20, "mem_free_gib": -.60}})
        self.assertEqual(r, "ROLLED_BACK")
    def test_no_effect_knob_not_promoted(self):
        r, sim, _ = run("net.tcp_buffers", {})
        self.assertEqual(r, "ROLLED_BACK"); self.assertEqual(sim.applied["net.tcp_buffers"], set())
    def test_false_positive_rate_under_null(self):
        wins = sum(run("net.tcp_buffers", {}, seed=s)[0] == "PROMOTED" for s in range(300))
        self.assertLessEqual(wins / 300, 0.03)                                       # alpha 0.025 per stage, 3 stages must all pass
    def test_power_under_real_effect(self):
        wins = sum(run("zfs.arc_max", {"zfs.arc_max": {"read_iops": +.08}}, seed=s)[0] == "PROMOTED" for s in range(100))
        self.assertGreaterEqual(wins / 100, 0.85)
    def test_drift_does_not_fake_a_win(self):
        wins = sum(run("net.tcp_buffers", {}, seed=s, drift=2.0)[0] == "PROMOTED" for s in range(150))   # 200% drift over the run; control cancels it
        self.assertLessEqual(wins / 150, 0.03)
    def test_class_C_never_executes(self):
        r, sim, led = run("disk.partition", {}, approvals=("disk.partition",))
        self.assertEqual(r, "REFUSED"); self.assertEqual(sim.log, [])
    def test_class_B_waits_for_approval_then_runs(self):
        r, sim, _ = run("ceph.balancer_upmap", {"ceph.balancer_upmap": {"osd_util_stddev": -.30}})
        self.assertEqual(r, "WAITING_APPROVAL"); self.assertEqual(sim.log, [])
        ok = sum(run("ceph.balancer_upmap", {"ceph.balancer_upmap": {"osd_util_stddev": -.30}}, approvals=("ceph.balancer_upmap",), seed=s)[0] == "PROMOTED" for s in range(60))
        self.assertGreaterEqual(ok / 60, 0.85)           # the rest are guard false alarms: safe-side rollbacks, never unsafe promotions
    def test_not_quiescent_defers(self):
        r, sim, _ = run("zfs.arc_max", {}, quiet=False)
        self.assertEqual(r, "DEFERRED"); self.assertEqual(sim.log, [])
    def test_single_unit_has_no_control(self):
        r, sim, _ = run("cpu.governor", {}, units=["only"]); self.assertEqual(r, "UNCONTROLLED")
    def test_ledger_chain_and_tamper(self):
        _, _, led = run("zfs.arc_max", {"zfs.arc_max": {"read_iops": +.15}})
        self.assertTrue(led.verify()); led.rows[2]["stage"] = 99; self.assertFalse(led.verify())
    def test_sample_size_formula(self):
        self.assertEqual(need_n(1.0, 0.5), math.ceil(((1.960 + 0.842) / 0.5) ** 2))   # 32
        self.assertEqual(need_n(1.0, 0.5), 32)
    def test_every_apply_has_a_restore_and_classes_valid(self):
        for k, v in KNOBS.items():
            self.assertIn(v["cls"], "ABC"); self.assertTrue(v["apply"] and v["restore"])
            if v["cls"] != "C": self.assertTrue(v["guard"], k)                         # every automated knob has a guard metric
    def test_did_cancels_common_drift(self):
        e, se = did([10] * 5 + [10.1], [15] * 5 + [15.1], [10] * 5 + [10.1], [15] * 5 + [15.1]); self.assertAlmostEqual(e, 0, places=9)

def rates():
    f = lambda knob, eff, n=200: sum(run(knob, eff, seed=s)[0] == "PROMOTED" for s in range(n)) / n
    return dict(null_promoted=f("net.tcp_buffers", {}), real_8pct_promoted=f("zfs.arc_max", {"zfs.arc_max": {"read_iops": .08}}),
                real_15pct_promoted=f("zfs.arc_max", {"zfs.arc_max": {"read_iops": .15}}), harmful_promoted=f("cpu.governor", {"cpu.governor": {"joules_per_op": -.10, "p99_latency_ms": .40}}),
                guard_only_harm_promoted=f("zfs.arc_max", {"zfs.arc_max": {"read_iops": .20, "mem_free_gib": -.60}}))
if __name__ == "__main__": unittest.main(verbosity=1)
