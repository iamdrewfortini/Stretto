# SPDX-License-Identifier: Apache-2.0
import math, random, unittest
from coherence.metrics import *
from coherence.energy import *

class Gaps(unittest.TestCase):
    def test_jain_extremes(self): self.assertEqual(jain([2, 2, 2]), 1.0); self.assertAlmostEqual(jain([1, 0, 0, 0]), 0.25); self.assertAlmostEqual(jain([0.58, 2.08, 1.25]), 0.8185, places=3)
    def test_ratio_gap(self): self.assertEqual(ratio_gap(5, 5), 0.0); self.assertAlmostEqual(ratio_gap(10, 5), 0.5); self.assertEqual(ratio_gap(3, 5), 0.0)
    def test_finish_bound(self): self.assertEqual(finish_time_bound(8, 16, 2), 8); self.assertEqual(finish_time_bound(5, 30, 2), 15)
    def test_proportionality(self): self.assertEqual(energy_proportionality_gap(100, 1.0, 100), 0.0); self.assertAlmostEqual(energy_proportionality_gap(100, 0.1, 200), 0.8)
    def test_balance_pressure_weighting(self):
        g = balance_gap({"cpu": [0.58, 2.08, 1.25], "ram": [0.66, 0.86, 0.71]}, {"cpu": 1.19, "ram": 0.73}); self.assertAlmostEqual(g, 0.1174, places=3)       # utilization RATIOS, measured 2026-10-26
        self.assertAlmostEqual(balance_gap({"a": [1, 1, 1]}), 0.0)
    def test_scale_gap_exact_power_law(self):
        caps = [1, 4, 16, 64]; self.assertAlmostEqual(scale_gap(caps, [c for c in caps]), 0.0, places=9); self.assertAlmostEqual(scale_gap(caps, [c ** 0.7 for c in caps]), 0.3, places=9); self.assertIsNone(scale_gap([1, 2], [1, 2]))

class Distance(unittest.TestCase):
    def test_zero_iff_all_gaps_zero(self): self.assertEqual(distance({k: 0.0 for k in AXES})["D"], 0.0); self.assertGreater(distance(dict({k: 0.0 for k in AXES}, speed=0.1))["D"], 0)
    def test_missing_axes_make_it_a_lower_bound_never_an_improvement(self):
        full = distance({"speed": 0.3, "energy": 0.2, "balance": 0.1, "scale": 0.0, "intent": 0.5}); part = distance({"speed": None, "energy": None, "balance": 0.1, "scale": 0.0, "intent": 0.5})
        self.assertTrue(part["lower_bound"]); self.assertEqual(sorted(part["missing"]), ["energy", "speed"]); self.assertLessEqual(part["D"], full["D"])
    def test_monotone_in_each_gap(self):
        base = {k: 0.1 for k in AXES}
        for k in AXES: up = dict(base); up[k] = 0.2; self.assertGreater(distance(up)["D"], distance(base)["D"])
    def test_contributions_sum_to_D_squared(self): d = distance({"speed": 0.3, "energy": 0.4, "balance": 0.1, "scale": 0.2, "intent": 0.5}); self.assertAlmostEqual(sum(d["contribution"].values()), d["D"] ** 2, places=5)

class Direction(unittest.TestCase):
    EFF = {"migrate": {"balance": -0.10, "speed": 0.02}, "governor": {"energy": -0.12, "speed": 0.03}, "scheduler": {"speed": -0.15, "energy": 0.01}, "ask-human": {"intent": -0.25}}
    COST = {"migrate": 2.0, "governor": 1.0, "scheduler": 1.0, "ask-human": 0.5}
    def test_points_at_the_dominant_axis(self):
        g = {"speed": 0.05, "energy": 0.6, "balance": 0.05, "scale": 0.0, "intent": 0.05}; self.assertEqual(direction(g, self.EFF, self.COST)[0][0], "governor")
        g2 = dict(g, energy=0.05, intent=0.7); self.assertEqual(direction(g2, self.EFF, self.COST)[0][0], "ask-human")
    def test_owned_axes_only(self):
        g = {"speed": 0.5, "energy": 0.5, "balance": 0.5, "scale": 0.0, "intent": 0.5}; r = direction(g, self.EFF, self.COST, owned={"balance"}); self.assertEqual([a for a, _ in r], ["migrate"])
    def test_hold_at_coherence_and_no_improving_action(self):
        self.assertEqual(direction({k: 0.0 for k in AXES}, self.EFF, self.COST), []); self.assertEqual(direction({"speed": 0.5, "energy": 0.0, "balance": 0.0, "scale": 0.0, "intent": 0.0}, {"governor": {"energy": -0.1}}, {"governor": 1}), [])
    def test_descent_reduces_D_monotonically_and_converges(self):
        g = {"speed": 0.4, "energy": 0.5, "balance": 0.3, "scale": 0.0, "intent": 0.6}; Ds = []
        for _ in range(200):
            Ds.append(distance(g)["D"]); r = direction(g, self.EFF, self.COST)
            if not r: break
            for k, v in self.EFF[r[0][0]].items(): g[k] = min(0.99, max(0.0, g[k] + 0.5 * v))               # half-step along the chosen action
        self.assertTrue(all(b <= a + 0.02 for a, b in zip(Ds, Ds[1:]))); self.assertLess(Ds[-1], 0.1)
    def test_noisy_effects_still_descend_on_average(self):
        rnd = random.Random(2); g = {"speed": 0.4, "energy": 0.5, "balance": 0.3, "scale": 0.0, "intent": 0.6}; d0 = distance(g)["D"]
        for _ in range(60):
            r = direction(g, self.EFF, self.COST)
            if not r: break
            for k, v in self.EFF[r[0][0]].items(): g[k] = min(0.99, max(0.0, g[k] + 0.5 * v * (1 + rnd.gauss(0, 0.5))))
        self.assertLess(distance(g)["D"], 0.5 * d0)
    def test_effect_model_learns_from_before_after(self):
        m = EffectModel(); [m.observe("governor", {"energy": 0.5, "speed": 0.1}, {"energy": 0.38, "speed": 0.13}) for _ in range(5)]; self.assertAlmostEqual(m.e["governor"]["energy"], -0.12, places=6)

class Energy(unittest.TestCase):
    def test_rapl_wraparound(self): self.assertAlmostEqual(rapl_delta_j(900_000, 1_100_000, 2_000_000), 0.2); self.assertAlmostEqual(rapl_delta_j(1_900_000, 100_000, 2_000_000), 0.2)
    def test_attribution_conserves_energy(self):
        a = attribute(1234.5, {"vm1": 10.0, "vm2": 30.0, "lxc3": 60.0}); self.assertAlmostEqual(sum(a.values()), 1234.5); self.assertAlmostEqual(a["vm1"], 123.45); self.assertEqual(attribute(5.0, {"x": 0.0}), {"x": 0.0})
    def test_unmeasured_is_none_not_a_guess(self):
        self.assertIsNone(joules_per_job(None, 5)); self.assertIsNone(joules_per_job(10.0, 0)); self.assertIsNone(edp(None, 3)); self.assertEqual(edp(10.0, 3.0), 30.0)
        r = source_report({"rapl": None, "ups_w": 212.0, "nvml_w": None}); self.assertEqual(r["measured"], ["ups_w"]); self.assertEqual(r["not_measured"], ["rapl", "nvml_w"])
if __name__ == "__main__": unittest.main(verbosity=1)
