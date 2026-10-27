# SPDX-License-Identifier: Apache-2.0
import random, statistics, unittest
from humanflow import *

def ev(t, act, **kw): return dict(t=t, activity=act, duration_s=0.0, **kw)
def ledger():
    L = PersonalLedger("alice")
    for e in [ev(0, "focus"), ev(60, "focus"), ev(120, "comms"), ev(180, "wait"), ev(240, "search", failed_search=True), ev(300, "focus")]: L.add(e)
    return L
class Personal(unittest.TestCase):
    def test_time_is_conserved_across_categories(self):
        s = ledger().summary("alice"); self.assertAlmostEqual(sum(s["by_category"].values()), s["total_s"]); self.assertEqual(s["by_category"]["focus"], 120.0)
    def test_switching_is_a_count_until_calibrated(self):
        s = ledger().summary("alice"); self.assertEqual(s["switches"], 4); self.assertIsNone(s["loss"]["switching"]); self.assertFalse(s["switching_calibrated"])
        s2 = ledger().summary("alice", switch_cost_s=120.0); self.assertEqual(s2["loss"]["switching"], 480.0); self.assertTrue(s2["switching_calibrated"])
    def test_loss_components(self): s = ledger().summary("alice"); self.assertEqual(s["loss"]["wait"], 60.0); self.assertEqual(s["loss"]["search_failed"], 60.0)
    def test_only_the_owner_can_read_anything(self):
        L = ledger()
        for who in ("manager", "bob"):
            with self.assertRaises(PermissionError): L.detail(who)
            with self.assertRaises(PermissionError): L.summary(who)
    def test_long_silence_is_not_counted_as_work(self): L = PersonalLedger("a"); [L.add(e) for e in (ev(0, "focus"), ev(10000, "focus"))]; self.assertLessEqual(L.summary("a")["total_s"], 300.0 + 1e-9)

def shared(n, wait=600.0):
    out = []
    for i in range(n): L = PersonalLedger(f"p{i}"); [L.add(e) for e in (ev(0, "focus"), ev(3600, "wait"), ev(3600 + wait, "focus"))]; out.append(L.summary(f"p{i}"))
    return out
class Rollup(unittest.TestCase):
    def test_small_groups_are_suppressed_entirely(self):
        r = rollup({"ops": shared(4), "eng": shared(5)}, k=5, seed=1); self.assertTrue(r["ops"]["suppressed"]); self.assertNotIn("by_category", r["ops"]); self.assertFalse(r["eng"]["suppressed"])
    def test_no_per_person_output_exists(self):
        r = rollup({"eng": shared(8)}, seed=2); flat = repr(r); self.assertNotIn("p0", flat); self.assertEqual(r["eng"]["contributors"], 8)
        self.assertFalse(any(callable(getattr(__import__("humanflow"), n)) and "person" in n for n in dir(__import__("humanflow"))))
    def test_noise_scale_matches_epsilon(self):
        cap, eps = 8 * 3600.0, 2.0; rnd = random.Random(5); xs = [laplace(cap / eps, rnd) for _ in range(40000)]
        self.assertAlmostEqual(statistics.fmean(xs), 0.0, delta=0.03 * cap / eps * 2 ** 0.5 * 3); self.assertAlmostEqual(statistics.pstdev(xs), (2 ** 0.5) * cap / eps, delta=0.05 * cap / eps * 2 ** 0.5)
    def test_clipping_bounds_one_persons_influence(self):
        big = shared(5); big[0]["by_category"]["focus"] = 10 ** 9; r1 = rollup({"g": big}, cap_s=100.0, epsilon=1e9, seed=3); r2 = rollup({"g": shared(5)}, cap_s=100.0, epsilon=1e9, seed=3)
        self.assertLessEqual(r1["g"]["by_category"]["focus"], 5 * 100.0 + 1e-3)
    def test_handoffs_and_doc_gaps_need_k_distinct_people(self):
        edges = [("sales", "legal", 100.0, f"p{i}") for i in range(5)] + [("sales", "ops", 900.0, "p1")] * 9; h = handoffs(edges, k=5)
        self.assertIn("sales->legal", h); self.assertNotIn("sales->ops", h)                       # 9 samples from ONE person are not enough
        g = doc_gaps([("expense policy", f"p{i}") for i in range(6)] + [("secret project", "p1")] * 20, k=5); self.assertEqual(g, [("expense policy", 6)])
if __name__ == "__main__": unittest.main()
