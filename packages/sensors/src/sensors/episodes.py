# SPDX-License-Identifier: Apache-2.0
"""Episodes and app categorisation. Deterministic; no model on tick.

Definitions (exact; tests pin them):
- An episode is a maximal run of window samples with the same
  (app, title-or-None). A sample with idle_s >= idle_threshold_s
  (default 120) closes the current episode and belongs to an ``idle``
  episode until a non-idle window sample arrives.
- Episode seconds = end - start where start/end are the first/last
  sample timestamps of the run, plus the final tick interval supplied
  by the importer via ``close(now)``.
- confidence is 1.0 when the app was seen on >= 3 samples, else
  samples/3 rounded to 2dp. A ledger event needs seconds >= 60 and
  confidence >= 0.7.
Categories mirror ``humanflow.personal.CATEGORIES``:
focus, meeting, comms, search, wait, admin, other.
"""
import os

CATEGORIES = ("focus", "meeting", "comms", "search", "wait", "admin", "other")

_FOCUS = ("code", "visual studio", "intellij", "pycharm", "xcode",
          "terminal", "iterm", "vim", "emacs", "sublime", "zed")
_MEETING = ("zoom", "meet", "teams", "facetime", "webex", "skype")
_COMMS = ("slack", "mail", "messages", "discord", "telegram", "outlook")
_BROWSER = ("safari", "chrome", "firefox", "arc", "edge", "brave")
_SEARCH_HINTS = ("google", "bing", "duckduckgo", "search", "stackoverflow")


def categorize(app, title=""):
    """Local rules first. Returns a CATEGORIES member."""
    a, t = (app or "").lower(), (title or "").lower()
    if any(k in a for k in _MEETING):
        return "meeting"
    if any(k in a for k in _COMMS):
        return "comms"
    if any(k in a for k in _FOCUS):
        return "focus"
    if any(k in a for k in _BROWSER):
        return "search" if any(h in t for h in _SEARCH_HINTS) else "other"
    if "finder" in a or "settings" in a or "installer" in a:
        return "admin"
    if "waiting" in t or "loading" in t:
        return "wait"
    return "other"


class CategoryResolver:
    """Local rules, then an injected one-shot ask, cached forever.

    The ask callable is the ONLY model path in this package (gateway
    role ``agent.background`` when wired by the runtime). It is never
    called on the tick path: resolution happens once per unknown app
    at episode close, and the result is cached on disk forever.
    """

    def __init__(self, cache_path=None, ask=None):
        self.ask = ask
        self.cache_path = cache_path
        self.cache = {}
        if cache_path and os.path.exists(cache_path):
            try:
                import json
                self.cache = json.load(open(cache_path, encoding="utf-8"))
            except (OSError, ValueError):
                self.cache = {}

    def resolve(self, app, title=""):
        cat = categorize(app, title)
        if cat != "other" or not app:
            return cat
        if app in self.cache:
            return self.cache[app]
        if self.ask is None:
            return "other"
        try:
            got = self.ask(app)
        except Exception:
            got = None
        cat = got if got in CATEGORIES else "other"
        self.cache[app] = cat
        if self.cache_path:
            try:
                import json
                with open(self.cache_path, "w", encoding="utf-8") as f:
                    json.dump(self.cache, f, sort_keys=True)
            except OSError:
                pass
        return cat


class EpisodeBuilder:
    def __init__(self, idle_threshold_s=120.0, resolver=None,
                 ledger_min_s=60.0, ledger_min_conf=0.7):
        self.idle_threshold_s = idle_threshold_s
        self.resolver = resolver or CategoryResolver()
        self.ledger_min_s = ledger_min_s
        self.ledger_min_conf = ledger_min_conf
        self.cur = None          # open episode dict
        self.closed = []         # finished episode dicts
        self.manual_spans = []   # (start, end) seen non-auto ledger spans

    def note_manual_span(self, start, end):
        self.manual_spans.append((float(start), float(end)))

    def _close(self, end):
        if not self.cur:
            return None
        ep, self.cur = self.cur, None
        ep["end"] = float(end)
        ep["seconds"] = max(0.0, ep["end"] - ep["start"])
        ep["confidence"] = 1.0 if ep["samples"] >= 3 else round(
            ep["samples"] / 3.0, 2)
        ep["category"] = ("idle" if ep["app"] == "idle" else
                          self.resolver.resolve(ep["app"], ep.get("title") or ""))
        self.closed.append(ep)
        return ep

    def feed(self, sample, idle_s=0.0):
        """Feed one window sample. Returns newly closed episodes."""
        out = []
        idle = idle_s >= self.idle_threshold_s
        app = "idle" if idle else (sample.app or "")
        title = None if idle else sample.title
        key = (app, title)
        if self.cur and self.cur["key"] != key:
            out.append(self._close(sample.ts))
        if not self.cur:
            self.cur = {"key": key, "app": app, "title": title,
                        "start": float(sample.ts), "samples": 0, "idle_s": 0.0}
        self.cur["samples"] += 1
        if idle:
            self.cur["idle_s"] = max(self.cur["idle_s"], float(idle_s))
        return [e for e in out if e]

    def close(self, now):
        ep = self._close(now)
        return [ep] if ep else []

    def ledger_event(self, ep):
        """Ledger dict for an episode, or None (threshold/dup rules)."""
        if ep["app"] == "idle" or ep["seconds"] < self.ledger_min_s:
            return None
        if ep["confidence"] < self.ledger_min_conf:
            return None
        for s, e in self.manual_spans:
            if ep["start"] < e and s < ep["end"]:
                return None  # never duplicate a manual entry's span
        return {"t": ep["start"],
                "activity": ep["category"] if ep["category"] in CATEGORIES
                else "other",
                "duration_s": ep["seconds"],
                "text": f"auto:{ep['app']}", "origin": "auto"}
