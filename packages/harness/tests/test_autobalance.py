# SPDX-License-Identifier: Apache-2.0
import json, math, random, statistics, unittest
from harness.sampling import neyman, pooled_variance, nyquist_interval, QuantileThreshold, rate_balance, PrecisionController
from harness.forecast import train, predict
from harness.questions import QuestionStream, beta_sd
from harness.signing import new_key, sign_with, make_verifier
from harness.boundary import Boundary
from harness.qms import derive_guards, K8S_KNOBS

class Sampling(unittest.TestCase):
    S = [dict(N=100, sigma=1, cost=1), dict(N=20, sigma=5, cost=1), dict(N=5, sigma=40, cost=4)]
    def test_budget_respected_and_capped(self):
        n = neyman(self.S, 60); self.assertLessEqual(sum(s["cost"] * x for s, x in zip(self.S, n)), 60 + 1e-6); self.assertTrue(all(x <= s["N"] + 1e-9 for s, x in zip(self.S, n)))
    def test_beats_proportional(self):
        n = neyman(self.S, 60); tot = sum(s["N"] * s["cost"] for s in self.S); prop = [60 * s["N"] / tot for s in self.S]
        self.assertLess(pooled_variance(self.S, n), pooled_variance(self.S, prop) * 0.6)
    def test_formula_matches_monte_carlo(self):
        S = [dict(N=200, sigma=1.0, cost=1), dict(N=50, sigma=6.0, cost=1)]; r = random.Random(3)
        pops = [[r.gauss(10 * i, s["sigma"]) for _ in range(s["N"])] for i, s in enumerate(S)]
        S = [dict(N=s["N"], sigma=statistics.stdev(p), cost=1) for s, p in zip(S, pops)]
        n = [round(x) for x in neyman(S, 60)]; Nt = sum(s["N"] for s in S); true = sum(s["N"] * statistics.fmean(p) for s, p in zip(S, pops)) / Nt
        est = [sum(s["N"] * statistics.fmean(r.sample(p, k)) for s, p, k in zip(S, pops, n)) / Nt for _ in range(4000)]
        mc = statistics.fmean((e - true) ** 2 for e in est); self.assertLess(abs(mc / pooled_variance(S, n) - 1), 0.15)
    def test_nyquist(self):
        self.assertEqual(nyquist_interval(86400), 3600); self.assertEqual(nyquist_interval(2400), 300); self.assertEqual(nyquist_interval(2400, alarm=True), 150)
        for p in (600, 3600, 86400, 604800): self.assertGreaterEqual(p / nyquist_interval(p), 2)
    def test_quantile_converges_and_tracks_shift(self):
        r = random.Random(1); q = QuantileThreshold(0.9, scale=1.0)
        for _ in range(30000): q.update(r.gauss(0, 1))
        self.assertLess(abs(q.theta - 1.2816), 0.12)
        for _ in range(3000): q.update(r.gauss(3, 1))
        self.assertLess(abs(q.theta - (3 + 1.2816)), 0.35)
    def test_rate_balance_equal_across_levels(self):
        spw = {"guest": 168 * 40, "node": 168 * 3, "cluster": 168}; qd = rate_balance(spw, 4)
        for k in spw: self.assertAlmostEqual((1 - qd[k]) * spw[k], 4, delta=0.04)
    def test_precision_controller_converges(self):
        pc = PrecisionController(q=0.6, target=0.7, gain=0.05); r = random.Random(2)
        for _ in range(600):
            prop = 20; p = 0.3 + 0.65 * (pc.q - 0.5) / 0.5; pc.update(sum(r.random() < p for _ in range(prop)), prop)
        p_final = 0.3 + 0.65 * (pc.q - 0.5) / 0.5; self.assertAlmostEqual(p_final, 0.7, delta=0.06)

class Forecast(unittest.TestCase):
    def series(self, n, amp=0.3, noise=0.05, seed=1):
        r = random.Random(seed); return [0.5 + amp * math.sin(2 * math.pi * (t % 24) / 24) + 0.001 * t + r.gauss(0, noise) for t in range(n)]
    def test_accepts_real_structure(self):
        m = train(self.series(24 * 10), 24); self.assertTrue(m["accepted"], m); self.assertGreater(m["skill"], 0.15)
    def test_rejects_pure_noise(self):
        r = random.Random(4); m = train([r.gauss(0.5, 0.1) for _ in range(240)], 24); self.assertFalse(m["accepted"], m)
    def test_rejects_too_little_data(self): self.assertIn("need", train(self.series(60), 24)["reason"])
    def test_holdout_is_out_of_sample(self): m = train(self.series(240), 24); self.assertEqual(m["holdout"], 240 - int(0.7 * 240))
    def test_predict_shape_and_phase(self):
        x = self.series(24 * 8); m = train(x, 24); p = predict(x, 24, m["params"], 24); self.assertEqual(len(p), 24)
        self.assertGreater(max(p) - min(p), 0.3)

