"""Meta client and insights: ledger, Meta-only guard, budget, replay, validation of model output, consent gate. No network."""
import datetime as dt, json, os, tempfile, threading, unittest, urllib.error, urllib.request
from unittest import mock

from stretto import consent, demo, insights, meta, segment, analyze
from stretto.server import make_server
from stretto.store import Store

MSG = [dict(role="user", content="hi")]


def reply(model="muse-spark-1.3", content="{}", usage=True, p=1000, c=500):
    r = dict(model=model, choices=[dict(message=dict(content=content), finish_reason="stop")])
    if usage:
        r["usage"] = dict(prompt_tokens=p, completion_tokens=c, completion_tokens_details=dict(reasoning_tokens=200))
    return r


def env(**kw):
    base = {k: v for k, v in os.environ.items() if k not in ("MODEL_API_KEY", "STRETTO_REPLAY", "STRETTO_RECORD")}
    base.update(kw)
    return mock.patch.dict(os.environ, base, clear=True)


class Client(unittest.TestCase):
    def test_no_access_is_a_clear_error_and_nothing_is_called(self):
        with env(), mock.patch.object(meta, "_post", side_effect=AssertionError("called")):
            with self.assertRaises(meta.ModelUnavailable) as c:
                meta.chat(Store(":memory:"), "t", MSG, 1.0)
        self.assertIn("MODEL_API_KEY", str(c.exception))

    def test_ledger_has_tokens_cost_and_a_valid_chain(self):
        s = Store(":memory:")
        with env(MODEL_API_KEY="k-secret"), mock.patch.object(meta, "_post", return_value=reply()):
            r = meta.chat(s, "insights", MSG, 1.0)
            meta.chat(s, "insights", MSG, 1.0)
        row = s.q("SELECT * FROM model_calls ORDER BY id")[0]
        self.assertEqual((row["prompt_tokens"], row["completion_tokens"], row["reasoning_tokens"], row["status"], row["mode"]), (1000, 500, 200, "ok", "direct"))
        self.assertAlmostEqual(row["cost_usd"], (1000 * 1.25 + 500 * 4.25) / 1e6, places=6)
        self.assertTrue(meta.verify_chain(s))
        self.assertNotIn("k-secret", json.dumps(s.q("SELECT * FROM model_calls")))
        s.x("UPDATE model_calls SET cost_usd=0 WHERE id=1")
        self.assertFalse(meta.verify_chain(s))

    def test_non_meta_model_is_refused_even_if_the_api_returns_it(self):
        s = Store(":memory:")
        with env(MODEL_API_KEY="k"), mock.patch.object(meta, "_post", return_value=reply(model="gpt-4o")):
            with self.assertRaises(meta.ModelUnavailable):
                meta.chat(s, "t", MSG, 1.0)
        self.assertEqual(s.q("SELECT status FROM model_calls")[0]["status"], "failed")     # the failure is in the ledger too
        with env(MODEL_API_KEY="k"):
            with self.assertRaises(meta.ModelUnavailable):
                meta.chat(s, "t", MSG, 1.0, model="gpt-4o")                                 # and a non-Meta request never leaves

    def test_unmetered_reply_is_refused(self):
        with env(MODEL_API_KEY="k"), mock.patch.object(meta, "_post", return_value=reply(usage=False)):
            with self.assertRaises(meta.ModelUnavailable):
                meta.chat(Store(":memory:"), "t", MSG, 1.0)

    def test_budget_stops_the_next_call(self):
        s = Store(":memory:")
        with env(MODEL_API_KEY="k"), mock.patch.object(meta, "_post", return_value=reply(p=1_000_000, c=500_000)) as post:
            meta.chat(s, "t", MSG, 1.0)                    # about $3.4: over a $1 cap
            with self.assertRaises(meta.BudgetExceeded):
                meta.chat(s, "t", MSG, 1.0)
        self.assertEqual(post.call_count, 1)

    def test_record_then_replay_without_a_key(self):
        s = Store(":memory:")
        with tempfile.TemporaryDirectory() as d:
            with env(MODEL_API_KEY="k", STRETTO_RECORD=d), mock.patch.object(meta, "_post", return_value=reply(content="recorded")):
                meta.chat(s, "t", MSG, 1.0)
            self.assertEqual(len(os.listdir(d)), 1)
            with env(STRETTO_REPLAY=d), mock.patch.object(meta, "_post", side_effect=AssertionError("network used")):
                self.assertEqual(meta.chat(s, "t", MSG, 1.0)["text"], "recorded")
                self.assertEqual(meta.status(s, 1.0)["mode"], "replay")
                with self.assertRaises(meta.ModelUnavailable):
                    meta.chat(s, "t", [dict(role="user", content="a different request")], 1.0)

    def test_http_errors_hide_the_body(self):
        err = urllib.error.HTTPError("u", 401, "x", {}, None)
        with env(MODEL_API_KEY="k"), mock.patch("urllib.request.OpenerDirector.open", side_effect=err):
            with self.assertRaises(meta.ModelUnavailable) as c:
                meta._post("/chat/completions", {})
        self.assertIn("401", str(c.exception))


def sim_day():
    t0 = dt.datetime.combine(dt.date.today() - dt.timedelta(days=1), dt.time()).timestamp()
    ev = [dict(e, src="simulated") for e in demo.samples(t0)]
    bl = segment.blocks(ev)
    found, loss = analyze.findings(bl)
    return dict(date=(dt.date.today() - dt.timedelta(days=1)).isoformat(), summary=analyze.summary(bl), findings=found, loss_s=loss, sources=[])


