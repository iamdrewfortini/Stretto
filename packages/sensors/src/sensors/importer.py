# SPDX-License-Identifier: Apache-2.0
"""Importer: fixed tick, consent per sample, derive, emit.

Each tick: for every available adapter whose source is consented,
poll (200 ms budget; overruns counted and the sample dropped),
redact titles, feed the episode builder, and queue derived events on
the ingest client. Tick work (excluding adapter subprocess wait, which
adapters report via ``sample.extra['wait_ms']``) is timed into
``tick_ms`` samples; budget is p95 < 5 ms with fixture adapters.
Consent is re-checked every tick from the consent file, so a revoke
stops every adapter of that source on the next tick.
"""
import os
import time
from collections import deque

from .episodes import EpisodeBuilder, categorize
from .metrics import MetricsEngine
from .narration import Narrator
from .redact import clean_title


class Importer:
    def __init__(self, adapters, consent, sink, titles_on=None,
                 hz=1.0, adapter_budget_ms=200.0, idle_threshold_s=120.0,
                 resolver=None, now_fn=time.time):
        self.adapters = list(adapters)   # [(adapter, available, why)]
        self.consent = consent
        self.sink = sink                 # IngestClient or list-like
        self.hz = hz
        self.budget_ms = adapter_budget_ms
        self.titles_on = (os.environ.get("SENSORS_TITLES", "on") != "off"
                          if titles_on is None else titles_on)
        self.builder = EpisodeBuilder(
            idle_threshold_s=idle_threshold_s, resolver=resolver)
        self.metrics = MetricsEngine()
        self.narrator = Narrator()
        self._now = now_fn
        self.tick_ms = deque(maxlen=3600)
        self.overruns = 0
        self._idle_s = 0.0

    def _emit(self, event):
        if hasattr(self.sink, "push"):
            self.sink.push(event)
        else:
            self.sink.append(event)

    def _publish_episode(self, ep, now):
        data = {"app": ep["app"], "category": ep["category"],
                "start": ep["start"], "end": ep["end"],
                "seconds": round(ep["seconds"], 1),
                "idle_s": round(ep.get("idle_s", 0.0), 1),
                "confidence": ep["confidence"]}
        if ep.get("title"):
            data["title"] = ep["title"]
        self._emit({"type": "activity.episode", "data": data})
        line = self.narrator.log_line(ep)
        if line:
            self._emit({"type": "narration.log", "data": {"text": line}})
        led = self.builder.ledger_event(ep)
        if led:
            self._emit({"type": "ledger.event.added", "data": led})

    def tick(self, now=None):
        now = self._now() if now is None else now
        t0 = time.perf_counter()
        wait_ms = 0.0
        window_sample = None
        # One consent snapshot per tick: one file stat, not one per adapter.
        granted = self.consent.state(now=now)
        # The settings titles choice, when set, wins over the startup
        # flag and applies from the next tick like any consent change.
        pref = self.consent.titles_pref() \
            if hasattr(self.consent, "titles_pref") else None
        titles_on = self.titles_on if pref is None else bool(pref)
        for adapter, available, _why in self.adapters:
            if not available:
                continue
            if not granted.get(adapter.source, False):
                continue
            p0 = time.perf_counter()
            try:
                samples = adapter.poll(now)
            except Exception:
                samples = []
            spent = (time.perf_counter() - p0) * 1000.0
            if getattr(adapter, "external_wait", False):
                wait_ms += spent  # OS-tool wait: not tick work
            elif spent > self.budget_ms:
                self.overruns += 1
                continue  # drop late samples; never block the tick
            for s in samples:
                wait_ms += float(s.extra.get("wait_ms", 0.0))
                if s.source == "idle":
                    self._idle_s = s.idle_s
                elif s.source == "window":
                    s.title = clean_title(s.title, True) if titles_on else None
                    window_sample = s
                elif s.source in ("input", "pointer"):
                    self.metrics.note_input(now, s.keys + s.clicks)
                    self._emit({"type": "telemetry.input", "data": {
                        "keys": s.keys, "clicks": s.clicks,
                        "pointer_px": s.pointer_px}})
        if window_sample is not None:
            for ep in self.builder.feed(window_sample, self._idle_s):
                self._publish_episode(ep, now)
        if self.metrics.due(now) and (self.builder.cur or self.builder.closed):
            open_ep = None
            if self.builder.cur:
                open_ep = dict(self.builder.cur)
                # Provisional category only: the resolver's ask is a
                # model call and must never run on the tick path; the
                # real resolution happens once at episode close.
                open_ep["category"] = categorize(
                    open_ep["app"], open_ep.get("title") or "")
            rows = self.metrics.compute(
                self.builder.closed, now, open_episode=open_ep)
            # Bound memory: nothing reads episodes older than the
            # widest window (3600s) plus a small margin.
            cutoff = now - 3660.0
            self.builder.closed = [e for e in self.builder.closed
                                   if e["end"] >= cutoff]
            self.builder.manual_spans = [
                s for s in self.builder.manual_spans if s[1] >= cutoff]
            for row in rows:
                self._emit({"type": "attention.metrics", "data": row})
            m10 = next((r for r in rows if r["window_s"] == 600), None)
            sug = self.narrator.suggest(
                m10, now, self.metrics.in_focus_streak(
                    self.builder.closed, now) or bool(
                    open_ep and open_ep.get("category") == "focus"
                    and now - open_ep["start"] >= 300))
            if sug:
                self._emit(sug)
        if hasattr(self.sink, "flush"):
            self.sink.flush()
        work_ms = (time.perf_counter() - t0) * 1000.0 - wait_ms
        self.tick_ms.append(max(0.0, work_ms))
        return work_ms

    def run(self, stop_fn=None, sleep_fn=time.sleep):
        period = 1.0 / self.hz
        while not (stop_fn and stop_fn()):
            t0 = self._now()
            self.tick(t0)
            sleep_fn(max(0.0, period - (self._now() - t0)))

    def close(self, now=None):
        now = self._now() if now is None else now
        for ep in self.builder.close(now):
            self._publish_episode(ep, now)
