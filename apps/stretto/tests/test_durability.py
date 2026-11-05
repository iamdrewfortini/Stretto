"""Durability: what is proven and what is not.
PROVEN here: committed data survives a killed process (SIGKILL); data is moved into the MAIN database file (not left only in the write-ahead log)
after writes that matter; the settings that govern power-loss safety are on; shutdown is clean; backups are consistent.
NOT provable here: an actual power cut. That is why the settings (synchronous=FULL, fullfsync) are asserted: they are the mechanism that matters."""
import contextlib, io, os, shutil, signal, sqlite3, subprocess, sys, tempfile, threading, time, unittest, json, http.client
from unittest import mock

from stretto import consent
from stretto import __main__ as cli
from stretto.store import Store

ROOT = os.path.join(os.path.dirname(__file__), "..")
T = 1_760_000_000


def rows(path, table="events"):
    c = sqlite3.connect(path)
    try:
        return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        c.close()


def main_file_only_count(db_path, table="events"):
    """Copy ONLY the main database file (no -wal, no -shm) and count rows: what a recovery that loses the log would see."""
    d = tempfile.mkdtemp()
    dst = os.path.join(d, "only-main.sqlite")
    shutil.copy(db_path, dst)
    return rows(dst, table)


def batch(n, start=0):
    return [dict(ts=T + start + i, dur=1, app="x", title=str(start + i)) for i in range(n)]


class Settings(unittest.TestCase):
    def test_power_loss_settings_are_on(self):
        d = Store(os.path.join(tempfile.mkdtemp(), "t.sqlite")).durability()
        self.assertEqual((d["journal_mode"], d["synchronous"]), ("wal", "FULL"))        # WAL + NORMAL can lose committed transactions on power loss
        self.assertTrue(d["fullfsync"] and d["checkpoint_fullfsync"])                   # macOS: fsync() alone does not flush the drive's cache


def main_only(db_path, sql, args=()):
    """Run a SELECT against a copy of ONLY the main database file (no -wal, no -shm)."""
    d = tempfile.mkdtemp()
    dst = os.path.join(d, "only-main.sqlite")
    shutil.copy(db_path, dst)
    c = sqlite3.connect(dst)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


