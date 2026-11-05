# SPDX-License-Identifier: Apache-2.0
"""Narration: one measured line per episode, sparse suggestions.

- ``narration.log {text}``: "14:05 VS Code, 22 min focus" per closed
  episode (idle episodes narrated only when >= 5 min).
- ``narration.suggestion {text, evidence}``: at most once per 5 min,
  never while a focus streak is running, rule-based, and every line
  cites the number it used. No model call is required; an optional
  phrasing callable (P1, gateway) must keep numbers unchanged and is
  rejected if it alters any digit sequence.
"""
import re
import time

SWITCH_THRESHOLD = 1.0       # switches/min over the 10-min window


def _hhmm(ts):
    lt = time.localtime(ts)
    return f"{lt.tm_hour:02d}:{lt.tm_min:02d}"


def _dur(seconds):
    m = int(round(seconds / 60.0))
    return f"{m} min" if m >= 1 else f"{int(seconds)} s"


def rank_suggestions(candidates):
    """Owner ranking rule (spec, 2026-11-04): largest time won back
    per cost to adopt first. A candidate without BOTH numbers is
    never shown. Cost is minutes of effort plus money (money folded
    in by the caller as adopt_cost_min equivalents)."""
    ok = [c for c in candidates
          if c.get("won_back_min_week") is not None
          and c.get("adopt_cost_min")]
    return sorted(ok, key=lambda c: c["won_back_min_week"]
                  / c["adopt_cost_min"], reverse=True)


class Narrator:
    def __init__(self, suggestion_gap_s=300.0, phrase=None,
                 switch_cost_s=None, adopt_cost_min=5.0):
        self.gap = suggestion_gap_s
        self.phrase = phrase
        self.switch_cost_s = switch_cost_s  # owner-calibrated; None = uncalibrated
        self.adopt_cost_min = adopt_cost_min
        self._last_suggestion = None

    def log_line(self, ep):
        if ep["app"] == "idle":
            if ep["seconds"] < 300:
                return None
            return f"{_hhmm(ep['start'])} idle, {_dur(ep['seconds'])}"
        return (f"{_hhmm(ep['start'])} {ep['app']}, "
                f"{_dur(ep['seconds'])} {ep['category']}")

    def _maybe_phrase(self, text, evidence):
        if self.phrase is None:
            return text
        try:
            got = self.phrase(text, evidence)
        except Exception:
            return text
        if got and re.findall(r"\d+(?:\.\d+)?", got) == \
                re.findall(r"\d+(?:\.\d+)?", text):
            return got
        return text

    def suggest(self, metrics10, now, in_streak):
        """Suggestion event dict or None. metrics10 is the 600s row."""
        if in_streak or metrics10 is None:
            return None
        if self._last_suggestion is not None and \
                now - self._last_suggestion < self.gap:
            return None
        spm = metrics10["switches_per_min"]
        if spm > SWITCH_THRESHOLD:
            if self.switch_cost_s is None:
                return None  # uncalibrated: no won-back number, no show
            won_min_week = round(metrics10["switches"] * 6 * 5
                                 * self.switch_cost_s / 60.0, 1)
            cand = {"won_back_min_week": won_min_week,
                    "adopt_cost_min": self.adopt_cost_min}
            if not rank_suggestions([cand]):
                return None
            text = (f"{metrics10['switches']} switches in 10 min; "
                    "mute comms for 25 min?")
            ev = {"type": "narration.suggestion", "data": {
                "text": self._maybe_phrase(text, f"switches={metrics10['switches']}"),
                "evidence": f"switches_per_min={spm} over 600s",
                "won_back_min_week": won_min_week,
                "adopt_cost_min": self.adopt_cost_min,
                "rank_score": round(won_min_week / self.adopt_cost_min, 2)}}
            self._last_suggestion = float(now)
            return ev
        # Idle branch: no calibrated won-back number exists for it, so
        # the both-numbers rule suppresses it like any uncalibrated
        # suggestion. Never emit a suggestion without both numbers.
        return None
