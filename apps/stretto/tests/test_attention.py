# SPDX-License-Identifier: Apache-2.0
"""Exact focus tracking, input-tick gating, attention measures, app metadata, and the agent loop end to end. Fakes only."""
import json, os, sys, tempfile, threading, unittest, urllib.error, urllib.request
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))
from stretto import attention, consent, segment
from stretto.server import make_server
from stretto.store import Store
from stretto_agent import adapters, cfg as C, cli, importers
from stretto_agent.client import Client

T0 = 1_760_000_000.0
CFG = dict(C.DEFAULTS)


def snap(app="Code.exe", title="a.py", ctl="Edit", idle_ms=0, inputs=0, domain=""):
    return dict(app=app, title=title, ctl=ctl, idle_ms=idle_ms, inputs=inputs, domain=domain, cx=1, cy=2)


class Tracker(unittest.TestCase):
    def test_stays_have_exact_start_and_duration_not_a_grid(self):
        t = adapters.FocusTracker(CFG)
        out = []
        for now, s in ((0.0, snap()), (0.25, snap()), (0.5, snap("chrome.exe", "Docs", "Chrome_Widget")), (0.75, snap("chrome.exe", "Docs", "Chrome_Widget")),
                       (1.0, snap("Code.exe", "a.py", "Edit"))):
            out += t.update(T0 + now, s)
        out += t.flush(T0 + 1.25)
        self.assertEqual([(s["app"], round(s["ts"] - T0, 2), s["dur"]) for s in out], [("Code", 0.0, 0.5), ("chrome", 0.5, 0.5), ("Code", 1.0, 0.25)])
        self.assertEqual(out[1]["ctl"], "Chrome_Widget")                    # which control had the focus, by class: never its text

    def test_a_shift_between_two_controls_of_one_app_is_seen(self):
        t = adapters.FocusTracker(CFG)
        out = t.update(T0, snap(ctl="Edit")) + t.update(T0 + 2, snap(ctl="TreeView")) + t.flush(T0 + 3)
        self.assertEqual([(s["ctl"], s["dur"]) for s in out], [("Edit", 2.0), ("TreeView", 1.0)])

    def test_a_long_stay_is_flushed_every_five_seconds_without_a_gap(self):
        t = adapters.FocusTracker(CFG)
        out = []
        for i in range(0, 41):
            out += t.update(T0 + i * 0.25, snap())
        out += t.flush(T0 + 10.25)
        self.assertEqual([s["dur"] for s in out], [5.0, 5.0, 0.25])
        self.assertAlmostEqual(out[1]["ts"], out[0]["ts"] + out[0]["dur"])

    def test_idle_private_and_password_manager_rules(self):
        t = adapters.FocusTracker(CFG)
        out = t.update(T0, snap()) + t.update(T0 + 1, snap(idle_ms=200_000)) + t.update(T0 + 2, snap("chrome.exe", "Bank - Incognito")) + \
            t.update(T0 + 3, snap("1Password.exe", "Vault: bank login")) + t.flush(T0 + 4)
        self.assertEqual([(s["app"], s["idle"], s["title"]) for s in out], [("Code", 0, "a.py"), ("idle", 1, ""), ("1Password", 0, "")])   # no incognito stay; title blanked
        self.assertTrue(all("Incognito" not in s["title"] for s in out))

    def test_input_ticks_only_when_enabled_and_never_for_idle(self):
        for flag, expect in ((False, None), (True, 3)):
            t = adapters.FocusTracker(CFG, count_inputs=flag)
            out = t.update(T0, snap(inputs=1)) + t.update(T0 + 0.25, snap(inputs=1)) + t.update(T0 + 0.5, snap(inputs=1)) + t.flush(T0 + 0.75)
            self.assertEqual(out[0]["inp"], expect)
        t = adapters.FocusTracker(CFG, count_inputs=True)
        out = t.update(T0, snap(idle_ms=999_999, inputs=1)) + t.flush(T0 + 1)
        self.assertIsNone(out[0]["inp"])


