"""Agent: history importers on fabricated databases, privacy filtering, consent flow against a real server. No real user data."""
import os, sqlite3, sys, tempfile, threading, unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))
from stretto import consent as server_consent
from stretto.server import make_server
from stretto.store import Store
from stretto_agent import adapters, cfg as C, cli, importers
from stretto_agent.client import Client, ConsentRequired, Spool

T0 = 1_760_000_000          # an arbitrary fixed instant
CH = lambda unix: int((unix + importers.CHROME_EPOCH) * 1e6)


def chrome_db(path, visits):
    """visits: [(url, title, unix_time, duration_s_or_0)] in visit-id order."""
    con = sqlite3.connect(path)
    con.executescript("CREATE TABLE urls(id INTEGER PRIMARY KEY, url TEXT, title TEXT); CREATE TABLE visits(id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER, visit_duration INTEGER);")
    for i, (url, title, t, d) in enumerate(visits, 1):
        con.execute("INSERT INTO urls VALUES(?,?,?)", (i, url, title))
        con.execute("INSERT INTO visits VALUES(?,?,?,?)", (i, i, CH(t), int(d * 1e6)))
    con.commit(); con.close()


def firefox_db(path, visits):
    con = sqlite3.connect(path)
    con.executescript("CREATE TABLE moz_places(id INTEGER PRIMARY KEY, url TEXT, title TEXT); CREATE TABLE moz_historyvisits(id INTEGER PRIMARY KEY, place_id INTEGER, visit_date INTEGER);")
    for i, (url, title, t) in enumerate(visits, 1):
        con.execute("INSERT INTO moz_places VALUES(?,?,?)", (i, url, title))
        con.execute("INSERT INTO moz_historyvisits VALUES(?,?,?)", (i, i, int(t * 1e6)))
    con.commit(); con.close()


class Chromium(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "History")
        chrome_db(self.db, [
            ("https://www.Example.com/a/secret/path?token=abc123&q=private", "Example page", T0, 45),    # recorded stay
            ("https://docs.google.com/document/d/XYZ/edit", "My doc", T0 + 60, 0),                        # no stay: gap to next (40 s)
            ("chrome://settings/", "Settings", T0 + 90, 5),                                               # not a site
            ("file:///C:/Users/me/private.pdf", "private.pdf", T0 + 95, 5),                               # not a site
            ("https://news.site/x", "News", T0 + 100, 0),                                                 # last, no stay: 30 s
        ])
        self.imp = importers.ChromiumHistory("chrome-history:Default", self.db)

    def test_times_domains_and_stays(self):
        out, cur, power = self.imp.read("")
        self.assertEqual(power, [])
        self.assertEqual([s["domain"] for s in out], ["example.com", "docs.google.com", "news.site"])
        self.assertAlmostEqual(out[0]["ts"], T0, delta=0.01)                 # the 1601 epoch is converted correctly
        # recorded stay; gap to the next navigation of ANY kind (docs.google.com ends when chrome://settings opens, 30 s later); last-visit default
        self.assertEqual([round(s["dur"]) for s in out], [45, 30, 30])
        self.assertEqual(cur, "5")

    def test_privacy_no_path_query_or_scheme_leaks(self):
        out, _, _ = self.imp.read("")
        blob = repr(out).lower()
        for leak in ("secret", "token", "abc123", "xyz", "c:/users", "chrome://", "file:", "q=private", "/edit", "/a/"):
            self.assertNotIn(leak, blob, leak)

    def test_incremental_and_cleared_history(self):
        _, cur, _ = self.imp.read("")
        self.assertEqual(self.imp.read(cur)[0], [])                          # nothing new
        chrome_db_more = sqlite3.connect(self.db)
        chrome_db_more.execute("INSERT INTO urls VALUES(6,'https://new.site/',?)", ("New",))
        chrome_db_more.execute("INSERT INTO visits VALUES(6,6,?,?)", (CH(T0 + 500), 0))
        chrome_db_more.commit(); chrome_db_more.close()
        out, cur2, _ = self.imp.read(cur)
        self.assertEqual([s["domain"] for s in out], ["new.site"])
        self.assertEqual(cur2, "6")
        os.remove(self.db)
        chrome_db(self.db, [("https://a.site/", "A", T0 + 900, 3)])           # the browser's history was cleared and rebuilt
        out, cur3, _ = self.imp.read("6")
        self.assertEqual([s["domain"] for s in out], ["a.site"])             # cursor reset, not silently stuck

    def test_source_database_is_not_modified(self):
        before = os.path.getmtime(self.db), os.path.getsize(self.db)
        self.imp.read("")
        self.assertEqual((os.path.getmtime(self.db), os.path.getsize(self.db)), before)
        self.assertEqual([f for f in os.listdir(tempfile.gettempdir()) if f.startswith("stretto-")], [])   # temp copy removed

    def test_probe_never_opens_the_database(self):
        with mock.patch("sqlite3.connect", side_effect=AssertionError("opened")):
            p = self.imp.probe()
        self.assertEqual(p["family"], "browser-history")
        self.assertGreater(p["bytes"], 0)


class Firefox(unittest.TestCase):
    def test_places(self):
        d = tempfile.mkdtemp(); db = os.path.join(d, "places.sqlite")
        firefox_db(db, [("https://wikipedia.org/wiki/Foo?x=1", "Foo", T0), ("https://github.com/a/b", "repo", T0 + 30)])
        out, cur, _ = importers.FirefoxHistory("firefox-history:p", db).read("")
        self.assertEqual([s["domain"] for s in out], ["wikipedia.org", "github.com"])
        self.assertEqual([round(s["dur"]) for s in out], [30, 30])
        self.assertEqual(cur, "2")


