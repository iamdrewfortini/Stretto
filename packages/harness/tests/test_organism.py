# SPDX-License-Identifier: Apache-2.0
import itertools, json, random, statistics, unittest
from harness.organism import *
from harness.sampling import QuantileThreshold

class Genome(unittest.TestCase):
    V = b"swappiness=10;arc_max=8GiB"
    def test_roundtrip_and_complement(self):
        g = Gene("k", self.V); self.assertEqual(g.value(), self.V); self.assertTrue(all(comp(comp(b)) == b for b in range(4)))
        self.assertTrue(all(comp(x) == y for c1, c2 in zip(g.s1, g.s2) for x, y in zip(c1[:3], c2[:3])))
    def test_every_single_base_error_is_detected_and_repaired_exactly(self):
        base = Gene("k", self.V); n = len(base.s1)
        for strand in ("s1", "s2"):
            for ci in range(n):
                for pos in range(4):
                    for v in range(4):
                        g = Gene("k", self.V); c = getattr(g, strand)[ci]
                        if c[pos] == v: continue
                        c[pos] = v; st = inspect(g)[ci]; self.assertIn(st, ("repair_s1", "repair_s2"))
                        self.assertEqual(repair(g), (1, 0)); self.assertEqual(g.value(), self.V); self.assertEqual(set(inspect(g)), {"ok"})
    def test_double_errors_never_silently_wrong(self):
        for pos in itertools.combinations(range(4), 2):                 # two bases of one codon on strand 1, all value pairs
            for v1, v2 in itertools.product(range(4), repeat=2):
                g = Gene("k", self.V); c = g.s1[2]
                if c[pos[0]] == v1 or c[pos[1]] == v2: continue
                c[pos[0]], c[pos[1]] = v1, v2; repair(g)
                self.assertTrue(g.value() == self.V or "unrepairable" in inspect(g))      # exact, or loudly flagged: never silently wrong
    def test_both_strands_hit_same_codon_flagged(self):
        g = Gene("k", self.V); g.s1[1][0] ^= 1; g.s2[1][1] ^= 1; self.assertEqual(inspect(g)[1], "unrepairable"); self.assertEqual(repair(g)[1], 1)
    def test_drift_and_splice_respect_boundary(self):
        des = {"swappiness": b"10", "arc": b"8", "mtu": b"1500"}; obs = {"swappiness": b"60", "arc": b"8", "mtu": b"9000"}
        self.assertEqual(sorted(drift(des, obs)), ["mtu", "swappiness"])
        plan, outside = splice_plan(des, obs, allowed={"swappiness"}); self.assertEqual([p["gene"] for p in plan], ["swappiness"]); self.assertEqual(outside, ["mtu"])
        obs2 = dict(obs, swappiness=plan[0]["to"]); self.assertNotIn("swappiness", drift(des, obs2))           # verify after splice

class Homeo(unittest.TestCase):
    def sim(self, noise, steps=200, seed=1, start=10.0):
        h = Homeostat(setpoint=5.0, lo=4.5, hi=5.5, gain=0.6, max_step=1.0); r = random.Random(seed); x, acts, outside = start, [], 0
        for t in range(steps):
            u = h.act(x); acts.append(u); x += u + r.gauss(0, noise)
            if t > 60 and not (4.0 <= x <= 6.0): outside += 1
        return x, acts, outside
    def test_converges_into_band_with_noise(self):
        for noise in (0.0, 0.1, 0.3): x, acts, outside = self.sim(noise); self.assertLess(outside / 140, 0.08, (noise, outside))
    def test_no_dithering_when_inside_band(self):
        h = Homeostat(5, 4.5, 5.5); self.assertEqual([h.act(x) for x in (4.5, 5.0, 5.5)], [0.0, 0.0, 0.0])
    def test_step_is_bounded_and_no_limit_cycle(self):
        x, acts, _ = self.sim(0.0); self.assertTrue(all(abs(a) <= 1.0 for a in acts)); self.assertFalse(recurring([("a", round(a, 3), "") for a in acts[-12:] if a != 0.0]))

class ImmuneTests(unittest.TestCase):
    def ev(self, **kw): return dict(kind="drift", metric="mem", direction="high", value=0.5, target="guest-1", **kw)
    def test_second_exposure_is_faster_and_cheaper(self):
        im = Immune(self_set={"envelope"}); a = im.respond(self.ev(), 0.9); b = im.respond(self.ev(), 0.9)
        self.assertEqual((a["layer"], b["layer"]), ("adaptive-novel", "adaptive-memory")); self.assertLess(b["steps"], a["steps"])
    def test_innate_contains_above_hard_limit_in_one_step(self): self.assertEqual(Immune(set()).respond(dict(self.ev(), value=0.99), 0.9)["steps"], 1)
    def test_self_is_never_attacked(self):
        im = Immune({"envelope", "gate-code"}); r = im.respond(dict(self.ev(), target="gate-code", value=5.0), 0.9); self.assertEqual((r["layer"], r["steps"]), ("tolerance", 0))
    def test_innate_false_trigger_rate_matches_quantile(self):
        r = random.Random(7); q = QuantileThreshold(0.99, scale=1.0); trig = 0; N = 20000
        for i in range(N):
            x = r.gauss(0, 1); trig += i > 2000 and x > q.theta; q.update(x)
        self.assertAlmostEqual(trig / (N - 2001), 0.01, delta=0.006)