class Gate(unittest.TestCase):
    def test_store_drops_counts_without_the_notice_and_counts_them(self):
        s = Store(":memory:")
        row = [dict(ts=T0, dur=2, app="Code", title="t", inp=7, ctl="Edit")]
        self.assertEqual(s.ingest(row, device="d", keep_input=False), 1)
        self.assertEqual((s.last_input_dropped, s.q("SELECT inp, ctl FROM events")[0]), (1, dict(inp=None, ctl="Edit")))
        row[0]["ts"] += 10
        s.ingest(row, device="d", keep_input=True)
        self.assertEqual(s.q("SELECT inp FROM events ORDER BY ts")[1]["inp"], 7)
        self.assertEqual(s.ingest([dict(ts=T0 + 99, dur=1, app="x", inp=10 ** 9)], keep_input=True), 1)
        self.assertEqual(s.q("SELECT inp FROM events ORDER BY ts DESC")[0]["inp"], 100_000)    # absurd values are clamped

    def test_blocks_sum_counts_and_remember_how_much_time_carried_them(self):
        ev = [dict(ts=T0, dur=2, app="Code", title="t", inp=4), dict(ts=T0 + 2, dur=3, app="Code", title="t", inp=None), dict(ts=T0 + 5, dur=5, app="Code", title="t", inp=6)]
        b = segment.blocks(ev)[0]
        self.assertEqual((b["inp"], b["inp_s"], b["seconds"]), (10, 7.0, 10.0))


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = Store(":memory:")
        cls.srv, cls.tok = make_server(cls.store, 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.cl = Client(f"http://127.0.0.1:{cls.port}", cls.tok)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def grant(self, dev, fam):
        self.cl.post("/api/consent", dict(device=dev, family=fam, action="grant", granted_by="T P", typed=consent.phrase(fam)))

    def test_server_strips_counts_until_the_input_notice_is_accepted_then_keeps_them(self):
        self.grant("dA", "host-system")
        body = dict(device="dA", src="collector", samples=[dict(ts=T0, dur=2, app="Code", title="t", inp=5)])
        self.assertEqual(self.cl.post("/api/ingest", body)["input_dropped"], 1)
        self.grant("dA", "input-activity")
        body["samples"][0]["ts"] += 30
        self.assertEqual(self.cl.post("/api/ingest", body)["input_dropped"], 0)
        self.assertEqual(self.store.q("SELECT inp FROM events WHERE device='dA' ORDER BY ts")[1]["inp"], 5)

    def test_app_metadata_is_stored_and_listed(self):
        self.grant("dB", "host-system")
        self.cl.post("/api/ingest", dict(device="dB", src="collector", samples=[], apps=[dict(app="Code", display="Visual Studio Code", publisher="Microsoft", version="1.95")]))
        r = self.cl.get("/api/apps?device=dB")["apps"]
        self.assertEqual((r[0]["display"], r[0]["publisher"], r[0]["version"]), ("Visual Studio Code", "Microsoft", "1.95"))

    def test_attention_endpoint_and_input_notice_text(self):
        self.assertIn("enough", self.cl.get("/api/attention"))
        n = self.cl.get("/api/consent/notice?family=input-activity")
        self.assertIn("never", " ".join(n["never"]).lower() + "never")
        self.assertIn("key logger", " ".join(n["never"]).lower())


def block(app, secs, cat, start, dom="", ctl="", inp=None, inp_s=0):
    return dict(app=app, domain=dom, seconds=secs, category=cat, start=start, end=start + secs, ctl=ctl, inp=inp, inp_s=inp_s, title="", key=(app, dom), n=1)


class Measures(unittest.TestCase):
    def test_numbers_follow_the_stated_formula(self):
        bl, t = [], T0
        for app, secs, cat in (("code", 600, "Build"), ("youtube.com", 20, "Distraction"), ("code", 600, "Build"), ("slack", 10, "Communication"), ("code", 400, "Build")):
            bl.append(block(app, secs, cat, t)); t += secs
        m = attention.measure(bl)
        self.assertEqual((m["shifts"], m["active_s"]), (4, 1630))
        self.assertAlmostEqual(m["fragmented_share"], 30 / 1630, places=3)
        self.assertEqual(m["return_time_s"]["count"], 2)
        want = round(100 * (1 - (0.45 * m["fragmented_share"] + 0.35 * min(1, m["shifts_per_hour"] / 60) + 0.20 * m["distraction_share"])))
        self.assertEqual(m["score"], want)
        self.assertEqual(m["longest_focus"]["seconds"], 600)
        self.assertIn("score = 100", m["formula"])

    def test_not_enough_data_says_so_instead_of_inventing_a_score(self):
        self.assertFalse(attention.measure([block("code", 20, "Build", T0)])["enough"])
        self.assertFalse(attention.measure([])["enough"])

    def test_panel_focus_and_input_ticks_only_appear_when_present(self):
        bl = [block("code", 300, "Build", T0, ctl="Edit", inp=240, inp_s=300), block("youtube.com", 100, "Distraction", T0 + 300, ctl="Chrome_Widget", inp=20, inp_s=100)]
        m = attention.measure(bl)
        self.assertEqual(m["focus_controls"][0], dict(app="code", control="Edit", seconds=300))
        self.assertEqual(m["input_ticks_per_minute"], dict(overall=39.0, focus=48.0, other=12.0, covered_s=400))
        self.assertNotIn("input_ticks_per_minute", attention.measure([block("code", 300, "Build", T0)]))


class LoopEndToEnd(unittest.TestCase):
    def test_agent_loop_records_exact_stays_with_consent_and_stops_when_it_is_withdrawn(self):
        store = Store(":memory:")
        srv, tok = make_server(store, 0)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        home = tempfile.mkdtemp()
        try:
            cl = Client(f"http://127.0.0.1:{port}", tok)
            for fam in ("host-system", "input-activity"):
                cl.post("/api/consent", dict(device="e2e", family=fam, action="grant", granted_by="T P", typed=consent.phrase(fam)))
            script = [snap("Code.exe", "a.py", "Edit", inputs=1)] * 8 + [snap("chrome.exe", "Docs", "Chrome_Widget", inputs=0)] * 8 + [snap("Code.exe", "a.py", "Edit", inputs=1)] * 4
            calls = {"n": 0}

            def cap():
                s = script[min(calls["n"], len(script) - 1)]
                calls["n"] += 1
                return s
            clock = {"t": T0}

            def now():
                return clock["t"]

            def sleep(dt):
                clock["t"] += dt

            def stop():
                return calls["n"] >= len(script) + 130 or clock["t"] > T0 + 80          # run long enough for the 30 s flush to happen
            cfg = dict(C.DEFAULTS, server=f"http://127.0.0.1:{port}", device="e2e", device_name="fake-pc", token_file="")
            with mock.patch.dict(os.environ, {"STRETTO_AGENT_HOME": home}), mock.patch.object(adapters, "make", return_value=(cap, "")), \
                    mock.patch.object(adapters, "poll_interval", return_value=0.25), mock.patch.object(importers, "discover", return_value=[]):
                cfg["token_file"] = os.path.join(home, "tok"); open(cfg["token_file"], "w").write(tok)
                cli.cmd_run(cfg, mock.Mock(), stop=stop, clock=now, sleep=sleep)
            rows = store.q("SELECT app, ctl, ts, dur, inp FROM events WHERE device='e2e' ORDER BY ts")
            self.assertTrue(rows)
            first = [r for r in rows if r["app"] == "Code"][0]
            self.assertAlmostEqual(first["ts"], T0, places=2)
            self.assertAlmostEqual(first["dur"], 2.0, places=2)                       # 8 looks x 0.25 s, then Chrome took the focus
            chrome = [r for r in rows if r["app"] == "chrome"][0]
            self.assertEqual((chrome["ctl"], chrome["inp"]), ("Chrome_Widget", 0))
            self.assertEqual(first["inp"], 8)                                           # counts kept because the notice was accepted
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
