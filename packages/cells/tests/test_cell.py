# SPDX-License-Identifier: Apache-2.0
import itertools, math, random, time, unittest
from coherence.attention import Attention, Tracker
from wf13d.bridge import State
from coherence.distill import pca, project, reconstruct, recon_error, jl_min_dim, random_projection, rp_apply, compression
from cells.microcell import MicroCell
from metarouter.speed import TimedEndpoint, SpeedRouter, erlang_c_wait, race_metrics, seq_metrics

def ep(name, model, t, c, p, task="t", status="live", via="gateway", **kw):
    e = TimedEndpoint(name, model, status, c, t, via=via, **kw); e.stats[task] = [round(p * 1000), round((1 - p) * 1000)]; return e

class Speed(unittest.TestCase):
    def test_erlang_known_values(self):
        self.assertAlmostEqual(erlang_c_wait(0.5, 1, 1), 1.0); self.assertAlmostEqual(erlang_c_wait(1, 1, 2), 1 / 3); self.assertEqual(erlang_c_wait(1, 1, 1), math.inf); self.assertEqual(erlang_c_wait(0, 1, 3), 0.0)
    def test_race_metrics_match_monte_carlo(self):
        eps = [ep("a", "muse-wonder-1.0", 1.0, 0.01, 0.5), ep("b", "muse-spark-1.3", 4.0, 0.05, 0.8), ep("c", "muse-spark-1.2", 9.0, 0.2, 0.95)]; E_c, E_t, P = race_metrics(eps, "t"); rnd = random.Random(2); N = 200000; sc = st = sp = 0.0
        for _ in range(N):
            ok = [rnd.random() < e.p("t") for e in eps]; T = min((e.t_eff() for e, o in zip(eps, ok) if o), default=max(e.t_eff() for e in eps)); st += T; sp += any(ok); sc += sum(e.cost * min(1, T / e.t_eff()) for e in eps)
        self.assertAlmostEqual(st / N, E_t, delta=0.02 * E_t); self.assertAlmostEqual(sc / N, E_c, delta=0.02 * E_c); self.assertAlmostEqual(sp / N, P, delta=0.005)
    def test_sequential_formula(self):
        a, b = ep("a", "muse-wonder-1.0", 2.0, 0.1, 0.5), ep("b", "muse-spark-1.3", 6.0, 0.4, 0.9); c, t, ok = seq_metrics([a, b], "t")
        self.assertAlmostEqual(c, 0.1 + 0.5 * 0.4); self.assertAlmostEqual(t, 2.0 + 0.5 * 6.0); self.assertAlmostEqual(ok, 1 - 0.5 * 0.1)
    def test_picks_fast_endpoint_even_with_lower_success(self):
        slow = ep("slow", "muse-spark-1.3", 30.0, 0.05, 0.99); fast = ep("fast", "muse-wonder-1.0", 2.0, 0.05, 0.90); r = SpeedRouter([slow, fast])
        self.assertEqual(max(r.eligible("coder"), key=lambda e: e.p("t")).name, "slow"); plan = r.plan("coder", "t", price_per_s=0.05); self.assertEqual(plan["eps"][0].name, "fast")
    def test_queueing_delay_demotes_a_busy_endpoint(self):
        busy = ep("busy", "muse-wonder-1.0", 1.0, 0.05, 0.9, arrival_per_s=0.95); idle = ep("idle", "muse-spark-1.3", 3.0, 0.05, 0.9)
        self.assertGreater(busy.t_eff(), 15); self.assertEqual(SpeedRouter([busy, idle]).plan("coder", "t", 0.05)["eps"][0].name, "idle")
    def test_race_chosen_only_when_time_is_valuable(self):
        a, b = ep("a", "muse-wonder-1.0", 1.0, 0.01, 0.5), ep("b", "muse-spark-1.3", 8.0, 0.05, 0.95); r = SpeedRouter([a, b])
        self.assertEqual(r.plan("coder", "t", price_per_s=0.0001)["strategy"], "sequential"); self.assertTrue(r.plan("coder", "t", price_per_s=1.0)["strategy"].startswith("race"))
    def test_prod_is_gateway_only_test_allows_subscription_lane(self):
        gw, sub = ep("gw", "muse-wonder-1.0", 3.0, 0.2, 0.9), ep("sub", "muse-wonder-1.0", 3.0, 0.0, 0.9, via="direct")
        self.assertEqual([e.name for e in SpeedRouter([gw, sub], "prod").eligible("coder")], ["gw"]); self.assertEqual({e.name for e in SpeedRouter([gw, sub], "test").eligible("coder")}, {"gw", "sub"})
        r = SpeedRouter([sub], "test"); plan = r.plan("coder", "t", 0.01); self.assertEqual(r.execute(plan, "t", lambda e: 1, lambda o: True)["lane"], "direct")
    def test_race_wall_clock_beats_slow_sequential(self):
        a, b = ep("a", "muse-wonder-1.0", 0.05, 0.01, 0.9), ep("b", "muse-spark-1.3", 0.4, 0.05, 0.9); r = SpeedRouter([a, b]); plan = dict(strategy="race2", eps=[a, b])
        res = r.execute(plan, "t", lambda e: (time.sleep(e.svc), e.name)[1], lambda o: True); self.assertEqual(res["endpoint"], "a"); self.assertLess(res["secs"], 0.25)

