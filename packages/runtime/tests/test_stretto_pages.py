# SPDX-License-Identifier: Apache-2.0
"""Stretto Talk and Leaks pages: registered in app.js, kit-built, no raw HTML
assembly and no absolute web URLs. Pure file reads; never touches the network.
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
STRETTO = os.path.normpath(os.path.join(HERE, "..", "..", "..", "apps", "stretto", "stretto", "static"))
PAGES = os.path.join(STRETTO, "js", "pages")
APP = os.path.join(STRETTO, "js", "app.js")

TALK = os.path.join(PAGES, "talk.js")
LEAKS = os.path.join(PAGES, "leaks.js")

EVENT_TYPES = [
    "leaks.computed",
    "suggestions.ranked",
    "progress.updated",
    "trajectory.forecast",
]

PROTO = "http" + "s?://"


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


class StrettoPagesT(unittest.TestCase):
    def test_files_exist(self):
        for p in (TALK, LEAKS, APP):
            self.assertTrue(os.path.isfile(p), p + " is missing")

    def test_registered_in_app(self):
        with open(APP, encoding="utf-8") as f:
            app = f.read()
        self.assertRegex(app, r"import\s+talk\s+from\s+'\./pages/talk\.js'")
        self.assertRegex(app, r"import\s+leaks\s+from\s+'\./pages/leaks\.js'")
        m = re.search(r"const PAGES = \[(.*?)\];", app, re.S)
        self.assertIsNotNone(m, "PAGES list not found")
        names = [n.strip() for n in m.group(1).split(",")]
        self.assertIn("talk", names)
        self.assertIn("leaks", names)
        self.assertEqual(names[0], "talk", "Talk must be first in the nav")
        self.assertEqual(names.index("leaks"), names.index("insights") + 1,
                         "Leaks must sit next to Insights")

    def test_no_inner_html(self):
        for p in (TALK, LEAKS):
            with open(p, encoding="utf-8") as f:
                text = f.read()
            self.assertEqual(non_constant_inner_html(text), [],
                             p + " assigns innerHTML")

    def test_no_absolute_urls(self):
        for p in (TALK, LEAKS):
            with open(p, encoding="utf-8") as f:
                text = f.read()
            clean = text.replace("www.w3.org", "")
            self.assertNotRegex(clean, PROTO, p + " has an absolute URL")

    def test_talk_behaviour(self):
        with open(TALK, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("ws://127.0.0.1:8788/", text)
        self.assertIn("/v1/turn", text)
        self.assertIn("getUserMedia", text)
        self.assertIn("AudioWorklet", text)
        self.assertIn("speechSynthesis", text)
        for t in ("ready", "partial", "final", "reply", "error"):
            self.assertTrue(("'%s'" % t) in text or ('"%s"' % t) in text,
                            "talk.js never handles " + t)

    def test_leaks_behaviour(self):
        with open(LEAKS, encoding="utf-8") as f:
            text = f.read()
        hits = [t for t in EVENT_TYPES if t in text]
        self.assertTrue(len(hits) == len(EVENT_TYPES) or "/api/insights" in text,
                        "leaks.js needs the four event names or /api/insights")
        self.assertIn("/api/insights", text)
        self.assertIn("/v1/events", text)


if __name__ == "__main__":
    unittest.main()


class ImportsResolve(unittest.TestCase):
    """A relative import that points at a missing file or a missing export stops the whole app in the browser."""
    def test_every_relative_import_resolves(self):
        import re
        root = os.path.join(STRETTO, "js")

        def exports(path):
            s = open(path, encoding="utf-8").read()
            names = set(re.findall(r"export\s+(?:async\s+)?(?:function|const|let|class)\s+(\w+)", s))
            for grp in re.findall(r"export\s*\{([^}]*)\}", s):
                names |= {x.split(" as ")[-1].strip() for x in grp.split(",") if x.strip()}
            if re.search(r"export\s+default", s):
                names.add("default")
            return names
        problems = []
        for dp, _, fs in os.walk(root):
            for f in fs:
                if not f.endswith(".js"):
                    continue
                p = os.path.join(dp, f); s = open(p, encoding="utf-8").read()
                for names, mod in re.findall(r"import\s+(.+?)\s+from\s+[\x27\"](\.[^\x27\"]+)[\x27\"]", s):
                    t = os.path.normpath(os.path.join(dp, mod))
                    if not os.path.exists(t):
                        problems.append(f"{os.path.relpath(p, root)}: missing module {mod}"); continue
                    m = re.search(r"\{([^}]*)\}", names)
                    want = [x.split(" as ")[0].strip() for x in m.group(1).split(",") if x.strip()] if m else []
                    if re.match(r"^\s*\w+\s*(,|$)", names):
                        want.append("default")
                    problems += [f"{os.path.relpath(p, root)}: {mod} has no export {w}" for w in want if w not in exports(t)]
        self.assertEqual(problems, [])
