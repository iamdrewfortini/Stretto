# SPDX-License-Identifier: Apache-2.0
import os
import unittest

PANEL = os.path.join(os.path.dirname(__file__), "..", "web",
                     "attention-panel.html")
IDS = ("attention-panel", "att-focus-ratio", "att-idle-ratio",
       "att-switches", "att-input", "attention-timeline",
       "attention-suggestion", "attention-log", "attention-consent",
       "paths-panel", "paths-route", "paths-compare", "paths-callout",
       "att-conn")


class AttentionPanel(unittest.TestCase):
    def test_ids_present_and_safe(self):
        html = open(PANEL, encoding="utf-8").read()
        for i in IDS:
            self.assertIn(f'id="{i}"', html)
        self.assertNotIn("innerHTML", html)       # textContent only
        self.assertNotIn("http://", html.replace("http://127", ""))
        self.assertNotIn("https://", html)        # no external resources
        self.assertIn("narration.log", html)
        self.assertIn("consent.", html)
        self.assertIn("reconnecting", html)       # SSE auto-reconnect
        self.assertIn("scenic route", html)        # detour callout
        dash = os.path.join(os.path.dirname(__file__), "..", "..",
                            "runtime", "src", "runtime", "web", "dashboard.html")
        live = open(dash, encoding="utf-8").read()
        for i in ("paths-panel", "paths-route", "renderPaths"):
            self.assertIn(i, live)


if __name__ == "__main__":
    unittest.main()
