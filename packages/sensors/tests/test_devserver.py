# SPDX-License-Identifier: Apache-2.0
import importlib.util
import os
import unittest

HERE = os.path.dirname(__file__)
SPEC = importlib.util.spec_from_file_location(
    "devserver", os.path.join(HERE, "..", "web", "devserver.py"))
devserver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(devserver)


class Validate(unittest.TestCase):
    def test_contract(self):
        ok = {"source_host": "mac", "events": [
            {"type": "attention.metrics", "data": {}},
            {"type": "ledger.event.added",
             "data": {"origin": "auto"}}]}
        events, err = devserver.validate(ok)
        self.assertIsNone(err)
        self.assertEqual(len(events), 2)
        _e, err = devserver.validate(
            {"events": [{"type": "evil.x", "data": {}}]})
        self.assertIn("bad types", err)
        _e, err = devserver.validate(
            {"events": [{"type": "ledger.event.added",
                         "data": {"origin": "manual"}}]})
        self.assertIn("bad types", err)
        _e, err = devserver.validate(
            {"events": [{"type": "narration.log", "data": {}}] * 201})
        self.assertIn("at most 200", err)

    def test_wrap_envelope(self):
        out = devserver.wrap({"source_host": "mac", "events": [
            {"type": "narration.log", "data": {"text": "x"}}]}, now=5.0)
        e = out[0]
        self.assertEqual(e["source"], "sensors@mac")
        self.assertEqual(e["ts"], 5.0)
        for k in ("id", "type", "subject", "causation_id",
                  "correlation_id", "schema", "data"):
            self.assertIn(k, e)

    def test_save_key_never_echoes(self):
        import stat as statmod
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / "runtime.env"
            env.write_text("RUNTIME_MODE=local\nMODEL_API_KEY=\n")
            os.environ["HUMANFLOW_ENV"] = str(env)
            try:
                n, fp = devserver.save_key("x" * 24)
            finally:
                del os.environ["HUMANFLOW_ENV"]
            body = env.read_text()
            self.assertIn("MODEL_API_KEY=" + "x" * 24, body)
            self.assertIn("RUNTIME_MODE=local", body)
            self.assertEqual(oct(statmod.S_IMODE(env.stat().st_mode))[-3:], "600")
            self.assertEqual(n, 24)
            self.assertNotIn("x" * 24, fp)

    def test_dashboard_has_panel(self):
        html = devserver.dashboard_html()
        self.assertIn('id="attention-panel"', html)
        self.assertIn('id="attention-log"', html)
        self.assertIn("prefers-color-scheme: dark", html)


if __name__ == "__main__":
    unittest.main()