class UserWrites(unittest.TestCase):
    """Everything a person creates or changes reaches the main database file immediately, through the real HTTP routes."""

    @classmethod
    def setUpClass(cls):
        from stretto.server import make_server
        cls.dir = tempfile.mkdtemp()
        cls.path = os.path.join(cls.dir, "t.sqlite")
        cls.store = Store(cls.path)
        cls.srv, cls.tok = make_server(cls.store, 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def post(self, path, body=None, admin=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Content-Type": "application/json"}
        if admin:
            h["X-Stretto-Token"] = self.tok
        c.request("POST", path, json.dumps(body or {}), h)
        r = c.getresponse()
        data = json.loads(r.read() or b"{}")
        c.close()
        self.assertEqual(r.status, 200, (path, data))
        return data

    def one(self, sql, args=()):
        return main_only(self.path, sql, args)

    def test_each_kind_of_hand_made_record_is_in_the_main_file_at_once(self):
        # a machine write just happened, so the throttle is "hot": it must NOT excuse a person's write from being checkpointed
        self.store.ingest(batch(3))
        p = self.post("/api/projects", dict(name="Plan"))
        self.assertEqual(self.one("SELECT name FROM projects WHERE id=?", (p["id"],)), [("Plan",)])
        t = self.post("/api/tasks", dict(title="Write plan", project_id=p["id"]))
        self.assertEqual(self.one("SELECT title FROM tasks WHERE id=?", (t["id"],)), [("Write plan",)])
        self.post(f"/api/tasks/{t['id']}", dict(status="done"))
        self.assertEqual(self.one("SELECT status FROM tasks WHERE id=?", (t["id"],)), [("done",)])
        h = self.post("/api/habits", dict(name="Walk"))
        self.assertEqual(self.one("SELECT name FROM habits WHERE id=?", (h["id"],)), [("Walk",)])
        self.post(f"/api/habits/{h['id']}/log", {"day": "2026-11-03"})
        self.assertEqual(self.one("SELECT day FROM habit_log WHERE habit_id=?", (h["id"],)), [("2026-11-03",)])
        self.post(f"/api/habits/{h['id']}/log", {"day": "2026-11-03"})                                   # toggled off
        self.assertEqual(self.one("SELECT day FROM habit_log WHERE habit_id=?", (h["id"],)), [])
        self.post("/api/rules", dict(field="app", pattern="^code$", category="Learn"))
        self.assertEqual(self.one("SELECT category FROM rules"), [("Learn",)])
        self.post("/api/settings", dict(goal_min=300))
        self.assertEqual(self.one("SELECT v FROM settings WHERE k='goal_min'"), [("300",)])

    def test_a_running_timer_and_its_stop_are_both_in_the_main_file(self):
        self.post("/api/timer/start", dict(label="Focus"))
        rows = self.one("SELECT label, end FROM timers ORDER BY id DESC LIMIT 1")
        self.assertEqual((rows[0][0], rows[0][1]), ("Focus", None))
        self.post("/api/timer/stop")
        self.assertIsNotNone(self.one("SELECT end FROM timers ORDER BY id DESC LIMIT 1")[0][0])

    def test_enrolment_and_revocation_of_a_device_key_are_in_the_main_file(self):
        code = self.post("/api/agent/enroll")["code"]
        self.post("/api/agent/register", dict(code=code, device="pc1", name="pc1"), admin=False)
        self.assertEqual(self.one("SELECT revoked FROM device_keys WHERE device='pc1'"), [(0,)])
        self.post("/api/agent/revoke", dict(device="pc1"))
        self.assertEqual(self.one("SELECT revoked FROM device_keys WHERE device='pc1'"), [(1,)])

    def test_consent_and_a_purge_the_person_asked_for_stay_done(self):
        self.post("/api/consent", dict(device="d9", family="browser-history", action="grant", granted_by="T P", typed=consent.phrase("browser-history")))
        self.assertEqual(self.one("SELECT action FROM consent WHERE device='d9'"), [("grant",)])
        self.post("/api/ingest", dict(device="d9", src="chrome-history:Default", samples=batch(5, start=500)))
        self.store.checkpoint(force=True)
        self.assertEqual(self.one("SELECT COUNT(*) FROM events WHERE device='d9'"), [(5,)])
        self.post("/api/purge", dict(device="d9", family="browser-history", confirm="DELETE browser-history"))
        self.assertEqual(self.one("SELECT COUNT(*) FROM events WHERE device='d9'"), [(0,)])                 # the deletion is in the main file too


class Crash(unittest.TestCase):
    def test_a_killed_process_loses_nothing_it_reported_as_stored(self):
        path = os.path.join(tempfile.mkdtemp(), "t.sqlite")
        code = (f"import sys, os; sys.path.insert(0, {ROOT!r}); from stretto.store import Store; s = Store({path!r}); "
                f"print(s.ingest([dict(ts={T} + i, dur=1, app='x', title=str(i)) for i in range(500)]), flush=True); os.kill(os.getpid(), 9)")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(r.returncode, -signal.SIGKILL)                                 # it really was killed, not exited
        self.assertEqual(r.stdout.strip(), "500")
        self.assertEqual(Store(path).q("SELECT COUNT(*) AS n FROM events")[0]["n"], 500)


class Checkpointing(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "t.sqlite")
        self.s = Store(self.path)

    def test_the_first_write_reaches_the_main_file_a_second_one_waits_and_a_forced_checkpoint_moves_it(self):
        self.s.ingest(batch(10))
        self.assertEqual(main_file_only_count(self.path), 10)                           # not stranded in the log
        self.s.ingest(batch(10, start=100))                                             # inside the throttle window
        self.assertEqual(main_file_only_count(self.path), 10)
        self.s.checkpoint(force=True)
        self.assertEqual(main_file_only_count(self.path), 20)

    def test_a_consent_record_is_always_in_the_main_file(self):
        self.s.ingest(batch(3))
        consent.record(self.s, "local", "host-system", "grant", "T P", consent.phrase("host-system"))
        self.assertEqual(main_file_only_count(self.path, "consent"), 1)                 # an acceptance is never at the mercy of the log

    def test_close_truncates_the_log(self):
        self.s.ingest(batch(5))
        self.s.ingest(batch(5, start=100))
        self.s.close()
        wal = self.path + "-wal"
        self.assertTrue(not os.path.exists(wal) or os.path.getsize(wal) == 0)
        self.assertEqual(main_file_only_count(self.path), 10)

    def test_memory_stores_ignore_checkpoints(self):
        m = Store(":memory:")
        m.ingest(batch(3))
        m.checkpoint(force=True)
        m.close()


@unittest.skipIf(os.name == "nt", "signals")
class Shutdown(unittest.TestCase):
    def test_sigterm_ends_in_a_clean_checkpointed_shutdown_and_the_token_survives_a_restart(self):
        d = tempfile.mkdtemp()
        env = dict(os.environ, PYTHONPATH=ROOT)
        for k in ("MODEL_API_KEY", "STRETTO_REPLAY"):
            env.pop(k, None)
        p = subprocess.Popen([sys.executable, "-u", "-m", "stretto", "--data", d, "--port", "0"], cwd=tempfile.mkdtemp(), env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            line = p.stdout.readline()
            self.assertIn("durability: wal/FULL", line)
            port = int(line.split("http://127.0.0.1:")[1].split()[0])
            tok = open(os.path.join(d, "token")).read().strip()
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            c.request("POST", "/api/demo/seed", "{}", {"X-Stretto-Token": tok, "Content-Type": "application/json"})
            self.assertEqual(c.getresponse().status, 200)
            self.assertGreater(main_file_only_count(os.path.join(d, "stretto.sqlite")), 1000)     # the seed is in the main file immediately
            p.send_signal(signal.SIGTERM)
            self.assertEqual(p.wait(timeout=15), 0)                                      # a clean exit, not a kill
        finally:
            if p.poll() is None:
                p.kill()
        wal = os.path.join(d, "stretto.sqlite-wal")
        self.assertTrue(not os.path.exists(wal) or os.path.getsize(wal) == 0)
        self.assertEqual(open(os.path.join(d, "token")).read().strip(), tok)                 # not rotated by a shutdown


class Token(unittest.TestCase):
    def test_reused_across_restarts_regenerated_when_garbage_and_private(self):
        d = tempfile.mkdtemp()
        first = cli.load_token(d)
        self.assertEqual(cli.load_token(d), first)                                       # a restart does not lock out an agent that holds it
        if os.name == "posix":
            self.assertEqual(os.stat(os.path.join(d, "token")).st_mode & 0o077, 0)
        for bad in ("", "short", "has spaces and is long enough to pass length x" * 2, "é" * 40):
            open(os.path.join(d, "token"), "w", encoding="utf-8").write(bad)
            fresh = cli.load_token(d)
            self.assertNotEqual(fresh, bad)
            self.assertGreaterEqual(len(fresh), 24)


class Backup(unittest.TestCase):
    def run_backup(self, data, out=None):
        argv = ["backup", "--data", data] + (["--out", out] if out else [])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as c:
            cli.main(argv)
        return c.exception.code, buf.getvalue()

    def test_a_consistent_copy_without_secrets_while_the_database_is_open(self):
        d = tempfile.mkdtemp()
        s = Store(os.path.join(d, "stretto.sqlite"))
        s.ingest(batch(300))
        open(os.path.join(d, ".env"), "w").write("MODEL_API_KEY=sk-SECRET\n")
        open(os.path.join(d, "token"), "w").write("t" * 32)
        code, out = self.run_backup(d)
        self.assertEqual(code, 0)
        self.assertIn("300 events, integrity ok", out)
        bdir = os.path.join(d, "backups")
        files = os.listdir(bdir)
        self.assertEqual(len(files), 1)
        self.assertEqual(rows(os.path.join(bdir, files[0])), 300)
        self.assertNotIn(b"sk-SECRET", open(os.path.join(bdir, files[0]), "rb").read())
        self.assertNotIn(b"t" * 32, open(os.path.join(bdir, files[0]), "rb").read())

    def test_only_the_newest_fourteen_are_kept(self):
        d = tempfile.mkdtemp()
        Store(os.path.join(d, "stretto.sqlite")).ingest(batch(5))
        bdir = os.path.join(d, "backups")
        os.makedirs(bdir)
        for i in range(16):
            open(os.path.join(bdir, f"stretto-2020010{i // 10}-0000{i % 10:02d}.sqlite"), "w").write("old")
        self.run_backup(d)
        names = sorted(os.listdir(bdir))
        self.assertEqual(len(names), 14)
        self.assertTrue(names[-1] > "stretto-2025")                                      # the new one survived; the oldest were dropped

    def test_no_database_is_an_error_not_an_empty_backup(self):
        code, _ = self.run_backup(tempfile.mkdtemp())
        self.assertNotEqual(code, 0)


class Doctor(unittest.TestCase):
    def test_doctor_reports_power_loss_safety(self):
        d = tempfile.mkdtemp()
        buf = io.StringIO()
        env = {k: v for k, v in os.environ.items() if k not in ("MODEL_API_KEY", "STRETTO_REPLAY")}
        with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(buf), mock.patch("os.getcwd", return_value=tempfile.mkdtemp()):
            with self.assertRaises(SystemExit):
                cli.main(["doctor", "--data", d, "--port", "0"])
        self.assertIn("[ok  ] database survives a power cut: wal, synchronous=FULL", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
