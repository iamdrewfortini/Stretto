# SPDX-License-Identifier: Apache-2.0
import io, contextlib, json, unittest
from metacoh import cli, doctor

class Cli(unittest.TestCase):
    def test_wf13d_command_matches_the_bridge(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out): rc = cli.main(["wf13d", "15.07.072"])
        j = json.loads(out.getvalue()); self.assertEqual((rc, j["c"], j["ask"]), (0, "FRONTIER", ["WHAT", "WHERE", "WHY", "HOW"]))
    def test_doctor_checks_that_do_not_need_installation_pass_from_source(self):
        res = {n: ok for n, ok, _ in doctor.run_all()}
        for name in ("ant locks (empty grid)", "consent default-deny", "meta-only policy", "distance from coherence", "mirror + tesseract", "handoff gap detection", "resonance"): self.assertTrue(res[name], name)
    def test_a_failing_check_is_reported_not_raised(self): n, ok, detail = doctor._check("boom", lambda: 1 / 0); self.assertFalse(ok); self.assertIn("ZeroDivisionError", detail)
    def test_gateway_env_file_defaults_and_process_override(self):
        import os, tempfile
        with tempfile.TemporaryDirectory() as home:
            cfg = os.path.join(home, ".config", "humanflow"); os.makedirs(cfg)
            with open(os.path.join(cfg, "runtime.env"), "w", encoding="utf-8") as f:
                f.write("GATEWAY_BIND=127.0.0.1:9999 # loopback\nMODEL_API_KEY=filekey\n")
            env = cli._gateway_env({"GATEWAY_BIND": "127.0.0.1:7777"}, home)
            self.assertEqual(env["GATEWAY_BIND"], "127.0.0.1:7777")  # process wins
            self.assertEqual(env["MODEL_API_KEY"], "filekey")        # file supplies the rest
            self.assertEqual(env["RUNTIME_MODE"], "local")
            self.assertTrue(env["EVENT_LOG"].startswith(os.path.join(home, ".local", "share", "humanflow")))
    def test_gateway_and_sensors_dispatch(self):
        import sys, types
        seen = {}
        fake_gw = types.ModuleType("runtime.gateway"); fake_gw.serve = lambda env: seen.setdefault("env", env)
        fake_sm = types.ModuleType("sensors.__main__")
        def _fake_sensors_main(argv): seen["argv"] = argv; return 7
        fake_sm.main = _fake_sensors_main
        saved = {k: sys.modules.get(k) for k in ("runtime.gateway", "sensors.__main__")}
        sys.modules["runtime.gateway"] = fake_gw; sys.modules["sensors.__main__"] = fake_sm
        try:
            self.assertEqual(cli.main(["gateway"]), 0); self.assertIn("RUNTIME_MODE", seen["env"])
            self.assertEqual(cli.main(["sensors", "probe"]), 7); self.assertEqual(seen["argv"], ["probe"])
        finally:
            for k, v in saved.items():
                if v is None: sys.modules.pop(k, None)
                else: sys.modules[k] = v
if __name__ == "__main__": unittest.main()