class Privacy(unittest.TestCase):
    REDACT = ["1password", "keepass"]

    def test_private_windows_are_dropped_and_password_managers_blanked(self):
        self.assertIsNone(adapters.filter_sample("chrome.exe", "Bank - Incognito", self.REDACT))
        self.assertIsNone(adapters.filter_sample("msedge.exe", "x - InPrivate", self.REDACT))
        self.assertEqual(adapters.filter_sample("1Password.exe", "Vault: bank login", self.REDACT), ("1Password.exe", ""))
        self.assertEqual(adapters.filter_sample("Code.exe", "stretto", self.REDACT), ("Code.exe", "stretto"))

    def test_idle_sample_carries_no_app_or_title(self):
        cfg = dict(C.DEFAULTS)
        cap = lambda: dict(app="Code.exe", title="secret plans", domain="", idle_ms=999_999, cx=1, cy=2)
        s = adapters.sample(cap, cfg, T0)
        self.assertEqual((s["app"], s["title"], s["idle"]), ("idle", "", 1))

    def test_exe_suffix_removed_and_title_kept(self):
        cfg = dict(C.DEFAULTS)
        s = adapters.sample(lambda: dict(app="Code.exe", title="t", domain="", idle_ms=0, cx=1, cy=2), cfg, T0)
        self.assertEqual((s["app"], s["title"], s["idle"]), ("Code", "t", 0))


class WithServer(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.srv, self.tok = make_server(self.store, 0)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.cl = Client(f"http://127.0.0.1:{self.port}", self.tok)
        self.base = tempfile.mkdtemp()
        self.cfg = dict(C.DEFAULTS, device="dev1", device_name="test-pc", enabled_sources=["chrome-history:Default"])
        d = tempfile.mkdtemp(); self.db = os.path.join(d, "History")
        chrome_db(self.db, [("https://a.site/p?q=1", "A", T0, 10), ("https://b.site/", "B", T0 + 20, 10), ("https://c.site/", "C", T0 + 40, 10)])
        self.imp = importers.ChromiumHistory("chrome-history:Default", self.db)

    def tearDown(self):
        self.srv.shutdown()

    def grant(self, fam="browser-history"):
        return self.cl.post("/api/consent", dict(device="dev1", family=fam, action="grant", granted_by="Test Person", typed=server_consent.phrase(fam)))

    def run_import(self):
        logs = []
        with mock.patch.object(importers, "discover", return_value=[self.imp]):
            n = cli.import_once(self.cfg, self.cl, log=logs.append)
        return n, logs

    def test_full_flow_no_consent_then_accept_then_incremental_then_revoke(self):
        n, logs = self.run_import()
        self.assertEqual(n, 0)
        self.assertIn("notice has not been accepted", " ".join(logs))
        self.assertEqual(self.store.q("SELECT COUNT(*) AS n FROM events")[0]["n"], 0)       # nothing was read into the server
        self.grant()
        n, _ = self.run_import()
        self.assertEqual(n, 3)
        self.assertEqual(self.run_import()[0], 0)                                           # incremental: nothing new
        self.assertEqual(self.cl.get("/api/cursor?device=dev1&src=chrome-history:Default")["cursor"], "3")
        self.cl.post("/api/consent", dict(device="dev1", family="browser-history", action="revoke", granted_by="Test Person"))
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO urls VALUES(4,'https://d.site/','D')")
        con.execute("INSERT INTO visits VALUES(4,4,?,0)", (CH(T0 + 99),))
        con.commit(); con.close()
        n, logs = self.run_import()
        self.assertEqual(n, 0)                                                              # a new visit exists, but consent was revoked
        self.assertIn("notice has not been accepted", " ".join(logs))
        self.assertEqual(self.store.q("SELECT COUNT(*) AS n FROM events WHERE domain='d.site'")[0]["n"], 0)

    def test_server_refuses_even_if_agent_config_is_edited(self):
        with self.assertRaises(ConsentRequired):
            self.cl.post("/api/ingest", dict(device="dev1", src="chrome-history:Default", samples=[dict(ts=T0, app="chrome", title="x")]))

    def test_spool_keeps_batches_until_the_server_accepts_them(self):
        sp = Spool(self.base)
        sp.add(dict(device="dev1", src="collector", samples=[dict(ts=T0, app="Code", title="t")]))
        with self.assertRaises(ConsentRequired):
            sp.flush(self.cl)
        self.assertEqual(len(sp.pending()), 1)                                              # kept: nothing lost while consent is missing
        self.grant("host-system")
        self.assertEqual(sp.flush(self.cl), (1, 0))
        self.assertEqual(self.store.q("SELECT COUNT(*) AS n FROM events WHERE device='dev1'")[0]["n"], 1)

    def test_spool_survives_an_unreachable_server(self):
        sp = Spool(self.base)
        sp.add(dict(device="dev1", src="collector", samples=[dict(ts=T0, app="Code")]))
        dead = Client("http://127.0.0.1:9", self.tok, timeout=1)
        self.assertEqual(sp.flush(dead), (0, 1))

    def test_accepting_requires_a_person_at_a_terminal(self):
        with mock.patch("sys.stdin.isatty", return_value=False):
            with self.assertRaises(SystemExit):
                cli._need_person()


if __name__ == "__main__":
    unittest.main()