class Insights(unittest.TestCase):
    def setUp(self):
        self.day = sim_day()
        self.f = insights.facts(self.day)

    def test_titles_and_urls_never_reach_the_prompt(self):
        ev = [dict(ts=1_760_000_000 + i * 5, dur=5, app="chrome", title="SECRET payroll Q3.xlsx", domain="docs.google.com", idle=0, src="x") for i in range(60)]
        bl = segment.blocks(ev)
        f, loss = analyze.findings(bl)
        day = dict(date="2026-11-03", summary=analyze.summary(bl), findings=f, loss_s=loss, sources=[])
        blob = json.dumps(insights.messages(insights.facts(day)))
        self.assertNotIn("SECRET", blob)
        self.assertNotIn("payroll", blob)
        self.assertIn("docs.google.com", blob)           # names and domains are what is sent, and the notice says so

    def good(self):
        return json.dumps(dict(headline="Most lost time came from one route", actions=[dict(finding="f0", title="Shortcut the loop", how="Create a template for this route.")]))

    def test_valid_reply_passes(self):
        r, d = insights.validate(self.good(), self.f)
        self.assertEqual(len(r["actions"]), 1)
        self.assertEqual(sum(d.values()), 0)

    def test_fenced_json_is_accepted(self):
        r, _ = insights.validate("```json\n" + self.good() + "\n```", self.f)
        self.assertEqual(len(r["actions"]), 1)

    def test_invented_finding_and_invented_number_and_medical_advice_are_dropped(self):
        bad = json.dumps(dict(headline="You lost 9999 minutes", actions=[
            dict(finding="f99", title="Ghost", how="Does not exist."),
            dict(finding="f0", title="Save 777 minutes", how="Do it."),
            dict(finding="f0", title="Reduce anxiety", how="See a therapist about your focus."),
            dict(finding="f0", title="Keep it", how="Batch the lookups once an hour.")]))
        r, d = insights.validate(bad, self.f)
        self.assertEqual([a["title"] for a in r["actions"]], ["Keep it"])
        self.assertEqual(r["headline"], "")
        self.assertEqual((d["unknown_finding"], d["blocked_topic"]), (1, 1))
        self.assertGreaterEqual(d["invented_number"], 2)

    def test_numbers_that_exist_in_the_facts_are_allowed(self):
        n = self.f["findings"][0]["minutes"]
        ok = json.dumps(dict(headline=f"{n} minutes were lost in one pattern", actions=[]))
        self.assertEqual(insights.validate(ok, self.f)[0]["headline"], f"{n} minutes were lost in one pattern")

    def test_garbage_and_zero_width_characters(self):
        self.assertEqual(insights.validate("sorry I cannot", self.f)[1]["malformed"], 1)
        z = json.dumps(dict(headline="Tighten​ the loop", actions=[]))
        r, d = insights.validate(z, self.f)
        self.assertEqual((r["headline"], d["sanitized"]), ("Tighten the loop", 1))


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = Store(":memory:")
        cls.srv, cls.tok = make_server(cls.store, 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def call(self, method, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, data=json.dumps(body).encode() if body is not None else None)
        req.add_header("Host", f"127.0.0.1:{self.port}"); req.add_header("X-Stretto-Token", self.tok)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_insights_flow_consent_then_model_then_cache(self):
        code, seeded = self.call("POST", "/api/demo/seed", {})
        date = seeded["date"]
        code, r = self.call("POST", "/api/insights", dict(date=date))
        self.assertEqual((code, r["error"], r["family"]), (403, "consent_required", "meta-insights"))      # nothing sent to Meta without acceptance
        self.assertEqual(self.call("GET", f"/api/insights?date={date}")[1]["reason"], "consent")
        self.call("POST", "/api/consent", dict(device="local", family="meta-insights", action="grant", granted_by="T P", typed=consent.phrase("meta-insights")))
        with env():
            code, r = self.call("POST", "/api/insights", dict(date=date))
        self.assertEqual((code, r["error"]), (503, "model_unavailable"))                                   # accepted, but no key and no recording
        good = json.dumps(dict(headline="One route cost the most", actions=[dict(finding="f0", title="Shortcut the loop", how="Make a template.")]))
        with env(MODEL_API_KEY="k"), mock.patch.object(meta, "_post", return_value=reply(content=good)) as post:
            code, r = self.call("POST", "/api/insights", dict(date=date))
            self.assertEqual(code, 200)
            self.assertEqual((r["basis"], r["cached"], r["mode"], len(r["actions"])), ("inferred", False, "direct", 1))
            code, r2 = self.call("POST", "/api/insights", dict(date=date))
            self.assertTrue(r2["cached"])
            self.assertEqual(post.call_count, 1)                                                           # the second request cost nothing
            self.assertTrue(self.call("GET", f"/api/insights?date={date}")[1]["available"])
        code, calls = self.call("GET", "/api/meta/calls?limit=5")
        self.assertEqual((code, calls["chain_ok"], calls["calls"][0]["model"]), (200, True, "muse-spark-1.3"))
        self.assertGreater(self.call("GET", "/api/meta/status")[1]["calls_today"], 0)

    def test_revoking_stops_further_calls(self):
        self.call("POST", "/api/consent", dict(device="dX", family="meta-insights", action="grant", granted_by="T P", typed=consent.phrase("meta-insights")))
        self.call("POST", "/api/consent", dict(device="dX", family="meta-insights", action="revoke", granted_by="T P"))
        self.assertEqual(self.call("POST", "/api/insights", dict(device="dX", date="2026-11-03"))[0], 403)

    def test_notice_lists_what_is_sent_and_never_sent(self):
        n = self.call("GET", "/api/consent/notice?family=meta-insights")[1]
        self.assertIn("titles", " ".join(n["never"]).lower())
        self.assertIn("api.meta.ai", " ".join(n["goes"]))


if __name__ == "__main__":
    unittest.main()
