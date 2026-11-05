"""Work-history importers (git, shell, logins), emit, and the SSH relay. Fixtures only: no real repositories, history files or servers."""
import contextlib, io, json, os, shutil, subprocess, sys, tempfile, threading, time, unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))
from stretto import consent
from stretto.server import make_server
from stretto.store import Store
from stretto_agent import cfg as C, cli, importers
from stretto_agent.client import Client

T1, T2, T3 = 1_760_000_000, 1_760_000_900, 1_760_001_800


def git(path, *args, **env):
    e = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null", **env)
    subprocess.run(["git", "-C", path] + list(args), check=True, capture_output=True, env=e)


def make_repo(root, name, commits):
    p = os.path.join(root, name)
    os.makedirs(p)
    subprocess.run(["git", "init", "-q", p], check=True)
    for email, t, msg in commits:
        d = f"{t} +0000"
        git(p, "-c", f"user.email={email}", "-c", "user.name=X", "commit", "-q", "--allow-empty", "-m", msg, GIT_AUTHOR_DATE=d, GIT_COMMITTER_DATE=d)
    return p


@unittest.skipUnless(shutil.which("git"), "git not installed")
class Git(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.repo = make_repo(self.root, "proj-a", [("me@example.com", T1, "SECRET client payroll fix"), ("other@example.org", T2, "SECRET other person"), ("me@example.com", T3, "second")])
        self.imp = importers.GitHistory("git-history:proj-a", self.repo, "me@example.com")

    def test_only_my_commit_times_and_the_repo_name_never_messages(self):
        out, cur, power = self.imp.read("")
        self.assertEqual([int(s["ts"]) for s in out], [T1, T3])             # the other author's commit is not mine
        self.assertEqual({(s["app"], s["title"]) for s in out}, {("git", "proj-a")})
        self.assertNotIn("SECRET", repr(out) + cur)
        self.assertNotIn("payroll", repr(out))
        self.assertEqual((cur, power), (str(T3), []))

    def test_incremental_picks_up_only_newer_work(self):
        _, cur, _ = self.imp.read("")
        git(self.repo, "-c", "user.email=me@example.com", "-c", "user.name=X", "commit", "-q", "--allow-empty", "-m", "later", GIT_AUTHOR_DATE=f"{T3 + 5000} +0000", GIT_COMMITTER_DATE=f"{T3 + 5000} +0000")
        out, cur2, _ = self.imp.read(cur)
        self.assertIn(T3 + 5000, [int(s["ts"]) for s in out])
        self.assertEqual(cur2, str(T3 + 5000))

    def test_discovery_finds_repos_prunes_junk_and_needs_an_email(self):
        make_repo(os.path.join(self.root, "nested"), "proj-b", []) if os.makedirs(os.path.join(self.root, "nested")) is None else None
        junk = os.path.join(self.root, "node_modules", "dep")
        os.makedirs(junk)
        subprocess.run(["git", "init", "-q", junk], check=True)
        with mock.patch.dict(os.environ, {"STRETTO_GIT_ROOTS": self.root}), mock.patch.object(importers, "_git", return_value=(0, "me@example.com\n")):
            names = sorted(i.name for i in importers.discover_work() if i.name.startswith("git-history"))
        self.assertEqual(names, ["git-history:proj-a", "git-history:proj-b"])
        with mock.patch.dict(os.environ, {"STRETTO_GIT_ROOTS": self.root}), mock.patch.object(importers, "_git", return_value=(0, "\n")):
            self.assertEqual([i for i in importers.discover_work() if i.name.startswith("git-history")], [])


class Shell(unittest.TestCase):
    def write(self, text):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "h")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_zsh_timestamps_only_never_commands(self):
        p = self.write(f": {T1}:0;export API_TOKEN=SECRET123 && curl https://x\n: {T2}:3;ls -la\ncontinued line without a stamp SECRET\n: {T3}:0;git push\n")
        out, cur, _ = importers.ShellHistory("shell-history:zsh", p, "zsh").read("")
        self.assertEqual([int(s["ts"]) for s in out], [T1, T2, T3])
        blob = repr(out) + cur
        for leak in ("SECRET", "curl", "export", "git push", "ls -la"):
            self.assertNotIn(leak, blob)
        self.assertEqual(importers.ShellHistory("shell-history:zsh", p, "zsh").read(cur)[0], [])

    def test_bash_with_histtimeformat(self):
        p = self.write(f"#{T1}\nsecret command one\n#{T2}\nsecret command two\nplain line\n")
        out, cur, _ = importers.ShellHistory("shell-history:bash", p, "bash").read("")
        self.assertEqual([int(s["ts"]) for s in out], [T1, T2])
        self.assertNotIn("secret", repr(out))

    def test_history_without_timestamps_yields_nothing(self):
        self.assertEqual(importers.ShellHistory("shell-history:bash", self.write("ls\ncd ..\n"), "bash").read("")[0], [])


