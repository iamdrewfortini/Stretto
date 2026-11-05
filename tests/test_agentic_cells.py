# SPDX-License-Identifier: Apache-2.0
"""Matrix-math tests for the 36-cell agentic CI/CD orchestrator (#21).

Run from the repo root: python3 -m unittest discover -s tests -t .
scripts/ is loaded by path so no package install is needed.
"""
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("agentic_cells", ROOT / "scripts" / "agentic_cells.py")
ac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ac)


class MatrixMath(unittest.TestCase):
    def test_36_cells_9_stages_4_each(self):
        roster = ac.build_roster()
        self.assertEqual(len(roster), 36)
        self.assertEqual(len({c["stage"] for c in roster}), 9)
        for sid, _ in ac.STAGES:
            self.assertEqual(len([c for c in roster if c["stage"] == sid]), 4)
        self.assertEqual([c["cell"] for c in roster[:2]], ["C01", "C02"])
        self.assertEqual(roster[-1]["cell"], "C36")

    def test_loop_cap_and_pass_bounds(self):
        summary, results = ac.run(loops=3)
        self.assertLessEqual(summary["loops_run"], 3)
        self.assertLessEqual(summary["cell_passes"], 108)
        self.assertEqual(summary["stage_passes"], 27 if summary["loops_run"] == 3 else summary["stage_passes"])
        self.assertEqual(summary["failed"], 0)

    def test_loops_above_cap_refused(self):
        with self.assertRaises(AssertionError):
            ac.run(loops=4)

    def test_skip_never_routed_and_weight_formula(self):
        self.assertAlmostEqual(ac.weight(dict(risk=1.0, confidence=1.0, cost=0.0)), 1.0)
        routed = ac.route([dict(cell="C99", status="skip", risk=1, confidence=1, cost=0),
                           dict(cell="C98", status="fail", risk=0, confidence=0, cost=9)])
        self.assertEqual(routed, ["C98"])

    def test_no_key_means_model_cells_skip(self):
        import os
        old = os.environ.pop("META_API_KEY", None)
        try:
            _, results = ac.run(loops=1)
        finally:
            if old is not None:
                os.environ["META_API_KEY"] = old
        mcp = [r for r in results if "mcp" in r["name"]]
        self.assertTrue(mcp and all(r["status"] == "skip" for r in mcp))


if __name__ == "__main__":
    unittest.main()
