# SPDX-License-Identifier: Apache-2.0
import importlib.util
import os
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                    "..", "..", ".."))
SPEC = importlib.util.spec_from_file_location(
    "why_check", os.path.join(ROOT, "scripts", "why_check.py"))
why_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(why_check)


class WhyCheck(unittest.TestCase):
    def test_repo_carries_the_why(self):
        self.assertEqual(why_check.check(ROOT), [])

    def test_missing_why_fails(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(why_check.check(tmp))


if __name__ == "__main__":
    unittest.main()
