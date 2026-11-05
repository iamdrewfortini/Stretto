import datetime as dt, json, threading, unittest, urllib.error, urllib.request
from stretto import analyze, demo, gamify, segment
from stretto.server import make_server
from stretto.store import Store

DAY0 = dt.datetime.combine(dt.date.today() - dt.timedelta(days=1), dt.time()).timestamp()


class Segment(unittest.TestCase):
    def test_idle_and_merge(self):
        ev = [dict(ts=1_700_000_000 + i * 5, dur=5, app="Code", title="a", idle=0) for i in range(12)] + \
             [dict(ts=1_700_000_060 + i * 5, dur=5, app="idle", title="", idle=1) for i in range(6)]
        b = segment.blocks(ev)
        self.assertEqual([x["category"] for x in b], ["Build", "Idle"])
        self.assertEqual(b[0]["seconds"], 60)

    def test_browser_site_from_title(self):
        c, key = segment.classify(dict(app="chrome.exe", title="Funny cats - YouTube", idle=0))
        self.assertEqual((c, key), ("Distraction", ("chrome", "youtube.com")))

    def test_user_rule_wins(self):
        c, _ = segment.classify(dict(app="chrome", title="Funny cats - YouTube", idle=0), [("domain", "youtube", "Learn")])
        self.assertEqual(c, "Learn")


class Analyze(unittest.TestCase):
    def setUp(self):
        self.b = segment.blocks(demo.samples(DAY0))
        self.f, self.loss = analyze.findings(self.b)

    def test_finds_each_kind_with_evidence(self):
        kinds = {f["kind"] for f in self.f}
        self.assertTrue({"ping_pong", "detour", "repeated_path"} <= kinds, kinds)
        for f in self.f:
            self.assertEqual(f["basis"], "measured")
            self.assertTrue(f["blocks"] and f["suggestion"])

    def test_loss_never_exceeds_active_time_and_counts_blocks_once(self):
        s = analyze.summary(self.b)
        self.assertGreater(self.loss, 0)
        self.assertLessEqual(self.loss, s["total_s"])

    def test_repeated_path_is_the_github_slack_code_loop(self):
        p = [f for f in self.f if f["kind"] == "repeated_path"][0]
        self.assertEqual(p["runs"], 3)
        self.assertIn("github.com", p["where"])

    def test_summary_separates_idle(self):
        s = analyze.summary(self.b)
        self.assertEqual(s["idle_s"], 900)
        self.assertGreater(s["focus_s"], s["distraction_s"])


class Gamify(unittest.TestCase):
    def test_xp_level(self):
        self.assertEqual(gamify.xp_for_day(3600, 7200), 60)
        self.assertEqual(gamify.xp_for_day(7200, 7200), 145)
        self.assertEqual(gamify.level(0)["level"], 1)
        self.assertEqual(gamify.level(50)["level"], 2)

    def test_streak_with_one_rest_day(self):
        today = dt.date.today()
        days = {(today - dt.timedelta(days=i)).isoformat(): 9000 for i in range(1, 8) if i != 3}
        self.assertEqual(gamify.streak(days, today.isoformat(), 7200), 6)
        days[(today - dt.timedelta(days=5)).isoformat()] = 0
        self.assertEqual(gamify.streak(days, today.isoformat(), 7200), 3)  # day 3 is the rest day, day 5 is the second miss


class Store_(unittest.TestCase):
    def test_ingest_rejects_bad_rows(self):
        s = Store(":memory:")
        n = s.ingest([dict(ts=1_700_000_000, app="Code"), dict(ts=5, app="x"), dict(ts=1_700_000_000, app=""), dict(app="x"),
                      dict(ts=1_700_000_000, app="Code", dur=99999), dict(ts=1_700_000_005, app="Code", title="t" * 999)])
        self.assertEqual(n, 2)
        self.assertEqual(len(s.q("SELECT title FROM events WHERE length(title)=300")), 1)


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = Store(":memory:")
        cls.srv, cls.tok = make_server(cls.store, 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def call(self, method, path, body=None, token=True, host=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, data=json.dumps(body).encode() if body is not None else None)
        req.add_header("Host", host or f"127.0.0.1:{self.port}")
        if token:
            req.add_header("X-Stretto-Token", self.tok)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_write_needs_token_and_host_is_checked(self):
        self.assertEqual(self.call("POST", "/api/tasks", dict(title="x"), token=False)[0], 403)
        self.assertEqual(self.call("GET", "/api/day", host="evil.example:80")[0], 403)

    def test_demo_day_end_to_end(self):
        code, seeded = self.call("POST", "/api/demo/seed", {})
        self.assertEqual((code, seeded["stored"] > 0), (200, True))
        code, d = self.call("GET", "/api/day?date=" + seeded["date"])
        self.assertEqual(code, 200)
        self.assertTrue(d["simulated"])
        self.assertGreater(d["loss_s"], 0)
        self.assertTrue(d["findings"])
        self.assertGreaterEqual(d["xp"]["xp"], 1)

    def test_tasks_timer_habits(self):
        _, t = self.call("POST", "/api/tasks", dict(title="Write plan", est_min=30))
        self.assertEqual(self.call("POST", f"/api/tasks/{t['id']}", dict(status="doing"))[0], 200)
        self.assertEqual(self.call("POST", f"/api/tasks/{t['id']}", dict(status="nope"))[0], 400)
        self.call("POST", "/api/timer/start", dict(task_id=t["id"]))
        self.assertEqual(self.call("GET", "/api/timer")[1]["task_id"], t["id"])
        self.call("POST", "/api/timer/stop", {})
        self.assertIsNone(self.call("GET", "/api/timer")[1])
        _, h = self.call("POST", "/api/habits", dict(name="Walk"))
        self.call("POST", f"/api/habits/{h['id']}/log", {})
        self.assertTrue([x for x in self.call("GET", "/api/habits")[1] if x["id"] == h["id"]][0]["done_today"])

    def test_static_cannot_escape(self):
        self.assertEqual(self.call("GET", "/../store.py")[0], 404)


if __name__ == "__main__":
    unittest.main()