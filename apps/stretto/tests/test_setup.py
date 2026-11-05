# SPDX-License-Identifier: Apache-2.0
"""Setup path: .env loading, doctor, person-run accept, install/run scripts."""
import contextlib, io, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

from stretto import consent, meta
from stretto import __main__ as cli
from stretto.store import Store

ROOT = os.path.join(os.path.dirname(__file__), "..")


def clean_env(**kw):
    base = {k: v for k, v in os.environ.items() if k not in ("MODEL_API_KEY", "STRETTO_REPLAY", "STRETTO_RECORD", "STRETTO_ENV_FILE")}
    base.update(kw)
    return mock.patch.dict(os.environ, base, clear=True)


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class EnvFile(unittest.TestCase):
    def test_data_dir_env_is_used_blank_values_are_ignored_and_real_env_wins(self):
        d = tempfile.mkdtemp()
        write(os.path.join(d, ".env"), "# comment\nMODEL_API_KEY=\nSTRETTO_REPLAY='/tmp/rec'\nOTHER=x y\n")
        with clean_env():
            self.assertEqual(meta.load_env(d), os.path.join(d, ".env"))
            self.assertNotIn("MODEL_API_KEY", os.environ)                  # the template's empty key does not count as configured
            self.assertEqual(os.environ["STRETTO_REPLAY"], "/tmp/rec")
        write(os.path.join(d, ".env"), "MODEL_API_KEY=from-file\n")
        with clean_env(MODEL_API_KEY="from-real-env"):
            meta.load_env(d)
            self.assertEqual(os.environ["MODEL_API_KEY"], "from-real-env")

    def test_no_env_file_is_fine(self):
        with clean_env(), mock.patch("os.getcwd", return_value=tempfile.mkdtemp()):
            self.assertIsNone(meta.load_env(tempfile.mkdtemp()))


class Doctor(unittest.TestCase):
    def run_doctor(self, data, **env):
        out = io.StringIO()
        with clean_env(**env), contextlib.redirect_stdout(out), mock.patch("os.getcwd", return_value=tempfile.mkdtemp()):
            with self.assertRaises(SystemExit) as c:
                cli.main(["doctor", "--data", data, "--port", "0"])
        return c.exception.code, out.getvalue()

    def test_ready_without_a_key_warns_but_does_not_block(self):
        code, text = self.run_doctor(tempfile.mkdtemp())
        self.assertEqual(code, 0)
        self.assertIn("[warn] Meta Model API access", text)
        self.assertIn("python3 -m stretto accept meta-insights", text)
        self.assertIn("Ready.", text)

    def test_the_key_value_is_never_printed(self):
        code, text = self.run_doctor(tempfile.mkdtemp(), MODEL_API_KEY="sk-TOPSECRET-123")
        self.assertNotIn("TOPSECRET", text)
        self.assertIn("[ok  ] Meta Model API access", text)

    def test_replay_mode_is_reported(self):
        d = tempfile.mkdtemp()
        code, text = self.run_doctor(tempfile.mkdtemp(), STRETTO_REPLAY=d)
        self.assertIn("keyless replay", text)

    def test_unwritable_data_folder_is_a_blocker(self):
        f = os.path.join(tempfile.mkdtemp(), "afile")
        write(f, "x")
        code, text = self.run_doctor(os.path.join(f, "sub"))               # a folder under a file cannot exist
        self.assertEqual(code, 1)
        self.assertIn("[FAIL] data folder is writable", text)


class Accept(unittest.TestCase):
    def test_needs_a_terminal_a_name_and_the_exact_phrase(self):
        d = tempfile.mkdtemp()
        with mock.patch("sys.stdin.isatty", return_value=False):
            with self.assertRaises(SystemExit):
                cli.main(["accept", "meta-insights", "--data", d])
        with mock.patch("sys.stdin.isatty", return_value=True), mock.patch("builtins.input", side_effect=["A Person", "yes"]), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as c:
                cli.main(["accept", "meta-insights", "--data", d])
        self.assertIn("Not accepted", str(c.exception.code))
        self.assertFalse(consent.active(Store(os.path.join(d, "stretto.sqlite")), "local", "meta-insights"))
        with mock.patch("sys.stdin.isatty", return_value=True), mock.patch("builtins.input", side_effect=["A Person", consent.phrase("meta-insights")]), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as c:
                cli.main(["accept", "meta-insights", "--data", d])
        self.assertEqual(c.exception.code, 0)
        st = Store(os.path.join(d, "stretto.sqlite"))
        self.assertTrue(consent.active(st, "local", "meta-insights"))
        self.assertTrue(consent.verify_chain(st))
        self.assertEqual(st.q("SELECT granted_by FROM consent")[0]["granted_by"], "A Person")


@unittest.skipUnless(shutil.which("sh"), "no sh")
class Scripts(unittest.TestCase):
    def test_shell_scripts_parse(self):
        for name in ("install.sh", "run.sh"):
            r = subprocess.run(["sh", "-n", os.path.join(ROOT, name)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, name + r.stderr)

    def test_install_no_start_creates_env_and_never_overwrites_it(self):
        home = tempfile.mkdtemp()
        env = dict(os.environ, STRETTO_DATA=os.path.join(home, "data"), HOME=home)
        for k in ("MODEL_API_KEY", "STRETTO_REPLAY"):
            env.pop(k, None)
        r = subprocess.run(["sh", os.path.join(ROOT, "install.sh"), "--no-start"], capture_output=True, text=True, env=env, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        envf = os.path.join(home, "data", ".env")
        self.assertTrue(os.path.isfile(envf))
        self.assertEqual(os.stat(envf).st_mode & 0o077, 0)
        write(envf, "MODEL_API_KEY=mine\n")
        subprocess.run(["sh", os.path.join(ROOT, "install.sh"), "--no-start"], capture_output=True, text=True, env=env, cwd=ROOT)
        self.assertEqual(open(envf).read(), "MODEL_API_KEY=mine\n")                      # a second run keeps the person's key
        self.assertNotIn("mine", r.stdout)


if __name__ == "__main__":
    unittest.main()