class AttentionTests(unittest.TestCase):
    NAMES = ["mem", "lat", "net", "sec", "idle"]
    def feed(self, att, n, rnd, shift=None):
        rows = []
        for i in range(n):
            obs = {k: rnd.gauss(0, 1) for k in self.NAMES}
            if shift and i >= shift[0]: obs[shift[1]] += shift[2]
            rows.append(att.step(obs))
        return rows
    def mk(self, **kw): return Attention(self.NAMES, intent={"mem", "lat"}, **kw)
    def test_shifts_to_planted_intent_signal_within_two_steps(self):
        att = self.mk(); rows = self.feed(att, 200, random.Random(1), shift=(100, "lat", 6.0)); first = next(r["step"] for r in rows[100:] if r["focus"] == "lat"); self.assertLessEqual(first - 101, 2)
    def test_no_thrash_on_pure_noise(self):
        att = self.mk(); self.feed(att, 3000, random.Random(3)); self.assertLess(att.intent_report()["switch_rate"], 0.02)
    def test_focus_sharpens_while_held(self):
        att = self.mk(); rows = self.feed(att, 300, random.Random(4), shift=(60, "mem", 5.0)); self.assertLess(rows[-1]["entropy"], rows[61]["entropy"] + 1e-9); self.assertLess(att.T, att.tmax)
    def test_off_intent_safety_signal_preempts(self):
        att = self.mk(); rows = self.feed(att, 150, random.Random(5), shift=(100, "sec", 12.0)); self.assertEqual(rows[100]["focus"], "sec"); self.assertTrue(rows[100]["preempted"])
    def test_off_intent_moderate_noise_does_not_steal_focus(self):
        att = self.mk(); rows = self.feed(att, 200, random.Random(6), shift=(100, "idle", 4.0)); self.assertNotEqual(rows[-1]["focus"], "idle")
    def test_drift_flag_when_attention_leaves_intent(self):
        att = Attention(self.NAMES, intent={"mem"}, leak=1.0, drift_tau=0.5, drift_n=5); rnd = random.Random(7)
        for i in range(120): att.step({k: rnd.gauss(0, 1) + (6.0 if (i > 40 and k == "net") else 0.0) for k in self.NAMES})
        self.assertGreater(att.intent_report()["drift_steps"], 0)
    def test_tracker_standardizes(self):
        t = Tracker(); rnd = random.Random(8); z = [t.update(rnd.gauss(10, 2)) for _ in range(2000)][200:]; self.assertAlmostEqual(sum(z) / len(z), 0, delta=0.15); self.assertAlmostEqual((sum(x * x for x in z) / len(z)) ** 0.5, 1.0, delta=0.15)

class Distill(unittest.TestCase):
    def data(self, n=300, d=12, r=3, noise=0.05, seed=1):
        rnd = random.Random(seed); B = [[rnd.gauss(0, 1) for _ in range(d)] for _ in range(r)]; scale = [5.0, 3.0, 2.0]
        out = []
        for _ in range(n):
            z = [rnd.gauss(0, 1) * scale[i] for i in range(r)]                      # latent factors drawn ONCE per sample
            out.append([sum(z[i] * B[i][j] for i in range(r)) + rnd.gauss(0, noise) for j in range(d)])
        return out
    def test_recovers_planted_rank_and_error_identity(self):
        X = self.data(); m = pca(X, 0.99); self.assertEqual(m["k"], 3); self.assertGreater(m["retained"], 0.99); print("\n", compression(m))
        full = pca(X, 1.0, iters=800); discarded = (full["total"] - sum(m["eig"])) * (len(X) - 1); self.assertAlmostEqual(recon_error(m, X), discarded, delta=1e-4 * max(1.0, discarded))
    def test_roundtrip_exact_at_full_rank(self):
        X = self.data(n=60, d=5, r=3, noise=0.5); m = pca(X, 1.0, iters=800); self.assertLess(max(abs(a - b) for x in X[:5] for a, b in zip(x, reconstruct(m, project(m, x)))), 1e-6)
    def test_jl_bound_preserves_distances(self):
        rnd = random.Random(9); n, d, eps = 60, 1500, 0.5; k = jl_min_dim(n, eps); R = random_projection(d, k); P = [[rnd.gauss(0, 1) for _ in range(d)] for _ in range(n)]; Q = [rp_apply(R, x) for x in P]; bad = tot = 0
        for i, j in itertools.combinations(range(0, n, 3), 2):
            a = sum((x - y) ** 2 for x, y in zip(P[i], P[j])); b = sum((x - y) ** 2 for x, y in zip(Q[i], Q[j])); tot += 1; bad += abs(b / a - 1) > eps
        self.assertLess(bad / tot, 0.01); self.assertLess(k, d)
    def test_jl_dim_formula(self): self.assertEqual(jl_min_dim(1000, 0.1), math.ceil(4 * math.log(1000) / (0.005 - 0.001 / 3)))

