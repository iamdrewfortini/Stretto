# SPDX-License-Identifier: Apache-2.0
"""Loopback ingest client for POST /v1/ingest.

Local only: the gateway URL must resolve to 127.0.0.1 or localhost;
anything else is refused at construction. Events queue in memory,
flush in batches of at most 200 every ``flush_s`` (default 2s), retry
with exponential backoff (1s, 2s, 4s ... capped 30s), and drop events
older than ``buffer_s`` (default 600s = 10 min) oldest-first. Sending
never blocks the importer tick: ``flush`` is called from the tick
loop but does a single bounded attempt per call.
"""
import json
import socket
import time
import urllib.request
from collections import deque
from urllib.parse import urlparse

ALLOWED_PREFIXES = ("telemetry.", "activity.", "attention.",
                    "narration.", "consent.")


def check_event(ev):
    t = ev.get("type", "")
    if t.startswith(ALLOWED_PREFIXES):
        return True
    return t == "ledger.event.added" and \
        ev.get("data", {}).get("origin") == "auto"


class IngestClient:
    def __init__(self, gateway, source_host=None, flush_s=2.0,
                 buffer_s=600.0, max_batch=200, opener=None,
                 now_fn=time.time):
        host = urlparse(gateway).hostname or ""
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError(f"gateway must be loopback, got {host!r}")
        self.gateway = gateway.rstrip("/")
        self.source_host = source_host or socket.gethostname()
        self.flush_s, self.buffer_s = flush_s, buffer_s
        self.max_batch = max_batch
        self._opener = opener or urllib.request.urlopen
        self._now = now_fn
        self.queue = deque()     # (queued_ts, event)
        self._last_flush = 0.0
        self._backoff_until = 0.0
        self._failures = 0
        self.sent = 0
        self.dropped = 0

    def push(self, event):
        if not check_event(event):
            raise ValueError(f"event type not accepted: {event.get('type')}")
        self.queue.append((self._now(), event))
        self._prune()

    def _prune(self):
        cutoff = self._now() - self.buffer_s
        while self.queue and self.queue[0][0] < cutoff:
            self.queue.popleft()
            self.dropped += 1

    def flush(self, force=False):
        """One bounded send attempt. Returns accepted count."""
        now = self._now()
        self._prune()
        if not self.queue:
            return 0
        if not force and (now - self._last_flush < self.flush_s
                          or now < self._backoff_until):
            return 0
        self._last_flush = now
        batch = [e for _, e in list(self.queue)[:self.max_batch]]
        body = json.dumps({"source_host": self.source_host,
                           "events": batch}).encode()
        req = urllib.request.Request(
            self.gateway + "/v1/ingest", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with self._opener(req, timeout=2) as resp:
                accepted = json.loads(resp.read()).get("accepted", 0)
        except Exception:
            self._failures += 1
            self._backoff_until = now + min(30.0, 2 ** (self._failures - 1))
            return 0
        # Drop only what the gateway accepted; a partial accept keeps
        # the rest queued for the next attempt instead of losing it.
        for _ in range(min(accepted, len(batch))):
            self.queue.popleft()
        self._failures = 0
        self.sent += accepted
        return accepted