class Microbiome(unittest.TestCase):
    def test_capacity_from_real_numbers(self): self.assertEqual(carrying_capacity(35.1, 2.0), 17)
    def test_population_never_exceeds_capacity_and_drains_gracefully(self):
        r = random.Random(3); n = 2; K_series = [17] * 60 + [6] * 20 + [17] * 120; drained_total = 0
        for K in K_series:
            n, d = pop_step(n, K, rng=r); drained_total += d; self.assertLessEqual(n, K)
        self.assertGreater(drained_total, 0); self.assertGreaterEqual(n, 14)           # regrows toward K after pressure ends
    def test_zero_capacity_means_zero_workers(self): self.assertEqual(pop_step(5, 0)[0], 0)

class Cascade(unittest.TestCase):
    def test_ratio_rule_is_optimal_by_brute_force(self):
        r = random.Random(11)
        for _ in range(200):
            lanes = {f"l{i}": (r.uniform(0.001, 1.0), r.uniform(0.2, 0.99)) for i in range(5)}
            best = min(itertools.permutations(lanes), key=lambda o: expected_cost(o, lanes)[0])
            self.assertAlmostEqual(expected_cost(best_order(lanes), lanes)[0], expected_cost(best, lanes)[0], places=12)
    def test_cheap_first_beats_strong_first_on_example(self):
        lanes = {"shell": (0.0, 0.5), "small": (0.01, 0.8), "strong": (0.20, 0.97)}
        self.assertEqual(best_order(lanes)[0], "shell"); self.assertLess(expected_cost(best_order(lanes), lanes)[0], expected_cost(["strong", "small", "shell"], lanes)[0] / 5)
    def test_energy_in_the_price(self): self.assertAlmostEqual(lane_cost(joules=3.6e6, usd_per_kwh=0.15), 0.15)

class Dags(unittest.TestCase):
    OK = {"nodes": [dict(id="a", action="observe", check="rows>0", est_cost=0.01), dict(id="b", action="mem.swappiness", check="p>.05", deps=["a"], est_cost=0.02),
                    dict(id="c", action="observe", check="rows>0", deps=["a"], est_cost=0.01), dict(id="d", action="report", check="exists", deps=["b", "c"], est_cost=0.0)]}
    A = {"observe", "mem.swappiness", "report"}
    def test_valid_plan_passes(self): self.assertEqual(validate_plan(self.OK, self.A, budget=0.1), [])
    def test_cycle_unknown_action_budget_and_missing_check_rejected(self):
        cyc = json.loads(json.dumps(self.OK)); cyc["nodes"][0]["deps"] = ["d"]; self.assertIn("dependency cycle", validate_plan(cyc, self.A, 0.1))
        bad = json.loads(json.dumps(self.OK)); bad["nodes"][1]["action"] = "disk.partition"; self.assertTrue(any("not allowed" in p for p in validate_plan(bad, self.A, 0.1)))
        self.assertTrue(any("over budget" in p for p in validate_plan(self.OK, self.A, 0.01)))
        nochk = json.loads(json.dumps(self.OK)); nochk["nodes"][2]["check"] = ""; self.assertTrue(any("missing check" in p for p in validate_plan(nochk, self.A, 0.1)))
        wide = {"nodes": [dict(id=f"n{i}", action="observe", check="x") for i in range(12)]}; self.assertTrue(any("width" in p for p in validate_plan(wide, self.A, 1, max_width=8)))
    def test_typed_checks_required_when_metrics_given(self):
        M = {"mem_frac", "p99_latency_ms"}; prose = validate_plan(self.OK, self.A, 0.1, metrics=M); self.assertTrue(prose and all("check must be" in p for p in prose))
        typed = json.loads(json.dumps(self.OK))
        for n in typed["nodes"]: n["check"] = {"metric": "mem_frac", "op": "<", "value": 0.75}
        self.assertEqual(validate_plan(typed, self.A, 0.1, metrics=M), [])
        typed["nodes"][0]["check"] = {"metric": "bogus", "op": "<", "value": 1}; self.assertTrue(validate_plan(typed, self.A, 0.1, metrics=M))
    def test_execution_order_cost_and_escalation(self):
        lanes = {"shell": (0.0, 0.5), "small": (0.01, 0.8), "strong": (0.2, 0.97)}; calls = []
        def run_lane(lane, n): calls.append((n["id"], lane)); return lane
        def check(n, out): return out == "strong" if n["id"] == "b" else out in ("shell", "small", "strong")        # node b needs the strong lane
        res = run_dag(self.OK, lanes, run_lane, check)
        self.assertEqual(res["state"], {"a": "ok", "b": "ok", "c": "ok", "d": "ok"})
        self.assertLess(calls.index(("a", "shell")), calls.index(("b", "shell")))                          # dependency order
        self.assertEqual([l for i, l in calls if i == "b"], ["shell", "small", "strong"])                  # cheapest first, escalated only on failed check
        self.assertEqual([l for i, l in calls if i == "a"], ["shell"])
        self.assertAlmostEqual(res["cost"], 0.0 + 0.0 + 0.01 + 0.2 + 0.0 + 0.0, places=6)
    def test_failed_node_skips_dependents(self):
        res = run_dag(self.OK, {"shell": (0.0, 0.5)}, lambda l, n: None, lambda n, o: n["id"] != "b"); self.assertEqual((res["state"]["b"], res["state"]["d"], res["state"]["c"]), ("failed", "skipped", "ok"))
    def test_parse_model_output_and_garbage(self):
        self.assertEqual(parse_plan('Sure!\n```json\n{"nodes":[{"id":"x"}]}\n```')["nodes"][0]["id"], "x")
        with self.assertRaises(ValueError): parse_plan("I cannot do that")
        self.assertTrue(validate_plan("nonsense", self.A, 1))
if __name__ == "__main__": unittest.main(verbosity=1)
