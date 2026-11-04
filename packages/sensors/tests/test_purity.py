# SPDX-License-Identifier: Apache-2.0
"""Production purity: no fake, mock, simulated or stub path may ship.

Test fixtures live only under tests/. The production package must
contain no such code path, and discovery must yield only the real
built-in platform adapters.
"""
import os
import re
import unittest

SRC = os.path.join(os.path.dirname(__file__), "..", "src", "sensors")
BANNED = re.compile(r"fake|mock|simulat|dummy|stub[_ ]?adapter|"
                    r"sample[_ ]?adapter", re.I)


class Purity(unittest.TestCase):
    def test_src_has_no_fake_paths(self):
        hits = []
        for root, _dirs, files in os.walk(SRC):
            for f in files:
                if f.endswith(".py"):
                    text = open(os.path.join(root, f),
                                encoding="utf-8").read()
                    for i, line in enumerate(text.splitlines(), 1):
                        if BANNED.search(line):
                            hits.append(f"{f}:{i}:{line.strip()}")
        self.assertEqual(hits, [])

    def test_discovery_yields_only_real_builtins(self):
        from sensors import adapters
        found = adapters.discover(include_unavailable=True)
        self.assertTrue(found)
        for adapter, _ok, _why in found:
            self.assertIn(type(adapter).__name__,
                          {c.__name__ for c in adapters._BUILTINS})

    def test_cli_run_wires_discovery_only(self):
        main = open(os.path.join(SRC, "__main__.py"),
                    encoding="utf-8").read()
        self.assertIn("Importer(discover(", main)
        self.assertNotIn("Fixture", main)


if __name__ == "__main__":
    unittest.main()
