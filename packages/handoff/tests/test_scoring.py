# SPDX-License-Identifier: Apache-2.0
import itertools, random, statistics, unittest
from handoff import examples
from handoff.procedure import Procedure
from handoff.scoring import *
from handoff.simulate import dataset, extract

LEVELS = [("clean", dict(p_fact_drop=0.0, p_halluc=0.0)), ("default", dict()), ("heavy", dict(p_fact_drop=0.35, p_halluc=0.25)), ("extreme", dict(p_fact_drop=0.6, p_halluc=0.4)), ("none", dict(p_fact_drop=1.0, p_halluc=0.0))]
class Signals(unittest.TestCase):
    def test_opposites_share_words_but_not_effects(self):
        g = examples.gearbox(); a, b = g.steps[g.index("g4")], g.steps[g.index("g10")]; self.assertGreater(sim_text(a, b), 0.3); self.assertEqual(sim_effect(a, b), 0.0)
    def test_a_paraphrase_shares_effects_not_words(self):
        g = examples.gearbox(); a = g.steps[g.index("g4")]; p = dict(a, text="Take off the belt"); self.assertLess(sim_text(a, p), 0.5); self.assertEqual(sim_effect(a, p), 1.0)
    def test_the_boost_widens_the_gap_between_a_paraphrase_and_an_opposite(self):
        g = examples.gearbox(); a, b = g.steps[g.index("g4")], g.steps[g.index("g10")]; p = dict(a, text="Take off the belt")
        self.assertGreater(boosted(a, p) - boosted(a, b), sim_text(a, p) - sim_text(a, b))
class Assignment(unittest.TestCase):
    def test_hungarian_equals_brute_force(self):
        r = random.Random(3)
        for n, m in ((5, 5), (4, 6), (6, 4), (3, 3)):
            S = [[r.random() for _ in range(m)] for _ in range(n)]; got = sum(S[i][j] for i, j in hungarian_max(S)); k = min(n, m)
            best = max(sum(S[i][p[i]] for i in range(n)) for p in itertools.permutations(range(m), n)) if n <= m else max(sum(S[p[j]][j] for j in range(m)) for p in itertools.permutations(range(n), m))
            self.assertAlmostEqual(got, best, places=9); self.assertEqual(len(hungarian_max(S)), k)
    def test_optimal_beats_greedy_when_greedy_is_trapped(self):
        S = [[0.9, 0.8], [0.85, 0.1]]; opt = sum(S[i][j] for i, j in hungarian_max(S)); gr = sum(S[i][j] for i, j in greedy(S, 0.0)); self.assertGreater(opt, gr); self.assertAlmostEqual(opt, 1.65)
class Coherence(unittest.TestCase):
    def test_the_headline_recall_is_set_by_a_hidden_threshold(self):
        c = {t: (r, p) for t, r, p in threshold_curve(dataset(range(100, 140)), sim_text)}
        self.assertGreaterEqual(c[0.2][0], 0.95); self.assertLessEqual(c[0.5][0], 0.7); self.assertGreaterEqual(min(c[0.2][1], c[0.5][1]), 0.99)       # same extraction, 0.3+ recall swing, precision unchanged
    def test_boosted_is_never_worse_than_words_in_any_noise_condition(self):
        for lab, kw in LEVELS:
            d = dataset(range(100, 140), **kw); rb, pb = step_scores(d); rw, pw = step_scores(d, thr=DEFAULT_THRESHOLD, sim_fn=sim_text)
            self.assertGreaterEqual(2 * rb * pb / (rb + pb), 2 * rw * pw / (rw + pw) - 0.002, lab)
    def test_signal_agreement_falls_as_the_inferred_effects_get_noisy(self):
        k = [statistics.fmean(agreement_kappa(e, kk) for e, kk, t, n in dataset(range(100, 130), **kw)) for lab, kw in LEVELS]
        self.assertTrue(all(a > b for a, b in zip(k, k[1:]))); self.assertAlmostEqual(k[-1], 0.0, places=9)
    def test_order_is_recovered_and_dependency_recovery_is_the_weak_spot(self):
        rep = []
        for name, f in examples.ALL.items():
            for sd in range(100, 120): p = f(); rng = random.Random(f"{name}-{sd}"); ext, truth = extract(p, rng); rep.append(job_report(ext, p.steps, truth, Procedure(ext, p.initial, p.goal), p))
        tau = statistics.fmean(r["order_tau"] for r in rep); dep = statistics.fmean(r["dependency_recall"] for r in rep); lo = min(r["dependency_recall"] for r in rep)
        self.assertGreaterEqual(tau, 0.95); self.assertTrue(0.5 <= dep <= 0.9, dep); self.assertLess(lo, 0.5); print(f"\norder tau {tau:.3f}; dependency recall mean {dep:.3f}, min {lo:.3f}")
    def test_this_benchmark_cannot_tell_the_matchers_apart(self):
        ok, f = discriminates(dataset(range(100, 140)), {"words": sim_text, "boosted": boosted, "effects": sim_effect}, thr=0.1); words_boosted = abs(f["words"] - f["boosted"])
        ok2, f2 = discriminates(dataset(range(100, 140)), {"words": sim_text, "boosted": boosted}, thr=0.1); self.assertFalse(ok2); self.assertLess(words_boosted, 0.02)
    def test_bootstrap_interval_is_ordered_and_narrows_with_more_jobs(self):
        r = random.Random(1); small = [r.random() for _ in range(30)]; big = small + [r.random() for _ in range(270)]
        m1, lo1, hi1 = bootstrap_ci(small); m2, lo2, hi2 = bootstrap_ci(big); self.assertTrue(lo1 <= m1 <= hi1 and lo2 <= m2 <= hi2); self.assertLess(hi2 - lo2, hi1 - lo1)
if __name__ == "__main__": unittest.main()