class CellTests(unittest.TestCase):
    def cell(self, mode="prod", ready_bits=(), c=30, t=60, extra=(), budget=1.0):
        st = State(c, t); st.step({"bits": {k: 1 for k in ready_bits}}) if ready_bits else None
        eps = [ep("g-wonder", "muse-wonder-1.0", 2.0, 0.02, 0.9, task="x"), ep("g-spark", "muse-spark-1.3", 6.0, 0.1, 0.97, task="x"), ep("g-vision", "sam-3.1", 1.0, 0.03, 0.9, task="x"), *extra]
        att = Attention(["mem", "lat", "sec"], intent={"mem"}); return MicroCell("cell-1", st, SpeedRouter(eps, mode), att, budget_usd=budget)
    RUN = staticmethod(lambda e: e.name); CHK = staticmethod(lambda o: True)
    def test_ready_gates_work_kinds(self):
        c = self.cell(); self.assertEqual(c.act("text", "observe", "x", self.RUN, self.CHK)["status"], "OK")
        self.assertEqual(c.act("text", "draft", "x", self.RUN, self.CHK)["status"], "BLOCKED"); self.assertEqual(c.act("text", "materialize", "x", self.RUN, self.CHK)["status"], "BLOCKED")
        c.confirm({"bits": {"WHAT": 1, "WHY": 1, "WHO": 1, "WHERE": 1}}); self.assertEqual(c.act("text", "draft", "x", self.RUN, self.CHK)["status"], "OK")
    def test_stops_block_materialize_until_approved(self):
        c = self.cell(c=31, t=63); c.confirm({"bits": {k: 1 for k in ("WHO", "WHAT", "WHERE", "WHEN", "WHY", "HOW")}, "tempo": 0}); r = c.act("text", "materialize", "x", self.RUN, self.CHK)
        self.assertEqual(r["status"], "BLOCKED"); self.assertTrue(all(any(s in p for p in r["problems"]) for s in ("S2", "S3", "S6")))
        self.assertEqual(c.act("text", "materialize", "x", self.RUN, self.CHK, approvals=("S2", "S3", "S6:fate:ISOLATED"))["status"], "OK")
    def test_non_meta_and_unproven_models_cannot_join_a_cell(self):
        with self.assertRaises(ValueError): TimedEndpoint("x", "grok-4", "live", 0.1, 1.0)
        with self.assertRaises(ValueError): TimedEndpoint("y", "chat-12g", "live", 0.1, 1.0)
    def test_modalities_route_to_role_specific_endpoints_and_no_signal_is_explicit(self):
        c = self.cell(); self.assertEqual(c.act("vision", "observe", "x", self.RUN, self.CHK)["endpoint"], "g-vision"); self.assertEqual(c.act("voice", "observe", "x", self.RUN, self.CHK)["status"], "NO_SIGNAL")
    def test_prod_excludes_subscription_lane_test_mode_uses_it(self):
        sub = ep("sub", "muse-wonder-1.0", 0.5, 0.0, 0.99, task="x", via="direct")
        prod = self.cell("prod", extra=[sub]); r = prod.act("text", "observe", "x", self.RUN, self.CHK); self.assertNotEqual(r["endpoint"], "sub")
        test = self.cell("test", extra=[sub]); r2 = test.act("text", "observe", "x", self.RUN, self.CHK); self.assertEqual((r2["endpoint"], r2["lane"]), ("sub", "direct"))
    def test_budget_cap(self):
        c = self.cell(budget=0.05); results = [c.act("text", "observe", "x", self.RUN, self.CHK)["status"] for _ in range(6)]; self.assertIn("BLOCKED", results); self.assertEqual(results[0], "OK")
    def test_provenance_rows_carry_address_focus_intent_and_chain_verifies(self):
        c = self.cell(); rnd = random.Random(1)
        for _ in range(30): c.observe({k: rnd.gauss(0, 1) for k in ("mem", "lat", "sec")})
        c.observe({"mem": 0.0, "lat": 0.0, "sec": 40.0}); c.act("text", "observe", "x", self.RUN, self.CHK); rows = c.led.rows
        act = [r for r in rows if r["event"] == "ACT"][0]; self.assertEqual(act["addr"], c.state.view()["key"]); self.assertEqual(act["intent"], ["mem"]); self.assertIn(act["focus"], ("mem", "lat", "sec"))
        self.assertTrue(any(r["event"] == "FOCUS" and r["preempted"] for r in rows)); self.assertTrue(c.led.verify())
    def test_human_only_sets_bits(self):
        c = self.cell()
        with self.assertRaises(PermissionError): c.state.step({"bits": {"WHO": 1}}, source="agent")
if __name__ == "__main__": unittest.main(verbosity=1)
