# SPDX-License-Identifier: Apache-2.0
"""Attention metrics over sliding windows. Exact definitions:

For window W seconds ending at ``now``, over closed+open episodes
clipped to the window (idle episodes included with category idle):
- focus_s / idle_s: clipped seconds with category focus / idle.
- focus_ratio = focus_s / W_covered, idle_ratio = idle_s / W_covered,
  where W_covered is total clipped seconds (0 -> ratios 0.0).
- switches: episode boundaries strictly inside the window.
- switches_per_min = switches * 60 / W.
- longest_focus_s: longest clipped continuous focus span.
- mean_episode_s: mean clipped episode seconds (0 when none).
- input_per_min: summed keys+clicks in window * 60 / W (P1; 0 absent).
Metrics are emitted every ``every_s`` (default 10) for windows
60, 600 and 3600 seconds as ``attention.metrics`` events.
"""
WINDOWS = (60, 600, 3600)


class MetricsEngine:
    def __init__(self, windows=WINDOWS, every_s=10.0):
        self.windows = tuple(windows)
        self.every_s = every_s
        self._last_emit = None
        self._inputs = []        # (ts, count)

    def note_input(self, ts, count):
        if count:
            self._inputs.append((float(ts), int(count)))

    def _clip(self, ep, lo, hi):
        s, e = max(ep["start"], lo), min(ep["end"], hi)
        return (e - s) if e > s else 0.0

    def compute(self, episodes, now, open_episode=None):
        eps = list(episodes)
        if open_episode:
            cur = dict(open_episode)
            cur["end"] = float(now)
            cur.setdefault("category", "other")
            eps.append(cur)
        self._inputs = [(t, c) for t, c in self._inputs
                        if t >= now - max(self.windows)]
        out = []
        for w in self.windows:
            lo = now - w
            clipped = [(ep, self._clip(ep, lo, now)) for ep in eps]
            clipped = [(ep, s) for ep, s in clipped if s > 0]
            covered = sum(s for _, s in clipped)
            focus = sum(s for ep, s in clipped
                        if ep.get("category") == "focus")
            idle = sum(s for ep, s in clipped if ep["app"] == "idle")
            bounds = sum(1 for ep, _ in clipped
                         if lo < ep["start"] < now)
            longest, run = 0.0, 0.0
            for ep, s in sorted(clipped, key=lambda x: x[0]["start"]):
                run = run + s if ep.get("category") == "focus" else 0.0
                longest = max(longest, run)
            keys = sum(c for t, c in self._inputs if t >= lo)
            out.append({
                "window_s": w,
                "switches": bounds,
                "switches_per_min": round(bounds * 60.0 / w, 3),
                "focus_ratio": round(focus / covered, 3) if covered else 0.0,
                "idle_ratio": round(idle / covered, 3) if covered else 0.0,
                "longest_focus_s": round(longest, 1),
                "mean_episode_s": round(covered / len(clipped), 1)
                if clipped else 0.0,
                "input_per_min": round(keys * 60.0 / w, 2),
            })
        return out

    def due(self, now):
        if self._last_emit is None or now - self._last_emit >= self.every_s:
            self._last_emit = float(now)
            return True
        return False

    def in_focus_streak(self, episodes, now, min_s=300.0):
        """True when a focus episode has run >= min_s up to now."""
        for ep in reversed(episodes):
            if ep["app"] == "idle" or ep.get("category") != "focus":
                return False
            return (now - ep["start"]) >= min_s
        return False