class Logins(unittest.TestCase):
    TEXT = ("me  pts/0  192.0.2.5    Tue Nov  3 10:00:01 2026 - Tue Nov  3 11:02:03 2026  (01:02)\n"
            "me  tty1                Mon Nov  2 08:00:00 2026 - Mon Nov  2 20:00:00 2026  (12:00)\n"
            "me  pts/1  198.51.100.9     Wed Nov  4 01:00:00 2026   still logged in\n"
            "reboot  system boot  5.15.0  Mon Nov  2 07:59:00 2026   still running\n")

    def test_parse_sessions_capped_and_without_addresses(self):
        rows = importers.LoginSessions.parse(self.TEXT, now=time.mktime(time.strptime("Wed Nov  4 03:00:00 2026", "%a %b %d %H:%M:%S %Y")))
        self.assertEqual(len(rows), 3)
        self.assertEqual([r[2] for r in rows], ["ssh", "console", "ssh"])
        self.assertTrue(all(r[1] <= 7200 for r in rows))                  # being logged in is presence, capped at 2 hours
        self.assertNotIn("192.168", repr(rows))


class Gate(unittest.TestCase):
    def test_family_mapping_and_server_enforcement(self):
        self.assertEqual({consent.family_of(s) for s in ("git-history:x", "shell-history:zsh", "login-sessions")}, {"work-history"})
        store = Store(":memory:")
        srv, tok = make_server(store, 0)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            cl = Client(f"http://127.0.0.1:{port}", tok)
            with self.assertRaises(Exception) as c:
                cl.post("/api/ingest", dict(device="d1", src="git-history:x", samples=[dict(ts=T1, app="git", title="x")]))
            self.assertEqual(getattr(c.exception, "family", None), "work-history")
            cl.post("/api/consent", dict(device="d1", family="work-history", action="grant", granted_by="T P", typed=consent.phrase("work-history")))
            self.assertEqual(cl.post("/api/ingest", dict(device="d1", src="git-history:x", samples=[dict(ts=T1, app="git", title="x")]))["stored"], 1)
        finally:
            srv.shutdown()


class Emit(unittest.TestCase):
    def test_emit_prints_batches_without_network_or_config(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "h")
        open(p, "w").write(f": {T1}:0;secret\n")
        imp = importers.ShellHistory("shell-history:zsh", p, "zsh")
        out = io.StringIO()
        with mock.patch.object(importers, "discover_work", return_value=[imp]), mock.patch("sys.stdin.isatty", return_value=True), contextlib.redirect_stdout(out):
            cli.cmd_emit({}, mock.Mock(list=False))
        data = json.loads(out.getvalue())
        self.assertEqual(data["batches"][0]["src"], "shell-history:zsh")
        self.assertNotIn("secret", out.getvalue())
        out = io.StringIO()
        with mock.patch.object(importers, "discover_work", return_value=[imp]), contextlib.redirect_stdout(out):
            cli.cmd_emit({}, mock.Mock(list=True))
        self.assertEqual(json.loads(out.getvalue())["sources"][0]["source"], "shell-history:zsh")


class Remote(unittest.TestCase):
    def test_needs_acceptance_then_relays_and_always_cleans_up(self):
        store = Store(":memory:")
        srv, tok = make_server(store, 0)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        tf = os.path.join(tempfile.mkdtemp(), "tok"); open(tf, "w").write(tok)
        cfg = dict(C.DEFAULTS, server=f"http://127.0.0.1:{port}", token_file=tf)
        calls = []

        def fake_ssh(host, cmd, stdin=None, timeout=120):
            calls.append(cmd)
            if cmd == "mktemp -d":
                return mock.Mock(stdout="/tmp/stretto-xyz\n")
            if cmd.endswith("emit --list"):
                return mock.Mock(stdout=json.dumps(dict(os="Linux 5.15", sources=[dict(source="shell-history:bash")])))
            if "emit" in cmd:
                return mock.Mock(stdout=json.dumps(dict(os="Linux 5.15", batches=[dict(src="shell-history:bash", samples=[dict(ts=T1, dur=30, app="shell", title="")], power=[], cursor=str(T1))])))
            return mock.Mock(stdout="")
        try:
            a = mock.Mock(host="dev", device=None)
            with mock.patch.object(cli, "_ssh", side_effect=fake_ssh), mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)):
                with self.assertRaises(SystemExit) as c:
                    cli.cmd_remote(cfg, a)
                self.assertIn("accept work-history --device host-dev", str(c.exception.code))
                self.assertEqual(calls, [])                                  # nothing was touched on the host before acceptance
                Client(cfg["server"], tok).post("/api/consent", dict(device="host-dev", family="work-history", action="grant", granted_by="T P", typed=consent.phrase("work-history")))
                with contextlib.redirect_stdout(io.StringIO()):
                    cli.cmd_remote(cfg, a)
            self.assertEqual(store.q("SELECT device, src, app FROM events")[0], dict(device="host-dev", src="shell-history:bash", app="shell"))
            self.assertTrue(any("STRETTO_AGENT_HOME=/tmp/stretto-xyz/home" in c for c in calls))     # config goes to the temp folder, not the host's profile
            self.assertEqual(calls[-1], "rm -rf /tmp/stretto-xyz")
            calls.clear()
            def boom(host, cmd, stdin=None, timeout=120):
                calls.append(cmd)
                if cmd == "mktemp -d":
                    return mock.Mock(stdout="/tmp/stretto-abc\n")
                raise RuntimeError("ssh dropped")
            with mock.patch.object(cli, "_ssh", side_effect=boom), mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)):
                with self.assertRaises(RuntimeError):
                    cli.cmd_remote(cfg, a)
            self.assertEqual(calls[-1], "rm -rf /tmp/stretto-abc")           # cleanup is attempted even when the run fails
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
