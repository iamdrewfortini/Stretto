# SPDX-License-Identifier: Apache-2.0
"""Device enrolment and scope, the agent bundle, the environment report, and the native permission plan."""
import io, json, os, sys, tempfile, threading, time, unittest, urllib.error, urllib.request, zipfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))
from stretto import bundle, consent, enroll
from stretto.server import make_server
from stretto.store import Store
from stretto_agent import cfg as C, cli, perms

T0 = 1_760_000_000


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

    def call(self, method, path, body=None, admin=True, key=None, raw=False):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, data=json.dumps(body).encode() if body is not None else None)
        req.add_header("Host", f"127.0.0.1:{self.port}")
        if admin:
            req.add_header("X-Stretto-Token", self.tok)
        if key:
            req.add_header("X-Stretto-Device-Key", key)
        try:
            with urllib.request.urlopen(req) as r:
                data = r.read()
                return r.status, (data if raw else json.loads(data)), r.headers
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), e.headers

    def enrol(self, device):
        code = self.call("POST", "/api/agent/enroll", {})[1]["code"]
        code_, r, _ = self.call("POST", "/api/agent/register", dict(code=code, device=device, name=device), admin=False)
        self.assertEqual(code_, 200)
        return r["device_key"], code

    # ---- enrolment
    def test_code_is_single_use_and_wrong_codes_fail(self):
        key, code = self.enrol("devA")
        self.assertEqual(self.call("POST", "/api/agent/register", dict(code=code, device="devA2"), admin=False)[0], 403)      # reused
        self.assertEqual(self.call("POST", "/api/agent/register", dict(code="nope", device="devA3"), admin=False)[0], 403)
        self.assertEqual(self.call("POST", "/api/agent/enroll", {}, admin=False)[0], 403)                                     # only an admin mints codes

    def test_expired_code_fails_and_device_id_is_validated(self):
        code = self.call("POST", "/api/agent/enroll", {})[1]["code"]
        self.store.x("UPDATE enroll_codes SET expires=?", (time.time() - 1,))
        self.assertEqual(self.call("POST", "/api/agent/register", dict(code=code, device="devB"), admin=False)[0], 403)
        code2 = self.call("POST", "/api/agent/enroll", {})[1]["code"]
        self.assertEqual(self.call("POST", "/api/agent/register", dict(code=code2, device="bad id; rm -rf"), admin=False)[0], 400)

    def test_key_is_only_stored_as_a_hash(self):
        key, _ = self.enrol("devC")
        self.assertNotIn(key, json.dumps(self.store.q("SELECT * FROM device_keys")))
        self.assertEqual(enroll.device_for_key(self.store, key), "devC")
        self.assertIsNone(enroll.device_for_key(self.store, key + "x"))

    def test_revoking_a_device_kills_its_key_at_once(self):
        key, _ = self.enrol("devD")
        self.call("POST", "/api/consent", dict(device="devD", family="host-system", action="grant", granted_by="T P", typed=consent.phrase("host-system")))
        ok = dict(device="devD", src="collector", samples=[dict(ts=T0, app="Code")])
        self.assertEqual(self.call("POST", "/api/ingest", ok, admin=False, key=key)[0], 200)
        self.call("POST", "/api/agent/revoke", dict(device="devD"))
        self.assertEqual(self.call("POST", "/api/ingest", ok, admin=False, key=key)[0], 403)

    # ---- scope
    def test_device_key_can_only_act_for_its_own_device(self):
        key, _ = self.enrol("devE")
        for d in ("devE",):
            self.call("POST", "/api/consent", dict(device=d, family="host-system", action="grant", granted_by="T P", typed=consent.phrase("host-system")))
        own = dict(device="devE", src="collector", samples=[dict(ts=T0, app="Code")])
        self.assertEqual(self.call("POST", "/api/ingest", own, admin=False, key=key)[1]["stored"], 1)
        other = dict(device="someone-else", src="collector", samples=[dict(ts=T0, app="Code")])
        self.assertEqual(self.call("POST", "/api/ingest", other, admin=False, key=key)[1]["error"], "out_of_scope")
        self.assertEqual(self.call("GET", "/api/cursor?device=devE&src=collector", admin=False, key=key)[0], 200)
        self.assertEqual(self.call("GET", "/api/cursor?device=someone-else&src=collector", admin=False, key=key)[0], 403)

    def test_device_key_cannot_read_data_accept_notices_or_enrol(self):
        key, _ = self.enrol("devF")
        self.assertEqual(self.call("GET", "/api/day", admin=False, key=key)[1]["error"], "out_of_scope")
        self.assertEqual(self.call("GET", "/api/patterns", admin=False, key=key)[0], 403)
        grant = dict(device="devF", family="host-system", action="grant", granted_by="Agent", typed=consent.phrase("host-system"))
        self.assertEqual(self.call("POST", "/api/consent", grant, admin=False, key=key)[1]["error"], "out_of_scope")        # agents never accept for a person
        self.assertEqual(self.call("POST", "/api/agent/enroll", {}, admin=False, key=key)[0], 403)
        self.assertEqual(self.call("POST", "/api/purge", dict(device="devF", family="host-system", confirm="DELETE host-system"), admin=False, key=key)[0], 403)

    def test_device_key_can_stop_recording(self):
        key, _ = self.enrol("devG")
        self.call("POST", "/api/consent", dict(device="devG", family="host-system", action="grant", granted_by="T P", typed=consent.phrase("host-system")))
        rev = dict(device="devG", family="host-system", action="revoke", granted_by="agent on devG")
        self.assertEqual(self.call("POST", "/api/consent", rev, admin=False, key=key)[0], 200)
        self.assertFalse(consent.active(self.store, "devG", "host-system"))

    # ---- bundle
    def test_bundle_has_agent_installer_and_no_master_token(self):
        for osn, installer in (("windows", "install.ps1"), ("linux", "install.sh"), ("macos", "install.sh")):
            code, data, hdr = self.call("POST", "/api/agent/bundle", dict(os=osn), raw=True)
            self.assertEqual(code, 200)
            self.assertIn(f"stretto-agent-{osn}.zip", hdr["Content-Disposition"])
            z = zipfile.ZipFile(io.BytesIO(data))
            names = z.namelist()
            self.assertIn(f"stretto-agent/{installer}", names)
            self.assertIn("stretto-agent/agent/stretto_agent/cli.py", names)
            self.assertIn("stretto-agent/agent/stretto_agent/perms.py", names)
            blob = b"".join(z.read(n) for n in names)
            self.assertNotIn(self.tok.encode(), blob)                                    # the master token never ships
            cfg = json.loads(z.read("stretto-agent/agent.json"))
            self.assertTrue(cfg["server"].startswith("http://127.0.0.1:"))
            self.assertEqual(self.call("POST", "/api/agent/register", dict(code=cfg["enroll_code"], device="b-" + osn), admin=False)[0], 200)   # its code works once
            if installer.endswith("sh"):
                self.assertTrue(z.getinfo(f"stretto-agent/{installer}").external_attr >> 16 & 0o111)
        self.assertEqual(self.call("POST", "/api/agent/bundle", dict(os="amiga"))[0], 400)
        self.assertEqual(self.call("POST", "/api/agent/bundle", dict(os="linux"), admin=False)[0], 403)

    # ---- environment report
    def test_environment_report_is_stored_as_display_only_data(self):
        key, _ = self.enrol("devH")
        plan = dict(os="windows", os_label="Windows 10", user="u", admin=False, required_missing=[],
                    items=[dict(id="x", source="power", label="L", why="W", status="weird", required=True, available=True, note="",
                                panel=dict(label="P", uri="ms-settings:x", argv=["calc.exe"]),
                                elevated=dict(description="D", display="cmd", how="UAC", argv=["evil.exe"]))])
        self.assertEqual(self.call("POST", "/api/agent/environment", dict(device="devH", plan=plan), admin=False, key=key)[0], 200)
        stored = self.call("GET", "/api/agent/environment?device=devH")[1]["plan"]
        self.assertNotIn("argv", json.dumps(stored))                                      # nothing executable is kept
        self.assertEqual(stored["items"][0]["status"], "unknown")                          # an unrecognised status is not trusted
        self.assertEqual(self.call("POST", "/api/agent/environment", dict(device="other", plan=plan), admin=False, key=key)[0], 403)
        self.assertEqual(self.call("GET", "/api/agent/environment?device=devH", admin=False, key=key)[0], 403)


