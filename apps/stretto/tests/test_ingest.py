# SPDX-License-Identifier: Apache-2.0
"""Multi-device ingest, source priority, patterns, consent and remote mode."""
import datetime as dt, json, threading, unittest, urllib.error, urllib.request

from stretto import consent, merge, patterns, segment
from stretto.server import make_server
from stretto.store import Store

D0 = dt.datetime.combine(dt.date.today() - dt.timedelta(days=3), dt.time(9)).timestamp()


def samples(start, n, app="Code", step=5, **kw):
    return [dict(ts=start + i * step, dur=step, app=app, title="t", **kw) for i in range(n)]


class Idempotent(unittest.TestCase):
    def test_same_batch_twice_counts_once(self):
        s = Store(":memory:")
        self.assertEqual(s.ingest(samples(D0, 20), "collector", "pc1"), 20)
        self.assertEqual(s.ingest(samples(D0, 20), "collector", "pc1"), 0)   # a retry after a lost reply
        self.assertEqual(s.ingest(samples(D0, 20), "collector", "pc2"), 20)  # another device is its own history
        self.assertEqual(len(s.q("SELECT 1 FROM events")), 40)

    def test_old_history_is_accepted_but_not_the_future(self):
        s = Store(":memory:")
        self.assertEqual(s.ingest([dict(ts=1_420_000_000, app="chrome")]), 1)       # 2015
        self.assertEqual(s.ingest([dict(ts=4_000_000_000, app="chrome")]), 0)       # 2096

    def test_cursor_roundtrip_and_power(self):
        s = Store(":memory:")
        self.assertEqual(s.cursor("pc1", "chrome-history:Default"), "")
        s.set_cursor("pc1", "chrome-history:Default", "123", 10)
        self.assertEqual(s.cursor("pc1", "chrome-history:Default"), "123")
        self.assertEqual(s.ingest_power([dict(ts=D0, kind="boot"), dict(ts=D0, kind="boot"), dict(ts=D0, kind="nonsense")], "pc1"), 1)


class Priority(unittest.TestCase):
    def test_live_capture_masks_inferred_history_but_history_fills_gaps(self):
        s = Store(":memory:")
        s.ingest(samples(D0, 60), "collector", "pc1")                                 # 09:00-09:05 live
        hist = [dict(ts=D0 + 100, dur=60, app="chrome", title="docs", domain="docs.google.com"),   # inside live coverage: dropped
                dict(ts=D0 + 3600, dur=120, app="chrome", title="docs", domain="docs.google.com")]  # an hour later: kept
        s.ingest(hist, "chrome-history:Default", "pc1")
        kept, dropped = merge.resolve(s.events(D0 - 1, D0 + 86400))
        self.assertEqual(dropped, {"chrome-history:Default": 1})
        self.assertEqual(sum(1 for e in kept if e["src"].startswith("chrome-history")), 1)
        self.assertEqual(sum(1 for e in kept if e["src"] == "collector"), 60)

    def test_os_log_beats_history_loses_to_collector(self):
        from stretto.store import priority
        self.assertGreater(priority("collector"), priority("activities-cache"))
        self.assertGreater(priority("activities-cache"), priority("edge-history:Default"))


class Patterns(unittest.TestCase):
    def test_best_window_and_not_enough_days(self):
        days = {}
        for i in range(6):
            t = dt.datetime.combine(dt.date.today() - dt.timedelta(days=i + 1), dt.time(10)).timestamp()
            days[(dt.date.today() - dt.timedelta(days=i + 1)).isoformat()] = segment.blocks(samples(t, 360))   # 30 min of Code at 10:00
        p = patterns.profile(days)
        self.assertTrue(p["enough"])
        self.assertEqual(p["days"], 6)
        self.assertIn(10, [(p["best_window"]["start_hour"] + k) % 24 for k in range(3)])
        self.assertFalse(patterns.profile({"2026-01-01": segment.blocks(samples(D0, 10))})["enough"])


