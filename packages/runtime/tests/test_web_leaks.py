# SPDX-License-Identifier: Apache-2.0
"""Tests for the leaks page (packages/runtime/web/leaks.html).

Self-contained page consuming the four shared-contract event types over
``EventSource("/v1/events")``. No external scripts, fonts, CSS or images;
all event text via textContent (no non-constant innerHTML); inline SVG
line chart built with createElementNS.
"""
import html.parser
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.normpath(os.path.join(HERE, "..", "web"))
LEAKS = os.path.join(WEB, "leaks.html")

EVENT_TYPES = [
    "leaks.computed",
    "suggestions.ranked",
    "progress.updated",
    "trajectory.forecast",
]


class _Refs(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.script_srcs = []
        self.link_hrefs = []
        self.inline_urls = []
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        a = dict(attrs)
        if tag == "script" and a.get("src"):
            self.script_srcs.append(a["src"])
        if tag == "link" and a.get("href"):
            self.link_hrefs.append(a["href"])
        for v in a.values():
            if isinstance(v, str) and "url(" in v:
                self.inline_urls.append(v)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if "url(" in data:
            self.inline_urls.append(data.strip()[:120])


def non_constant_inner_html(text):
    bad = []
    for m in re.finditer(r"innerHTML\s*=", text):
        rhs = text[m.end():m.end() + 200].lstrip()
        if rhs[:1] in ("'", '"'):
            q = rhs[0]
            i = 1
            while i < len(rhs) and rhs[i] != q:
                i += 2 if rhs[i] == "\\" else 1
            rest = rhs[i + 1:].lstrip()
            if rest[:1] in ("", ";") or rest.startswith("</"):
                continue
        bad.append(text[m.start():m.end() + 60].strip())
    return bad


class LeaksPageT(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.isfile(LEAKS), "leaks.html is missing")
        with open(LEAKS, encoding="utf-8") as f:
            self.text = f.read()

    def test_parses(self):
        p = _Refs()
        p.feed(self.text)  # must not raise
        for t in ("html", "head", "body", "script"):
            self.assertIn(t, p.tags)

    def test_no_external_resources(self):
        p = _Refs()
        p.feed(self.text)
        self.assertEqual(p.script_srcs, [])
        self.assertEqual(p.link_hrefs, [])
        ext = [u for u in p.inline_urls
               if re.search(r"url\(\s*['\"]?https?://", u)]
        self.assertEqual(ext, [])
        self.assertNotRegex(self.text, r"<script[^>]+src\s*=")
        self.assertNotRegex(self.text, r"<link[^>]+href\s*=")
        clean = self.text.replace("http://www.w3.org/2000/svg", "")
        self.assertNotIn("http://", clean)
        self.assertNotIn("https://", clean)

    def test_references_events_and_types(self):
        self.assertIn("/v1/events", self.text)
        self.assertIn("EventSource", self.text)
        for t in EVENT_TYPES:
            self.assertIn(t, self.text)

    def test_no_inner_html_templating(self):
        self.assertEqual(non_constant_inner_html(self.text), [])

    def test_inline_svg_chart(self):
        self.assertTrue(
            "<svg" in self.text or "createElementNS" in self.text,
            "needs inline SVG chart")

    def test_nav_and_sections(self):
        self.assertRegex(self.text, r'href\s*=\s*"/"')
        self.assertRegex(self.text, r'href\s*=\s*"/dashboard"')
        self.assertIn("lower is better", self.text)
        self.assertIn("Assumptions", self.text)

    def test_responsive_and_themed(self):
        self.assertIn("prefers-color-scheme", self.text)
        self.assertIn("--bg", self.text)
        self.assertIn("tabular-nums", self.text)
        self.assertIn("width=device-width", self.text)


if __name__ == "__main__":
    unittest.main()
