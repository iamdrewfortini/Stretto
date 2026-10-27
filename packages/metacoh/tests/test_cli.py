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
if __name__ == "__main__": unittest.main()
