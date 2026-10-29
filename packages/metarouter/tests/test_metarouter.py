# SPDX-License-Identifier: Apache-2.0
import math, random, unittest
from metarouter.policy import CATALOG, check_agent, scan_text, egress_policy, local_fit, gateway_request
from metarouter.router import Endpoint, MetaRouter, EmbeddingStore, PredictionRouter, admit

class Policy(unittest.TestCase):
    def test_gateway_request_rejects_cross_provider_and_wrong_route(self):
        for model, provider in (("muse-wonder-1.0", "xai"), ("muse-glimmer-30b", "meta"), ("sam-3.1", "meta")):
            with self.assertRaises(ValueError):
                gateway_request(model, [], "dummy", provider=provider)

    def test_non_meta_agents_and_models_refused(self):
        self.assertEqual(check_agent(dict(id="a", model="muse-wonder-1.0")), [])
        for m in ("grok-code-fast", "claude-opus", "gpt-5", "qwen3"): self.assertTrue(check_agent(dict(id="a", model=m)), m)
        with self.assertRaises(ValueError): MetaRouter([Endpoint("x", "grok-code-fast", "live", 0.1, roles={"coder"})])
    def test_scanner_finds_vendors_and_flags_runtimes_to_verify(self):
        v, w = scan_text("model = 'grok-4'\nuse Claude here\nserved by vllm\nmuse-wonder-1.0 ok", "f.py")
        self.assertEqual([(p, l) for p, l, _ in v], [("f.py", 1), ("f.py", 2)]); self.assertEqual([m for _, _, m in w], ["vllm"])
    def test_every_catalogued_model_is_meta(self): self.assertTrue(all(m["provider"] in ("meta-api", "meta-local") for m in CATALOG.values()))
    def test_glimmer_does_not_fit_on_measured_free_ram(self):
        r = local_fit("muse-glimmer-30b", {"node-a": 6.2, "node-b": 5.9, "node-c": 22.9})
        self.assertFalse(any(x["fits"] for x in r.values())); self.assertAlmostEqual(r["node-c"]["short_by"], 3.1, places=2)
        self.assertTrue(local_fit("muse-glimmer-30b", {"n": 40})["n"]["fits"])
    def test_egress_policy_text(self): t = egress_policy(); self.assertIn("kind: NetworkPolicy", t); self.assertIn("UNTESTED", t)
    def test_agents_may_reach_only_dns_and_the_gateway(self):
        agents = egress_policy().split("---")[0]; self.assertIn("192.0.2.11/32", agents); self.assertNotIn("0.0.0.0/0", agents); self.assertIn("port: 8443", agents)
        gw = egress_policy().split("---")[1]; self.assertIn("0.0.0.0/0", gw); self.assertIn("192.0.2.60/32", gw)
    def test_unproven_gateway_model_refused_everywhere(self):
        self.assertTrue(check_agent(dict(id="a", model="chat-12g"))); self.assertIn("origin is not recorded", check_agent(dict(id="a", model="chat-12g"))[0])
        with self.assertRaises(ValueError): gateway_request("chat-12g", [], "vk")
        with self.assertRaises(ValueError): gateway_request("gpt-5", [], "vk")
        r = gateway_request("muse-wonder-1.0", [{"role": "user", "content": "hi"}], "vk-agent-1"); self.assertTrue(r["url"].startswith("https://gateway.example.internal:8443")); self.assertEqual(r["body"]["model"], "meta/muse-wonder-1.0")
    def test_direct_endpoints_excluded_when_gateway_required(self):
        eps = [Endpoint("muse-sub", "muse-wonder-1.0", "live", 0.1, via="direct"), Endpoint("gw-wonder", "muse-wonder-1.0", "live", 0.4)]
        self.assertEqual([e.name for e in MetaRouter(eps).eligible("coder")], ["gw-wonder"]); self.assertEqual(len(MetaRouter(eps, require_gateway=False).eligible("coder")), 2)