class Http(unittest.TestCase):
    remote = False

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

    def accept(self, device, family, by="Test Person"):
        return self.call("POST", "/api/consent", dict(device=device, family=family, action="grant", granted_by=by, typed=consent.phrase(family)))

    def test_no_consent_no_data_for_each_family(self):
        for src, fam in (("collector", "host-system"), ("chrome-history:Default", "browser-history"), ("activities-cache", "host-system")):
            code, r = self.call("POST", "/api/ingest", dict(device="pcA", src=src, samples=samples(D0, 3)))
            self.assertEqual((code, r["error"], r["family"]), (403, "consent_required", fam))
        self.assertEqual(self.store.q("SELECT COUNT(*) AS n FROM events WHERE device='pcA'")[0]["n"], 0)
        code, r = self.call("POST", "/api/ingest", dict(device="pcA", src="collector", samples=[], power=[dict(ts=D0, kind="boot")]))
        self.assertEqual(code, 403)                     # system power events are host-system data too

    def test_wrong_phrase_or_missing_name_is_refused(self):
        self.assertEqual(self.call("POST", "/api/consent", dict(device="pcB", family="host-system", action="grant", granted_by="A", typed="yes"))[0], 400)
        self.assertEqual(self.call("POST", "/api/consent", dict(device="pcB", family="host-system", action="grant", granted_by="", typed=consent.phrase("host-system")))[0], 400)
        self.assertFalse(self.call("GET", "/api/consent?device=pcB")[1]["families"]["host-system"]["active"])

    def test_grant_allows_only_that_family_then_revoke_blocks(self):
        self.assertEqual(self.accept("pcC", "browser-history")[0], 200)
        self.assertEqual(self.call("POST", "/api/ingest", dict(device="pcC", src="firefox-history:x", samples=samples(D0, 3)))[1]["stored"], 3)
        self.assertEqual(self.call("POST", "/api/ingest", dict(device="pcC", src="collector", samples=samples(D0, 3)))[0], 403)   # other family still closed
        self.call("POST", "/api/consent", dict(device="pcC", family="browser-history", action="revoke", granted_by="Test Person"))
        self.assertEqual(self.call("POST", "/api/ingest", dict(device="pcC", src="firefox-history:x", samples=samples(D0 + 99, 3)))[0], 403)

    def test_purge_needs_typed_confirmation_and_only_deletes_that_family(self):
        self.accept("pcD", "browser-history"); self.accept("pcD", "host-system")
        self.call("POST", "/api/ingest", dict(device="pcD", src="edge-history:Default", samples=samples(D0, 5)))
        self.call("POST", "/api/ingest", dict(device="pcD", src="collector", samples=samples(D0 + 5000, 4)))
        self.assertEqual(self.call("POST", "/api/purge", dict(device="pcD", family="browser-history", confirm="yes"))[0], 400)
        code, r = self.call("POST", "/api/purge", dict(device="pcD", family="browser-history", confirm="DELETE browser-history"))
        self.assertEqual((code, r["deleted"]), (200, 5))
        self.assertEqual(self.store.q("SELECT COUNT(*) AS n FROM events WHERE device='pcD'")[0]["n"], 4)

    def test_consent_log_is_tamper_evident(self):
        self.accept("pcE", "host-system")
        self.assertTrue(consent.verify_chain(self.store))
        self.store.x("UPDATE consent SET granted_by='Someone Else' WHERE device='pcE'")
        self.assertFalse(consent.verify_chain(self.store))

    def test_new_notice_version_asks_again(self):
        self.accept("pcF", "host-system")
        self.assertTrue(consent.active(self.store, "pcF", "host-system"))
        old = consent.VERSION
        try:
            consent.VERSION = old + 1
            self.assertFalse(consent.active(self.store, "pcF", "host-system"))
        finally:
            consent.VERSION = old

    def test_notice_says_what_is_read_stored_never_and_how_to_revoke(self):
        for fam in consent.NOTICES:
            code, n = self.call("GET", f"/api/consent/notice?family={fam}")
            self.assertEqual(code, 200)
            for k in ("reads", "stores", "never", "goes", "warn", "revoke", "phrase"):
                self.assertTrue(n[k], (fam, k))

    def test_simulated_source_needs_no_consent(self):
        self.assertEqual(self.call("POST", "/api/ingest", dict(device="pcG", src="simulated", samples=samples(D0, 2)))[1]["stored"], 2)

    def test_cursor_saved_with_batch(self):
        self.accept("pcH", "browser-history")
        self.call("POST", "/api/ingest", dict(device="pcH", src="chrome-history:Default", samples=samples(D0, 2), cursor="77"))
        self.assertEqual(self.call("GET", "/api/cursor?device=pcH&src=chrome-history:Default")[1]["cursor"], "77")

    def test_sources_and_patterns_endpoints(self):
        self.call("POST", "/api/ingest", dict(device="pcG", src="simulated", samples=samples(D0, 5)))
        code, r = self.call("GET", "/api/sources")
        self.assertEqual(code, 200)
        self.assertTrue([x for x in r["sources"] if x["src"] == "simulated"])
        self.assertEqual(self.call("GET", "/api/patterns?days=30")[0], 200)


class RemoteMode(unittest.TestCase):
    def test_refuses_to_listen_beyond_loopback_without_allowed_host(self):
        with self.assertRaises(ValueError):
            make_server(Store(":memory:"), 0, host="0.0.0.0")

    def test_remote_page_never_carries_the_token_and_reads_need_it(self):
        srv, tok = make_server(Store(":memory:"), 0, host="127.0.0.1", allow_hosts=())
        srv.RequestHandlerClass.remote = True          # same switch make_server flips for a non-loopback bind
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            def get(path, token=None):
                r = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
                if token:
                    r.add_header("X-Stretto-Token", token)
                try:
                    with urllib.request.urlopen(r) as x:
                        return x.status, x.read()
                except urllib.error.HTTPError as e:
                    return e.code, e.read()
            code, page = get("/")
            self.assertEqual(code, 200)
            self.assertNotIn(tok.encode(), page)
            self.assertEqual(get("/api/day")[0], 403)
            self.assertEqual(get("/api/day", tok)[0], 200)
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
