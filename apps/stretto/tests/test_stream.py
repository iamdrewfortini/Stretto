"""Period deltas, previous attention score, range trend value, cross-device overlap, and the live event stream."""
import datetime as dt, http.client, json, threading, time, unittest

from stretto import demo, merge
from stretto.server import Api, make_server
from stretto.store import Store

TODAY = dt.date.today()


def start_of(k):
    return dt.datetime.combine(TODAY - dt.timedelta(days=k), dt.time()).timestamp()


def iso(k):
    return (TODAY - dt.timedelta(days=k)).isoformat()


def seg(t, secs, app="Code", device="d", src="collector", idle=0, title="t"):
    return [dict(ts=t + i * 5, dur=5, app=app, title=title, idle=idle, src=src, device=device) for i in range(int(secs // 5))]


class Deltas(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")
        self.api = Api(self.s)

    def test_no_earlier_data_means_prev_null_and_no_delta_keys(self):
        self.s.ingest(demo.samples(start_of(1), seed=1), "collector", "d")
        sm = self.api.day(iso(1))["summary"]
        self.assertIsNone(sm["prev"])
        self.assertNotIn("delta", sm)
        self.assertNotIn("delta_pct", sm)

    def test_prev_is_the_latest_earlier_day_with_data_and_empty_days_are_skipped(self):
        self.s.ingest(demo.samples(start_of(6), seed=1), "collector", "d")
        self.s.ingest(demo.samples(start_of(1), seed=2), "collector", "d")                       # days 5..2 have nothing
        sm = self.api.day(iso(1))["summary"]
        self.assertEqual(sm["prev"]["date"], iso(6))

    def test_delta_is_today_minus_prev_in_signed_ints_and_pct_is_two_decimals(self):
        self.s.ingest(seg(start_of(3) + 9 * 3600, 600) + seg(start_of(3) + 10 * 3600, 120, app="chrome", title="Funny cats - YouTube"), "collector", "d")
        self.s.ingest(seg(start_of(2) + 9 * 3600, 900) + seg(start_of(2) + 10 * 3600, 60, app="chrome", title="Funny cats - YouTube"), "collector", "d")
        sm = self.api.day(iso(2))["summary"]
        p, d, pc = sm["prev"], sm["delta"], sm["delta_pct"]
        self.assertEqual((p["date"], p["focus_s"], p["distraction_s"]), (iso(3), 600, 120))
        self.assertEqual((sm["focus_s"], sm["distraction_s"]), (900, 60))
        self.assertEqual((d["focus_s"], d["distraction_s"], d["total_s"]), (300, -60, 240))
        self.assertTrue(all(isinstance(v, int) for v in d.values()))
        self.assertEqual((pc["focus_s"], pc["distraction_s"]), (0.5, -0.5))
        self.assertEqual(set(p), {"date", "focus_s", "distraction_s", "idle_s", "total_s", "loss_s"})

    def test_pct_is_null_when_the_previous_value_is_zero(self):
        self.s.ingest(seg(start_of(3) + 9 * 3600, 600), "collector", "d")                        # no idle, no distraction
        self.s.ingest(seg(start_of(2) + 9 * 3600, 600) + seg(start_of(2) + 10 * 3600, 60, app="idle", idle=1, title=""), "collector", "d")
        sm = self.api.day(iso(2))["summary"]
        self.assertIsNone(sm["delta_pct"]["idle_s"])
        self.assertEqual(sm["delta"]["idle_s"], 60)

    def test_attention_prev_and_delta_score(self):
        self.s.ingest(demo.samples(start_of(3), seed=1), "collector", "d")
        self.s.ingest(demo.samples(start_of(2), seed=2), "collector", "d")
        a = self.api.attention(iso(2))
        self.assertIsInstance(a["prev_score"], int)
        self.assertEqual(a["delta_score"], a["score"] - a["prev_score"])
        first = self.api.attention(iso(3))
        self.assertIsNone(first["prev_score"])
        self.assertIsNone(first["delta_score"])

    def test_range_gives_the_focus_of_the_n_days_before_it(self):
        for k in (9, 8, 7, 3, 2):
            self.s.ingest(seg(start_of(k) + 9 * 3600, 600), "collector", "d")                   # 600 s focus each
        r = self.api.range(7)                                                                   # covers days 6..0; the 7 days before are 13..7
        self.assertEqual(r["prev_total_focus_s"], 1800)
        self.assertEqual(sum(d["focus_s"] for d in r["days"]), 1200)


class Overlap(unittest.TestCase):
    def ev(self, device, t, secs, **kw):
        return seg(t, secs, device=device, **kw)

    def test_two_devices_at_once_are_measured_and_named(self):
        t = start_of(1) + 9 * 3600
        s, dev = merge.overlap(self.ev("laptop", t, 600, app="Code") + self.ev("desktop", t, 600, app="chrome"))
        self.assertEqual((s, dev), (600, ["desktop", "laptop"]))

    def test_partial_overlap_counts_only_the_shared_seconds(self):
        t = start_of(1) + 9 * 3600
        s, _ = merge.overlap(self.ev("a", t, 600) + self.ev("b", t + 300, 600))
        self.assertEqual(s, 300)

    def test_touching_stays_idle_estimated_and_single_device_do_not_overlap(self):
        t = start_of(1) + 9 * 3600
        self.assertEqual(merge.overlap(self.ev("a", t, 300) + self.ev("b", t + 300, 300))[0], 0)                        # one ends as the other starts
        self.assertEqual(merge.overlap(self.ev("a", t, 600) + self.ev("b", t, 600, idle=1, app="idle"))[0], 0)          # an idle computer is not in use
        self.assertEqual(merge.overlap(self.ev("a", t, 600) + self.ev("b", t, 600, src="chrome-history:Default"))[0], 0)  # inferred history cannot say
        self.assertEqual(merge.overlap(self.ev("a", t, 600))[0], 0)

    def test_the_day_summary_reports_it(self):
        s = Store(":memory:")
        t = start_of(1) + 9 * 3600
        s.ingest(self.ev("laptop", t, 300), "collector", "laptop")
        s.ingest(self.ev("desktop", t, 300), "collector", "desktop")
        sm = Api(s).day(iso(1))["summary"]
        self.assertEqual((sm["concurrent_s"], sm["concurrent_devices"]), (300, ["desktop", "laptop"]))      # measured in the raw data
        self.assertEqual((sm["overlap_s"], sm["overlap_devices"]), (0, []))                                  # and resolved: counted once
        quiet = Store(":memory:")
        quiet.ingest(self.ev("laptop", t, 300), "collector", "laptop")
        sm = Api(quiet).day(iso(1))["summary"]
        self.assertEqual((sm["overlap_s"], sm["overlap_devices"]), (0, []))


def read_event(resp):
    """Next SSE frame as a dict. Comments come back as {'comment': ...}; the 'retry:' preamble is skipped."""
    ev = {}
    while True:
        line = resp.fp.readline()
        if not line:
            return None
        line = line.decode().rstrip("\r\n")
        if line == "":
            if "retry" in ev and len(ev) == 1:
                ev = {}
                continue
            if ev:
                return ev
            continue
        if line.startswith(":"):
            ev["comment"] = line
        else:
            k, _, v = line.partition(": ")
            ev[k] = v


class Stream(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.srv, self.tok = make_server(self.store, 0)
        self.port = self.srv.server_address[1]
        self.api = self.srv.RequestHandlerClass.api
        self.api.bus.poll_s, self.api.bus.heartbeat_s = 0.1, 0.4
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.conns = []

    def tearDown(self):
        for c in self.conns:
            c.close()
        self.srv.shutdown()

    def open(self, token=True, headers=None, query=""):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.conns.append(c)
        h = dict(headers or {})
        if token == "header":
            h["X-Stretto-Token"] = self.tok
        c.request("GET", "/api/events" + (f"?token={self.tok}" if token is True else "") + query, headers=h)
        return c, c.getresponse()

    def post(self, path, body=None, ):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("POST", path, json.dumps(body or {}), {"X-Stretto-Token": self.tok, "Content-Type": "application/json"})
        r = c.getresponse()
        data = json.loads(r.read())
        c.close()
        return r.status, data

    def until(self, resp, name, limit=30):
        for _ in range(limit):
            ev = read_event(resp)
            self.assertIsNotNone(ev, f"stream closed before '{name}'")
            if ev.get("event") == name:
                return ev
        self.fail(f"no '{name}' event")

    def test_token_is_required_via_header_or_query_and_the_content_type_is_sse(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", "/api/events")
        self.assertEqual(c.getresponse().status, 403)
        c.close()
        for mode in (True, "header"):
            _, r = self.open(token=mode)
            self.assertEqual(r.status, 200)
            self.assertEqual(r.getheader("Content-Type"), "text/event-stream")

    def test_hello_is_first_and_carries_the_timer_body(self):
        self.post("/api/timer/start", dict(label="Write plan"))
        _, r = self.open()
        ev = read_event(r)
        self.assertEqual(ev["event"], "hello")
        data = json.loads(ev["data"])
        self.assertIn("server_ts", data)
        self.assertEqual(data["timer"]["label"], "Write plan")
        self.assertTrue(ev["id"].isdigit())

    def test_timer_events_carry_exactly_the_get_timer_body(self):
        _, r = self.open()
        self.until(r, "hello")
        self.post("/api/timer/start", dict(label="Focus"))
        ev = self.until(r, "timer")
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", "/api/timer")
        body = json.loads(c.getresponse().read())
        self.assertEqual(json.loads(ev["data"]), body)
        self.post("/api/timer/stop")
        self.assertIsNone(json.loads(self.until(r, "timer")["data"]))

    def test_new_data_for_today_produces_block_then_day_events_and_existing_blocks_are_not_replayed(self):
        now = time.time()
        self.store.ingest(seg(now - 600, 300), "collector", "d")                      # already there before anyone connects
        _, r = self.open()
        self.until(r, "hello")
        time.sleep(0.5)                                                              # several watcher ticks pass with no new data
        self.assertEqual([m[1] for m in self.api.bus.ring if m[1] in ("block", "day")], [])   # nothing announced for what already existed
        self.store.ingest(seg(now - 200, 100, app="chrome", title="Docs - Google Docs"), "collector", "d")
        blk = self.until(r, "block")
        data = json.loads(blk["data"])
        self.assertIn("seconds", data)
        self.assertNotIn("key", data)
        day = self.until(r, "day")
        d = json.loads(day["data"])
        self.assertEqual(d["date"], TODAY.isoformat())
        self.assertIn("overlap_s", d["summary"])
        self.assertGreater(int(blk["id"]), 0)
        self.assertLess(int(blk["id"]), int(day["id"]))                              # ids are monotonic

    def test_heartbeat_comment_arrives_when_nothing_happens(self):
        _, r = self.open()
        self.until(r, "hello")
        ev = read_event(r)
        self.assertEqual(ev, {"comment": ": heartbeat"})

    def test_resume_with_last_event_id_replays_what_was_missed_and_unknown_ids_get_hello(self):
        _, r = self.open()
        self.until(r, "hello")
        self.post("/api/timer/start", dict(label="one"))
        first = self.until(r, "timer")
        r.close()
        self.post("/api/timer/stop")                                                   # happens while disconnected
        _, r2 = self.open(headers={"Last-Event-ID": first["id"]})
        ev = read_event(r2)
        self.assertEqual(ev["event"], "timer")
        self.assertIsNone(json.loads(ev["data"]))
        self.assertGreater(int(ev["id"]), int(first["id"]))
        _, r3 = self.open(headers={"Last-Event-ID": "999999"})
        self.assertEqual(read_event(r3)["event"], "hello")

    def test_the_watcher_stops_when_the_last_client_leaves(self):
        c, r = self.open()
        self.until(r, "hello")
        self.assertIsNotNone(self.api.bus.watcher)
        r.close()                                                                      # the response holds the socket too: close both, as a browser does
        c.close()
        for _ in range(40):
            if self.api.bus.watcher is None and self.api.bus.count() == 0:
                break
            time.sleep(0.1)
        self.assertEqual(self.api.bus.count(), 0)
        self.assertIsNone(self.api.bus.watcher)

    def test_a_device_key_cannot_open_the_stream(self):
        from stretto import enroll
        code, _ = enroll.new_code(self.store)
        key = enroll.register(self.store, code, "dev1", "dev1")
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", "/api/events", headers={"X-Stretto-Device-Key": key})
        self.assertEqual(c.getresponse().status, 403)


if __name__ == "__main__":
    unittest.main()
