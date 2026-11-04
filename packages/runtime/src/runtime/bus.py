# SPDX-License-Identifier: Apache-2.0
"""Event bus: one envelope for every service-to-service message, an append-only JSONL log, in-process subscribers.
Replaying the log rebuilds every projection. Lines are never edited; corrections are new events with causation_id."""
import json, os, threading, time, uuid
from datetime import datetime, timezone


def envelope(type_, data, source, subject="owner", causation_id=None, correlation_id=None):
    return {"id": "evt_" + uuid.uuid4().hex[:20], "type": type_, "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "source": source, "subject": subject, "causation_id": causation_id, "correlation_id": correlation_id,
            "schema": f"{type_}/1", "data": data}


class EventBus:
    def __init__(self, path=None):
        self.path, self._subs, self._lock, self._cond = path, [], threading.Lock(), threading.Condition()
        self._recent, self._seq = [], 0  # (seq, event); seq only grows, so readers never lose their place
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    def subscribe(self, fn, types=None):
        self._subs.append((fn, set(types) if types else None))

    def emit(self, type_, data, source, **kw):
        ev = envelope(type_, data, source, **kw)
        line = json.dumps(ev, separators=(",", ":")) + "\n"
        with self._lock:
            if self.path:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line); f.flush(); os.fsync(f.fileno())
            self._push(ev)
        with self._cond:
            self._cond.notify_all()
        for fn, types in list(self._subs):
            if types is None or type_ in types:
                try:
                    fn(ev)
                except Exception as e:  # a failing subscriber never breaks the producer
                    if type_ != "bus.subscriber_error":
                        self.emit("bus.subscriber_error", {"for": ev["id"], "error": repr(e)[:300]}, "bus")
        return ev

    def _push(self, ev, keep=500):
        self._seq += 1
        self._recent.append((self._seq, ev))
        if len(self._recent) > keep:
            del self._recent[:-keep]

    def seed_recent(self, keep=500):
        """Load the tail of the log so live readers (the dashboard) see history after a restart."""
        tail = list(self.replay())[-keep:]
        with self._lock:
            for ev in tail:
                self._push(ev, keep)

    def since(self, seq):
        """Events with sequence number > seq, and the newest sequence number."""
        with self._lock:
            return [ev for s, ev in self._recent if s > seq], self._seq

    def wait(self, timeout):
        with self._cond:
            self._cond.wait(timeout)

    def replay(self):
        if not self.path or not os.path.exists(self.path):
            return
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)
