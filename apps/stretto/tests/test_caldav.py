# SPDX-License-Identifier: Apache-2.0
"""Read-only iCloud CalDAV sync: discovery, REPORT parsing, shared dedupe, env gating, endpoint shape. No network:
the single seam calendars.caldav_request is replaced by a fixture-serving stub."""
import json
import os
import pathlib
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from stretto import calendars
from stretto.store import Store

FIX = pathlib.Path(__file__).parent / "fixtures" / "caldav"
HOME = "https://p42-caldav.icloud.com/123456/calendars/"
SECRET = "s3cret-app-pw-xyz"
ENV = dict(ICLOUD_CALDAV_USER="someone@example.com", ICLOUD_CALDAV_PASSWORD=SECRET, ICLOUD_CALDAV_URL=HOME)
NO_ENV = {k: "" for k in calendars.CALDAV_ENV}


class StubDAV:
    """Serves fixture multistatus bodies and records every call; refuses any method that would write."""
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, user, password, body, depth):
        self.calls.append((method, url, depth))
        assert method in ("PROPFIND", "REPORT"), method
        return (FIX / ("propfind.xml" if method == "PROPFIND" else "report.xml")).read_bytes()


class CalDAVUnit(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")

    def test_discovers_only_calendar_collections(self):
        urls = calendars.calendar_urls(HOME, (FIX / "propfind.xml").read_bytes())
        self.assertEqual(urls, ["https://p42-caldav.icloud.com/123456/calendars/work/"])

    def test_report_yields_ics_and_parse_unfolds_lines(self):
        texts = calendars.calendar_data((FIX / "report.xml").read_bytes())
        self.assertEqual(len(texts), 1)
        evs = calendars.parse_ics(texts[0])
        self.assertEqual([e["uid"] for e in evs], ["abc-1@icloud.com", "stretto-task-7@stretto.local", "abc-2@icloud.com"])
        self.assertEqual(evs[0]["title"], "Design review with the platform team about the calendar sync rollout")
        self.assertEqual(evs[2]["title"], "Offsite, day one")

    def test_sync_imports_via_dedupe_and_is_idempotent(self):
        stub = StubDAV()
        with mock.patch.dict(os.environ, ENV), mock.patch.object(calendars, "caldav_request", stub):
            first = calendars.caldav_sync(self.s)
            second = calendars.caldav_sync(self.s)
        self.assertEqual(first, dict(created=2, skipped=1, seen=3))
        self.assertEqual(second, dict(created=0, skipped=3, seen=3))
        self.assertEqual(stub.calls[:2], [("PROPFIND", HOME, 1), ("REPORT", HOME + "work/", 1)])
        titles = sorted(r["title"] for r in self.s.q("SELECT title FROM tasks WHERE planned_start IS NOT NULL"))
        self.assertEqual(titles, ["Design review with the platform team about the calendar sync rollout", "Offsite, day one"])

    def test_not_configured_without_any_env_and_no_network(self):
        for missing in calendars.CALDAV_ENV:
            env = dict(ENV, **{missing: ""})
            with mock.patch.dict(os.environ, env), mock.patch.object(calendars, "caldav_request", side_effect=AssertionError("network")):
                with self.assertRaises(calendars.CalDAVError) as cm:
                    calendars.caldav_sync(self.s)
                self.assertEqual(cm.exception.reason, "not_configured")
                self.assertEqual(calendars.caldav_missing(), [missing])

    def test_request_refuses_plain_http_and_never_echoes_secret(self):
        with self.assertRaises(calendars.CalDAVError) as cm:
            calendars.caldav_request("PROPFIND", "http://example.invalid/", "u", SECRET, "<x/>", 1)
        self.assertEqual(cm.exception.reason, "https_required")
        err = urllib.error.HTTPError(HOME, 401, "Unauthorized", {}, None)
        with mock.patch.object(urllib.request, "urlopen", side_effect=err) as op:
            with self.assertRaises(calendars.CalDAVError) as cm:
                calendars.caldav_request("PROPFIND", HOME, "u", SECRET, "<x/>", 1)
        req = op.call_args[0][0]
        self.assertTrue(req.get_header("Authorization", "").startswith("Basic "))
        self.assertNotIn("Authorization", req.headers)            # unredirected: never forwarded to a redirect target
        self.assertEqual((cm.exception.reason, cm.exception.status), ("unauthorized", 401))
        self.assertNotIn(SECRET, repr(cm.exception) + str(cm.exception))

    def test_bad_xml_is_structured(self):
        with self.assertRaises(calendars.CalDAVError) as cm:
            calendars.calendar_urls(HOME, b"<not xml")
        self.assertEqual(cm.exception.reason, "bad_xml")

    def test_provider_card_needs_all_three(self):
        with mock.patch.dict(os.environ, dict(ENV, ICLOUD_CALDAV_PASSWORD="")):
            self.assertFalse(next(p for p in calendars.providers() if p["id"] == "icloud")["configured"])
        with mock.patch.dict(os.environ, ENV):
            card = next(p for p in calendars.providers() if p["id"] == "icloud")
        self.assertEqual((card["configured"], card["mode"]), (True, "caldav-ready"))
        self.assertNotIn(SECRET, json.dumps(card))


class CalDAVEndpoint(unittest.TestCase):
    def setUp(self):
        from stretto.server import make_server
        self.s = Store(":memory:")
        self.srv, self.tok = make_server(self.s, port=0, token="t")
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()

    def post(self, path, obj=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(obj or {}).encode(), method="POST")
        req.add_header("Host", f"127.0.0.1:{self.port}"); req.add_header("X-Stretto-Token", self.tok)
        req.add_header("Content-Type", "application/json")
        try:
            r = urllib.request.urlopen(req, timeout=5)
            return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_503_not_configured(self):
        with mock.patch.dict(os.environ, NO_ENV):
            code, body = self.post("/api/calendar/caldav/sync")
        self.assertEqual(code, 503)
        self.assertEqual(body["reason"], "not_configured")
        self.assertEqual(body["missing"], list(calendars.CALDAV_ENV))

    def test_sync_returns_counts(self):
        with mock.patch.dict(os.environ, ENV), mock.patch.object(calendars, "caldav_request", StubDAV()):
            code, body = self.post("/api/calendar/caldav/sync")
        self.assertEqual((code, body), (200, dict(created=2, skipped=1, seen=3)))

    def test_upstream_failure_is_502_without_secret(self):
        def boom(*a):
            raise calendars.CalDAVError("unauthorized", 401)
        with mock.patch.dict(os.environ, ENV), mock.patch.object(calendars, "caldav_request", boom):
            code, body = self.post("/api/calendar/caldav/sync")
        self.assertEqual((code, body["reason"], body["upstream_status"]), (502, "unauthorized", 401))
        self.assertNotIn(SECRET, json.dumps(body)); self.assertNotIn(ENV["ICLOUD_CALDAV_USER"], json.dumps(body))

    def test_ics_import_still_shares_dedupe(self):
        ics = (FIX / "report.xml").read_text()
        ics = ics[ics.index("BEGIN:VCALENDAR"):ics.index("]]>")]
        self.assertEqual(self.post("/api/calendar/import", dict(ics=ics)), (200, dict(created=2, skipped=1, seen=3)))
        with mock.patch.dict(os.environ, ENV), mock.patch.object(calendars, "caldav_request", StubDAV()):
            self.assertEqual(self.post("/api/calendar/caldav/sync"), (200, dict(created=0, skipped=3, seen=3)))


if __name__ == "__main__":
    unittest.main()