class Perms(unittest.TestCase):
    def detect(self, system, **patches):
        with mock.patch.object(C, "system", return_value=system), mock.patch.object(perms, "_history_readable", return_value="granted"), \
                mock.patch.object(perms, "_run", return_value=(0, "")), mock.patch.object(perms, "is_admin", return_value=False):
            ctx = [mock.patch.object(perms, k, **v) for k, v in patches.items()]
            for c in ctx:
                c.start()
            try:
                return perms.detect()
            finally:
                for c in ctx:
                    c.stop()

    def test_windows_plan_lists_uac_command_as_planned_and_needs_nothing_to_record(self):
        p = self.detect("windows")
        ids = {i["id"]: i for i in p["items"]}
        self.assertEqual(ids["foreground-window"]["status"], "granted")
        self.assertEqual(p["required_missing"], [])
        sec = ids["security-log"]
        self.assertFalse(sec["available"])                                                 # honest: planned, not built
        self.assertIn("Add-LocalGroupMember -Group 'Event Log Readers'", sec["elevated"]["display"])
        self.assertIn("RunAs", sec["elevated"]["argv"][-1])
        self.assertIn("UAC", sec["elevated"]["how"])
        self.assertTrue(ids["activity-history"]["panel"]["uri"].startswith("ms-settings:"))

    def test_macos_plan_derives_the_accessibility_pane_and_reports_missing(self):
        p = self.detect("macos", _ax_trusted=dict(return_value=False))
        acc = {i["id"]: i for i in p["items"]}["accessibility"]
        self.assertEqual(acc["status"], "missing")
        self.assertEqual(acc["panel"]["argv"][0], "open")
        self.assertTrue(acc["panel"]["uri"].endswith("Privacy_Accessibility"))
        self.assertIn(os.path.realpath(sys.executable), acc["note"])
        self.assertEqual({i["id"]: i for i in self.detect("macos", _ax_trusted=dict(return_value=True))["items"]}["accessibility"]["status"], "granted")

    def test_linux_wayland_is_unsupported_and_x11_missing_tools_get_a_package_command(self):
        with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}):
            d = {i["id"]: i for i in self.detect("linux")["items"]}["display-session"]
        self.assertEqual(d["status"], "unsupported")
        self.assertIn("Xorg", d["note"])
        env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "XDG_SESSION_TYPE")}
        env["DISPLAY"] = ":0"
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("shutil.which", return_value=None), mock.patch.object(perms, "_pkg_manager", return_value="apt"):
            p = self.detect("linux")
        d = {i["id"]: i for i in p["items"]}["display-session"]
        self.assertEqual(d["status"], "missing")
        self.assertEqual(d["elevated"]["display"], "sudo apt-get install -y xdotool xprintidle")
        self.assertEqual(p["required_missing"], ["display-session"])

    def test_every_executable_comes_from_the_fixed_table_and_public_view_strips_it(self):
        p = self.detect("windows")
        pub = perms.public(p)
        self.assertNotIn("argv", json.dumps(pub))
        for it in p["items"]:
            for k in ("panel", "elevated"):
                if it[k]:
                    self.assertTrue(all(isinstance(a, str) for a in it[k]["argv"]))

    def test_run_elevated_runs_only_the_tables_argv(self):
        with mock.patch.object(C, "system", return_value="windows"), mock.patch.object(perms, "_history_readable", return_value="granted"), \
                mock.patch.object(perms, "_run", return_value=(0, "")), mock.patch.object(perms, "is_admin", return_value=False), \
                mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)) as run:
            self.assertEqual(perms.run_elevated("security-log"), 0)
            self.assertIsNone(perms.run_elevated("foreground-window"))                      # no elevated command: nothing runs
            self.assertIsNone(perms.run_elevated("; calc"))
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args[0][0][:3], ["powershell", "-NoProfile", "-Command"])

    def test_cli_run_needs_a_person_and_the_exact_confirmation(self):
        a = mock.Mock(action="run", id="security-log")
        with mock.patch.object(C, "system", return_value="windows"), mock.patch.object(perms, "_history_readable", return_value="granted"), \
                mock.patch.object(perms, "_run", return_value=(0, "")), mock.patch.object(perms, "is_admin", return_value=False):
            with mock.patch("sys.stdin.isatty", return_value=False):
                with self.assertRaises(SystemExit):
                    cli.cmd_perms({}, a)
            with mock.patch("sys.stdin.isatty", return_value=True), mock.patch("builtins.input", return_value="yes"), \
                    mock.patch.object(perms, "run_elevated") as ran:
                with self.assertRaises(SystemExit):
                    cli.cmd_perms({}, a)
                ran.assert_not_called()
            with mock.patch("sys.stdin.isatty", return_value=True), mock.patch("builtins.input", return_value="RUN security-log"), \
                    mock.patch.object(perms, "run_elevated", return_value=0) as ran:
                cli.cmd_perms({}, a)
                ran.assert_called_once_with("security-log")


class AgentEnrol(unittest.TestCase):
    def test_enroll_saves_a_private_key_and_drops_the_master_token(self):
        store = Store(":memory:")
        srv, tok = make_server(store, 0)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            code, _ = enroll.new_code(store)
            home = tempfile.mkdtemp()
            with mock.patch.dict(os.environ, {"STRETTO_AGENT_HOME": home}):
                cfg = dict(C.DEFAULTS, server=f"http://127.0.0.1:{port}", token_file="/master/token", device="agentdev", device_name="pc")
                cli.cmd_enroll(cfg, mock.Mock(code=code))
                self.assertEqual(cfg["token_file"], "")
                key = C.device_key(cfg)
                self.assertTrue(key)
                if os.name == "posix":
                    self.assertEqual(os.stat(cfg["device_key_file"]).st_mode & 0o077, 0)       # readable only by its owner
                cl = cli._client(cfg)
                self.assertEqual(cl.device_key, key)
                self.assertEqual(cl.token, "")
                self.assertIn("host-system", cl.consent("agentdev"))
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
