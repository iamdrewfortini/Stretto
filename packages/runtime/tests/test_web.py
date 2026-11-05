# SPDX-License-Identifier: Apache-2.0
"""Tests for the runtime dashboard page (packages/runtime/web/dashboard.html).

The dashboard is one self-contained page: no external scripts, fonts, CSS
or images, an EventSource on /v1/events, a turn form posting to /v1/turn,
and no innerHTML templating of event data (all text goes through
textContent / createTextNode). The same no-external-resources check also
covers voice.html when that file exists.
"""
import html.parser
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.normpath(os.path.join(HERE, "..", "web"))
DASHBOARD = os.path.join(WEB, "dashboard.html")
VOICE = os.path.join(WEB, "voice.html")


class _Refs(html.parser.HTMLParser):
    """Collect script/link references and inline style/url( uses."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.script_srcs = []
        self.link_hrefs = []
        self.inline_urls = []
        self._in_style = False

    def handle_starttag(self, tag, attrs):
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


def external_refs(path):
    """Return external (http/https) references found in an html file."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    p = _Refs()
    p.feed(text)
    ext = [u for u in p.script_srcs + p.link_hrefs if re.match(r"https?://", u.strip())]
    ext += [u for u in p.inline_urls if re.search(r"url\(\s*['\"]?https?://", u)]
    return ext, text


def non_constant_inner_html(text):
    """Find innerHTML assignments whose RHS is not a plain constant string."""
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


class DashboardT(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.isfile(DASHBOARD), "dashboard.html is missing")

    def test_no_external_resources(self):
        ext, _ = external_refs(DASHBOARD)
        self.assertEqual(ext, [], f"dashboard.html must be self-contained, found: {ext}")

    def test_no_script_src_or_link_href(self):
        with open(DASHBOARD, encoding="utf-8") as f:
            text = f.read()
        self.assertNotRegex(text, r"<script[^>]+src\s*=")
        self.assertNotRegex(text, r"<link[^>]+href\s*=")

    def test_references_events_and_turn(self):
        with open(DASHBOARD, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("/v1/events", text)
        self.assertIn("/v1/turn", text)
        self.assertIn("EventSource", text)

    def test_no_inner_html_templating(self):
        with open(DASHBOARD, encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(non_constant_inner_html(text), [])

    def test_links_voice_page(self):
        with open(DASHBOARD, encoding="utf-8") as f:
            text = f.read()
        self.assertRegex(text, r'href\s*=\s*"/"')


class VoiceT(unittest.TestCase):
    def test_no_external_resources_if_present(self):
        if not os.path.isfile(VOICE):
            self.skipTest("voice.html absent")
        ext, _ = external_refs(VOICE)
        self.assertEqual(ext, [], f"voice.html must be self-contained, found: {ext}")


if __name__ == "__main__":
    unittest.main()
