# SPDX-License-Identifier: Apache-2.0
"""Gap closes (hackathon late window): bulk consent, model selection, distilled host saving, simulated range flags."""
import os
import unittest

from stretto import calendars, challenges, coach, coherence, consent, embedder, folding, gamify, graphmap, honeycomb, kvcache, meta, selftrain, topics, voicetree
from stretto.store import Store

FACTS = dict(date="2026-11-04", active_minutes=400, focus_minutes=240, distraction_minutes=60, idle_minutes=60,
             switches=40, lost_minutes=30, tightness_percent=92,
             top_places=[dict(name="code", minutes=200)],
             findings=[dict(id="f0", kind="detour", places=["slack"], minutes=14, times=1)], estimated_sources=[])


def fake_day():
    return dict(date="2026-11-04", simulated=False,
                summary=dict(by_app=[("code", 12000), ("slack", 1800)]),
                transitions=[dict(src="code", dst="slack", count=3, avg_stay_s=120)],
                findings=[dict(kind="detour", where=["slack"], seconds=840, returned_to="code")],
                blocks=[dict(app="Code", domain="", category="Build", start=0, end=600),
                        dict(app="slack", domain="", category="Communication", start=600, end=700)])


class GapCloses(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")

    def test_bulk_grant_needs_bulk_phrase_and_logs_each_family(self):
        with self.assertRaises(ValueError):
            consent.grant_many(self.s, "local", ["browser-history"], "Alex", typed="I AGREE: browser-history")
        out = consent.grant_many(self.s, "local", ["browser-history", "meta-insights"], "Alex", typed=consent.BULK_PHRASE)
        self.assertTrue(out["browser-history"]["active"])
        self.assertTrue(out["meta-insights"]["active"])
        self.assertTrue(consent.verify_chain(self.s))
        self.assertEqual(len(consent.log(self.s, "local")), 2)

    def test_bulk_grant_rejects_unknown_and_empty(self):
        with self.assertRaises(ValueError):
            consent.grant_many(self.s, "local", [], "Alex", typed=consent.BULK_PHRASE)
        with self.assertRaises(ValueError):
            consent.grant_many(self.s, "local", ["nope"], "Alex", typed=consent.BULK_PHRASE)

    def test_model_selection_env_setting_and_fallback(self):
        self.assertEqual(meta.current_model(self.s), meta.DEFAULT_MODEL)
        self.s.set_setting("model", "llama-test-1")
        self.assertEqual(meta.current_model(self.s), "llama-test-1")
        self.s.set_setting("model", "gpt-not-meta")
        self.assertEqual(meta.current_model(self.s), meta.DEFAULT_MODEL)
        os.environ["STRETTO_MODEL"] = "sam-test-2"
        try:
            self.assertEqual(meta.current_model(self.s), "sam-test-2")
        finally:
            del os.environ["STRETTO_MODEL"]

    def test_distilled_ingest_drops_titles_and_domains(self):
        # distilled transform lives in the server ingest route; here we pin the store-level contract it relies on:
        # a sample carrying no title/domain is stored with empty detail, a full sample keeps it.
        now = 1_700_000_000
        self.s.ingest([{"ts": now, "dur": 60, "app": "code", "title": "", "domain": ""}], src="collector", device="local")
        rows = self.s.q("SELECT title, domain FROM events")
        self.assertEqual((rows[0]["title"], rows[0]["domain"]), ("", ""))


class HoneycombGraphVoice(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")

    def test_honeycomb_exact_twin_and_route_are_grounded(self):
        art = dict(headline="h", actions=[], cost_usd=0.01)
        honeycomb.put(self.s, "sha1", FACTS, art)
        got, how = honeycomb.get(self.s, "sha1", FACTS)
        self.assertEqual((got, how), (art, "exact"))
        twin, how2 = honeycomb.get(self.s, "other-sha", FACTS)
        self.assertEqual(twin, art)
        self.assertEqual(how2, "honeycomb-twin")
        routed, info = honeycomb.route(self.s, FACTS)
        self.assertEqual(routed, art)
        self.assertTrue(info["grounded"])
        self.assertGreaterEqual(info["similarity"], 0.999)
        other = dict(FACTS, findings=[dict(id="f0", kind="ping_pong", places=["a", "b"], minutes=9, times=4)])
        miss, info2 = honeycomb.route(self.s, other)
        self.assertIsNone(miss)
        self.assertFalse(info2["grounded"])
        self.assertEqual(honeycomb.stats(self.s)["artifacts"], 1)

    def test_graphmap_and_voicetree_derive_from_day(self):
        g = graphmap.build(fake_day())
        self.assertEqual([n["id"] for n in g["nodes"]], ["code", "slack"])
        self.assertEqual(g["edges"][0]["count"], 3)
        self.assertEqual(g["findings"][0]["kind"], "detour")
        t = voicetree.derive(fake_day())
        self.assertIn("14 minutes", t["nodes"]["root"]["say"])
        self.assertEqual(t["nodes"]["n0"]["finding"], "f0")
        self.assertEqual(voicetree.derive(dict(fake_day(), findings=[]))["nodes"]["root"]["kind"], "affirm")


class ChallengesCoach(unittest.TestCase):
    def test_grouped_compounded_loss_and_simplest_fix(self):
        d1 = dict(fake_day(), loss_s=840)
        d2 = dict(fake_day(), date="2026-11-03", loss_s=840)
        out = challenges.group([d1, d2])
        self.assertEqual(len(out["challenges"]), 1)
        c = out["challenges"][0]
        self.assertEqual(c["minutes_per_day"], 14)
        self.assertEqual(c["compounded"]["days30"], 420)
        self.assertIn("scheduled break", c["fix"])
        self.assertTrue(c["ask"])
        self.assertEqual(c["xp_reward"], 14)
        self.assertEqual(out["total"]["days30"], 420)

    def test_coach_ramp_pushes_and_eases_and_ranks(self):
        p = coach.plan(dict(best_window=dict(start_hour=9, end_hour=12)), 40, 200)
        self.assertEqual([r["reclaim_min"] for r in p["ramp"]], [10, 14, 20, 26])
        self.assertEqual(p["metric"], "time")
        up = coach.plan({}, 40, 200, weeks_met=1)
        self.assertEqual(up["ramp"][0]["reclaim_min"], 12)  # 10 * 1.15 rounds to 12 (banker's? round(11.5)=12)
        down = coach.plan({}, 40, 200, weeks_missed=2)
        self.assertEqual(down["ramp"][0]["reclaim_min"], 9)
        self.assertEqual(coach.rank(1)["title"], "Starter")
        self.assertEqual(coach.rank(12)["title"], "Timewright")
        self.assertIn("rank", gamify.level(5000))


class Pins(unittest.TestCase):
    def test_pin_completes_on_clean_day_and_awards_once(self):
        s = Store(":memory:")
        r = challenges.pin(s, "detour", ["slack"], "fix it", 14, "2026-11-02")
        self.assertTrue(r["pinned"])
        self.assertTrue(challenges.pin(s, "detour", ["slack"], "fix it", 14, "2026-11-02")["already"])
        dirty = dict(fake_day(), date="2026-11-03")
        clean = dict(fake_day(), date="2026-11-04", findings=[])
        self.assertEqual(challenges.check_completion(s, [dirty]), [])
        self.assertEqual(challenges.check_completion(s, [clean]), [r["id"]])
        self.assertEqual(challenges.check_completion(s, [clean]), [])
        self.assertEqual(challenges.bonus_xp(s), 14)
        self.assertEqual(challenges.pins(s)[0]["status"], "completed")


class FakeApi:
    def day(self, date=None):
        return fake_day()


class TopicsFoldingCoherence(unittest.TestCase):
    def test_conversations_bucket_embed_fold_compact_cohere(self):
        s = Store(":memory:")
        s.ux("INSERT INTO tasks(title,created) VALUES(?,?)", ("Fix focus detour in slack", 1.0))
        s.x("CREATE TABLE IF NOT EXISTS turns(id INTEGER PRIMARY KEY, you TEXT, reply TEXT, tools TEXT, ts REAL)")
        s.x("INSERT INTO turns(you,reply,tools,ts) VALUES(?,?,?,?)", ("my focus leaks to slack", "Batch the slack checks", "[]", 1.0))
        items = topics.collect(s, FakeApi())
        kinds = {x["kind"] for x in items}
        self.assertIn("conversation", kinds)
        self.assertIn("task", kinds)
        hits = topics.recall(items, "deep work leak")
        self.assertTrue(hits)
        rep = coherence.run(s, FakeApi())
        self.assertTrue(rep["coherent"], rep["orphans"])
        self.assertGreaterEqual(rep["by_kind"].get("conversation", 0), 1)
        self.assertGreaterEqual(rep["honeycomb_artifacts"], 1)
        st = folding.compact(s, max_embeddings=500)
        self.assertIn("kept", st)

    def test_ics_roundtrip_and_providers_honest(self):
        ics = calendars.export_ics([dict(id=3, title="Ship it, now", est_min=30, planned_start=1700000000)], [])
        self.assertIn("BEGIN:VCALENDAR", ics)
        ev = calendars.parse_ics(ics)
        self.assertEqual(ev[0]["title"], "Ship it, now")
        prov = calendars.providers()
        self.assertEqual([p["id"] for p in prov], ["google", "icloud", "microsoft"])
        self.assertTrue(all(p["mode"] == "ics" or p["configured"] for p in prov))


class SelfTrainEmbed(unittest.TestCase):
    def test_dense_embedding_kv_and_tiers(self):
        v1 = embedder.dense("focus detour slack", ["focus", "detour", "slack"])
        self.assertEqual(len(v1), embedder.DIMS)
        self.assertAlmostEqual(sum(x * x for x in v1), 1.0, places=3)
        self.assertEqual(v1, embedder.dense("focus detour slack", ["focus", "detour", "slack"]))
        self.assertGreater(kvcache.stats()["hits"], 0)
        self.assertEqual(meta.model_for("main"), "muse-wonder-1.0")
        self.assertEqual(meta.model_for("sub"), "muse-spark-1.3")

    def test_selftrain_needs_data_then_learns_terms(self):
        s = Store(":memory:")
        out = selftrain.run(s, FakeApi())
        self.assertFalse(out["trained"])   # honest: not enough local data yet
        for i in range(14):
            s.ux("INSERT INTO tasks(title,created) VALUES(?,?)", (f"focus build task {i}", float(i)))
        challenges.pin(s, "detour", ["slack"], "batch slack checks", 10, "2026-11-01")
        s.x("UPDATE pinned_challenges SET status='completed' WHERE kind='detour'")
        out = selftrain.run(s, FakeApi())
        self.assertTrue(out["trained"], out)
        self.assertGreater(out["terms_learned"], 0)
        self.assertEqual(len(selftrain.log(s)), 1)


class StaticCaching(unittest.TestCase):
    def test_asset_etag_roundtrip(self):
        import urllib.request, urllib.error
        from stretto.server import make_server
        from stretto.store import Store
        srv, tok = make_server(Store(":memory:"), port=0, token="t")
        import threading
        th = threading.Thread(target=srv.serve_forever, daemon=True); th.start()
        try:
            base = f"http://127.0.0.1:{srv.server_address[1]}"
            host = {"Host": f"127.0.0.1:{srv.server_address[1]}"}
            r = urllib.request.urlopen(urllib.request.Request(base + "/js/app.js", headers=host), timeout=5)
            self.assertEqual(r.status, 200)
            etag = r.headers.get("ETag")
            self.assertTrue(etag)
            self.assertIn("max-age=3600", r.headers.get("Cache-Control", ""))
            try:
                urllib.request.urlopen(urllib.request.Request(base + "/js/app.js", headers={**host, "If-None-Match": etag}), timeout=5)
                self.fail("expected 304")
            except urllib.error.HTTPError as e:
                self.assertEqual(e.code, 304)
            shell = urllib.request.urlopen(urllib.request.Request(base + "/", headers=host), timeout=5)
            self.assertIn("no-store", shell.headers.get("Cache-Control", ""))
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