class Questions(unittest.TestCase):
    def mk(self):
        s = QuestionStream(per_day=2); c = {"a": [0, 0], "b": [20, 20]}
        s.propose("q1", "a", "A", c, 1.0, "Allow lower swappiness?"); s.propose("q2", "b", "B", c, 3.0, "Raise MTU?"); s.propose("q3", "a", "B", c, 3.0, "Move guest?"); return s, c
    def test_voi_ordering_and_daily_cap(self):
        s, c = self.mk(); top = s.next(1000.0, k=5); self.assertEqual(len(top), 2); self.assertEqual(top[0]["qid"], "q3")
        self.assertEqual(s.next(1001.0, k=5), []); self.assertGreater(beta_sd(0, 0), beta_sd(20, 20))
    def test_answers_shift_posterior_and_other_needs_text(self):
        s, c = self.mk(); s.answer("q1", "yes", "owner", 1.0); out = s.apply_to_counts(c); self.assertEqual(out["a"], [2.0, 0.0])
        s.answer("q3", "no", "owner", 2.0); self.assertEqual(s.apply_to_counts(c)["a"], [2.0, 2.0])
        with self.assertRaises(ValueError): s.answer("q2", "other", "owner", 3.0)
        s.answer("q2", "other", "owner", 3.0, text="only on weekends"); self.assertEqual(s.notes[0]["text"], "only on weekends"); self.assertEqual(s.apply_to_counts(c)["b"], [20, 20])
        with self.assertRaises(ValueError): s.answer("q2", "maybe", "owner", 4.0)
    def test_class_a_advisory_class_b_approval_expires(self):
        s, c = self.mk(); self.assertTrue(s.q["q1"]["advisory"]); self.assertFalse(s.q["q2"]["advisory"])
        s.answer("q2", "yes", "owner", 100.0); self.assertTrue(s.approved("b", 101.0)); self.assertFalse(s.approved("b", 100.0 + 8 * 86400))
    def test_answer_ledger_is_tamper_evident(self):
        s, c = self.mk(); s.answer("q1", "yes", "owner", 1.0); self.assertTrue(s.led.verify()); s.led.rows[0]["choice"] = "no"; self.assertFalse(s.led.verify())

class Custody(unittest.TestCase):
    def setUp(self):
        self.k = {n: new_key() for n in ("a1", "a2", "h1", "x")}
        self.auth = {"a1": ("agent", self.k["a1"][1]), "a2": ("agent", self.k["a2"][1]), "h1": ("human", self.k["h1"][1])}
        self.v = make_verifier(self.auth); self.env = dict(max_changes_per_day=3)
    def sigs(self, names, env=None): return {n: sign_with(env or self.env, self.k[n][0]) for n in names}
    def test_two_agents_and_human_valid(self): self.assertTrue(self.v(self.env, self.sigs(["a1", "a2", "h1"]))[0])
    def test_missing_human_or_agent_rejected(self):
        self.assertFalse(self.v(self.env, self.sigs(["a1", "a2"]))[0]); self.assertFalse(self.v(self.env, self.sigs(["a1", "h1"]))[0])
    def test_unauthorized_and_tampered_rejected(self):
        self.assertFalse(self.v(self.env, self.sigs(["a1", "a2", "x"]))[0]); s = self.sigs(["a1", "a2", "h1"]); self.assertFalse(self.v(dict(max_changes_per_day=999), s)[0])
    def test_optimizer_side_holds_public_keys_only(self):
        self.assertTrue(all(isinstance(p, bytes) and len(p) == 32 for _, p in self.auth.values()))
        b = Boundary(self.env, self.sigs(["a1", "a2", "h1"]), verify_fn=self.v); self.assertIsNone(b.intact()); b.env["max_changes_per_day"] = 999; self.assertIn("signature invalid", b.intact())

class Qms(unittest.TestCase):
    def test_margin_follows_headroom(self):
        x = [10 + i * 0.01 for i in range(200)]; g = derive_guards({"p99_latency_ms": 20}, {"p99_latency_ms": x}); self.assertAlmostEqual(g["p99_latency_ms"], 0.5 * (20 - sorted(x)[190]) / 20, places=5)
        self.assertEqual(derive_guards({"p99_latency_ms": 10}, {"p99_latency_ms": x})["p99_latency_ms"], 0.0)
        f = derive_guards({">read_iops": 800}, {"read_iops": [1000.0] * 100}); self.assertAlmostEqual(f["read_iops"], 0.5 * 200 / 800)
    def test_k8s_knobs_are_gitops_with_restore(self):
        for k, v in K8S_KNOBS.items(): self.assertEqual(v["channel"], "gitops"); self.assertIn("revert", v["restore"]); self.assertTrue(v["guard"])

if __name__ == "__main__": unittest.main(verbosity=1)
