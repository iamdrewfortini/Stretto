# SPDX-License-Identifier: Apache-2.0
import itertools
import copy
import math
import unittest
from fractions import Fraction

from metarouter.development_cost import optimize_policy, simulate_policy


def candidate(ident, cost, probability, model="muse-wonder-1.0", **kw):
    return dict(id=ident, model=model, cost=cost, success_probability=probability, **kw)


class DevelopmentCost(unittest.TestCase):
    def test_exact_exhaustive_oracle_for_every_small_input_combination(self):
        # Independent oracle: enumerate success/failure outcomes and weight
        # their incurred costs, rather than using the optimizer's recurrence.
        for costs in itertools.product((0.1, 1, 4), repeat=2):
            for probabilities in itertools.product((0.2, 0.7, 1), repeat=2):
                rows = [candidate(str(i), costs[i], probabilities[i]) for i in range(2)]
                for floor in (0.5, 0.9, 1):
                    feasible = []
                    for count in (1, 2):
                        for seq in itertools.permutations(rows, count):
                            failure = math.prod(1 - Fraction(str(r["success_probability"])) for r in seq)
                            expected = Fraction(0)
                            for outcome in itertools.product((False, True), repeat=count):
                                weight, paid = Fraction(1), Fraction(0)
                                for r, win in zip(seq, outcome):
                                    p = Fraction(str(r["success_probability"]))
                                    weight *= p if win else 1 - p
                                for r, win in zip(seq, outcome):
                                    paid += Fraction(str(r["cost"]))
                                    if win:
                                        break
                                expected += weight * paid
                            if 1 - failure >= Fraction(str(floor)):
                                feasible.append((expected, count, tuple(r["id"] for r in seq)))
                    out = optimize_policy(rows, floor)
                    if feasible:
                        want = min(feasible)
                        self.assertEqual(out["status"], "OK")
                        self.assertEqual(Fraction(out["policy"]["exact"]["expected_cost"]), want[0])
                        self.assertEqual(tuple(r["id"] for r in out["policy"]["attempts"]), want[2])
                    else:
                        self.assertEqual(out["status"], "NO_SIGNAL")
                        self.assertIsNone(out["policy"])

    def test_cheapest_sufficient_route_beats_expensive_model_reflex(self):
        rows = [candidate("cheap", 0.1, 0.9), candidate("frontier", 9, 0.999, "muse-spark-1.3")]
        out = optimize_policy(rows, 0.85)
        self.assertEqual([r["id"] for r in out["policy"]["attempts"]], ["cheap"])
        self.assertEqual(out["policy"]["exact"]["expected_cost"], "1/10")
        higher = optimize_policy(rows, 0.99)
        self.assertEqual([r["id"] for r in higher["policy"]["attempts"]], ["cheap", "frontier"])
        self.assertGreaterEqual(higher["policy"]["success_probability"], 0.99)

    def test_floor_is_not_relaxed_and_same_endpoint_is_never_retried(self):
        out = optimize_policy([candidate("a", 1, 0.8)], 0.9)
        self.assertEqual(out["status"], "NO_SIGNAL")
        self.assertEqual(len(out["policies_evaluated"]), 1)
        with self.assertRaises(ValueError):
            simulate_policy(out)
        # Rational boundary: combined success is exactly .91, not a floating
        # approximation accidentally accepted above the requested floor.
        rows = [candidate("a", 1, 0.7), candidate("b", 1, 0.7)]
        self.assertEqual(optimize_policy(rows, 0.91)["status"], "OK")
        self.assertEqual(optimize_policy(rows, 0.9100000000000001)["status"], "NO_SIGNAL")

    def test_bounds_distinct_ids_and_role_policy(self):
        bad_rows = [[], [candidate(str(i), 1, 0.5) for i in range(9)],
                    [candidate("x", 1, 0.5), candidate("x", 1, 0.5)],
                    [candidate("x", 1, 0.5, "gpt-5")],
                    [candidate("x", 1, 0.5, "sam-3.1")],
                    [candidate("x", 1, 0.5, role="image")],
                    [candidate("x", 1, 0.5, extra="untrusted")],
                    [candidate("x", 1, 0.5), candidate("y", 1, 0.5, role="planner")]]
        for rows in bad_rows:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                optimize_policy(rows, 0.5)
        for limit in (0, 3, True, 1.0, None):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                optimize_policy([candidate("a", 1, 0.9)], 0.8, limit)

    def test_invalid_costs_probabilities_and_floor_fail_loudly(self):
        for value in (0, -1, True, "0.5", None, float("nan"), float("inf")):
            for field in ("cost", "success_probability"):
                row = candidate("a", 1, 0.5)
                row[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    optimize_policy([row], 0.5)
            with self.subTest(floor=value), self.assertRaises(ValueError):
                optimize_policy([candidate("a", 1, 0.5)], value)
        with self.assertRaises(ValueError):
            optimize_policy([candidate("a", 1, 1.1)], 0.5)

    def test_all_ordered_policies_and_stable_ties(self):
        rows = [candidate(str(i), 1, 1) for i in range(8)]
        out = optimize_policy(rows, 1)
        self.assertEqual(out["optimality"]["evaluated_policy_count"], 64)
        self.assertEqual(out, optimize_policy(list(reversed(rows)), 1))
        self.assertEqual([r["id"] for r in out["policy"]["attempts"]], ["0"])
        self.assertEqual(optimize_policy(rows, 1, 1)["optimality"]["evaluated_policy_count"], 8)

    def test_seeded_simulation_checks_exact_optimum_with_explicit_tolerance(self):
        out = optimize_policy([candidate("a", 0.2, 0.65), candidate("b", 2, 0.9)], 0.95)
        sim = simulate_policy(out, 50000, 193)
        self.assertEqual(sim, simulate_policy(out, 50000, 193))
        self.assertEqual(sim["status"], "PASS")
        self.assertEqual(sim["oracle_comparison"]["exact_cost_gap_to_oracle"], "0")
        self.assertEqual(sim["evidence_scope"], "seeded_synthetic_simulation")
        self.assertLessEqual(sim["absolute_error"]["success_probability"],
                             sim["hoeffding_bounds"]["success_absolute_tolerance"])
        self.assertLessEqual(sim["absolute_error"]["mean_cost"],
                             sim["hoeffding_bounds"]["cost_absolute_tolerance"])
        self.assertTrue(any("not live" in x for x in sim["assumptions"]))

    def test_simulation_boundaries_and_attempt_order(self):
        out = optimize_policy([candidate("a", 2, 0.9), candidate("b", 1, 0.1)], 0.9)
        for trials in (0, True, 1000001):
            with self.assertRaises(ValueError):
                simulate_policy(out, trials=trials)
        with self.assertRaises(ValueError):
            simulate_policy(out, seed=True)
        direct = {"attempts": [candidate("z", 1, 1), candidate("a", 5, 1)]}
        sim = simulate_policy(direct, trials=10)
        self.assertEqual(sim["observed_mean_cost"], 1)
        self.assertEqual(sim["attempts_used"], 10)

    def test_simulation_does_not_launder_a_forged_optimality_claim(self):
        out = optimize_policy([candidate("a", 1, 0.8), candidate("b", 9, 0.9)], 0.7)
        for mutation in (lambda x: x["policy"].update(expected_cost=0),
                         lambda x: x["policy"].update(attempts=[candidate("b", 9, 0.9)]),
                         lambda x: x.update(candidates=[])):
            bad = copy.deepcopy(out)
            mutation(bad)
            with self.assertRaises(ValueError):
                simulate_policy(bad, trials=10)


if __name__ == "__main__":
    unittest.main()