class Routing(unittest.TestCase):
    def eps(self):
        return [Endpoint("wonder", "muse-wonder-1.0", "live", 0.4), Endpoint("spark", "muse-spark-1.3", "live", 1.0), Endpoint("glimmer", "muse-glimmer-30b", "not-deployed", 0.05),
                Endpoint("paid-spark", "muse-spark-1.2", "live", 0.8, paid_credits=True)]
    def test_not_deployed_and_paid_credits_never_used(self):
        r = MetaRouter(self.eps()); used = {e.name for e in r.eligible("coder")}; self.assertEqual(used, {"wonder", "spark"})
        r2 = MetaRouter(self.eps(), allow_credits=True); self.assertIn("paid-spark", {e.name for e in r2.eligible("coder")})
    def test_no_eligible_endpoint_is_an_explicit_stop_not_a_fallback(self):
        r = MetaRouter([Endpoint("glimmer", "muse-glimmer-30b", "not-deployed", 0.05)]); out = r.route("coder", lambda e: "x", lambda o: True)
        self.assertEqual(out["status"], "NO_SIGNAL"); self.assertIn("glimmer: not-deployed", out["why"])
    def test_embed_has_no_signal_until_a_meta_embedder_is_live(self):
        out = MetaRouter(self.eps()).route("embed", lambda e: [0.0], lambda o: True); self.assertEqual(out["status"], "NO_SIGNAL"); self.assertIn("no embeddings route", out["why"])
    def test_learns_specialists_and_cheapest_sufficient_model(self):
        truth = {("wonder", "summarize"): 0.9, ("wonder", "refactor"): 0.15, ("spark", "summarize"): 0.95, ("spark", "refactor"): 0.9}
        r = MetaRouter([Endpoint("wonder", "muse-wonder-1.0", "live", 0.4), Endpoint("spark", "muse-spark-1.3", "live", 1.0)], seed=5); rng = random.Random(9); total = 0.0; N = 600
        for i in range(N):
            task = "summarize" if i % 2 == 0 else "refactor"
            res = r.route("coder", lambda e: rng.random() < truth[(e.name, task)], lambda o: o, task=task, explore=True, measure=lambda e, o: {"wonder": 0.4, "spark": 1.0}[e.name]); total += res["cost"]
        first = {t: r.order("coder", t)[0].name for t in ("summarize", "refactor")}
        self.assertEqual(first, {"summarize": "wonder", "refactor": "spark"})
        self.assertLess(total / N, 0.80)                       # always asking spark first costs ~1.0 per task
    def test_observed_cost_updates_the_estimate(self):
        e = Endpoint("wonder", "muse-wonder-1.0", "live", 1.0); r = MetaRouter([e]); r.route("coder", lambda e: 1, lambda o: True, measure=lambda e, o: 3.0)
        self.assertAlmostEqual(e.cost, 0.7 * 1.0 + 0.3 * 3.0)

class Embeddings(unittest.TestCase):
    def test_binary_prefilter_with_rerank_recall(self):
        rng = random.Random(1); d, n = 64, 1500; centers = [[rng.gauss(0, 1) for _ in range(d)] for _ in range(30)]; st = EmbeddingStore()
        vecs = [[c + rng.gauss(0, 0.5) for c in centers[i % 30]] for i in range(n)]
        for i, v in enumerate(vecs): st.add("m1", "v1", i, v)
        rec = []
        for q in range(40):
            qv = [c + rng.gauss(0, 0.5) for c in centers[q % 30]]; a, b = set(st.search("m1", "v1", qv, 10, shortlist=10)), set(st.exact("m1", "v1", qv, 10)); rec.append(len(a & b) / 10)
        self.assertGreaterEqual(sum(rec) / len(rec), 0.85)
    def test_cross_model_comparison_refused(self):
        st = EmbeddingStore(); st.add("m1", "v1", "a", [1.0, 0.0]); st.add("m2", "v1", "b", [1.0, 0.0])
        with self.assertRaises(KeyError): st.search("m3", "v1", [1.0, 0.0])
        with self.assertRaises(KeyError): st.search("m1", "v2", [1.0, 0.0])
        with self.assertRaises(KeyError): st.search("m1", "v1", [1.0, 0.0, 0.0])

class Prediction(unittest.TestCase):
    def test_hedge_regret_under_bound(self):
        rng = random.Random(4); T = 800; pr = PredictionRouter(["last", "mean", "seasonal"], T); x = [0.5 + 0.3 * math.sin(2 * math.pi * t / 24) + rng.gauss(0, 0.05) for t in range(T + 24)]
        for t in range(24, T + 24):
            f = {"last": x[t - 1], "mean": 0.5, "seasonal": x[t - 24]}; pr.predict(f); pr.update(f, x[t], scale=1.0)
        self.assertLessEqual(pr.regret(), pr.bound(T))
    def test_admission_gate(self):
        self.assertFalse(admit([0.1] * 10, [0.2] * 10)[0]); self.assertTrue(admit([0.1] * 40, [0.2] * 40)[0]); self.assertFalse(admit([0.19] * 40, [0.2] * 40)[0])
if __name__ == "__main__": unittest.main(verbosity=1)
