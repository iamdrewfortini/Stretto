# SPDX-License-Identifier: Apache-2.0
"""Capture adapters and the event pipeline. A source yields raw frames/audio chunks; every frame is checked against consent, described by an INJECTED model call (so the model can be a Meta
API/gateway model or an on-device one), redacted, turned into a small event and then DROPPED. Raw pixels or audio are never stored and the Event type has no field for them."""
import hashlib, hmac
from .consent import ConsentRegistry, Chain
from .redact import redact

class Event(dict):
    """pseudonym, source, t, app, activity, text (already redacted), duration_s, id. Deliberately no raw media field."""
    FIELDS = ("id", "pseudonym", "source", "t", "app", "activity", "text", "duration_s", "redactions")

def pseudonym(person, person_key): return hmac.new(person_key, person.encode(), hashlib.sha256).hexdigest()[:16]     # key stays with the person/device

class AdaptiveSampler:
    """Decide whether to capture now. Never faster than 1/min_interval_s, never idle longer than max_interval_s, and in between sample when the scene changed (score >= threshold)."""
    def __init__(self, min_interval_s=1.0, max_interval_s=30.0, threshold=0.2): self.lo, self.hi, self.th, self.last = min_interval_s, max_interval_s, threshold, None
    def should_capture(self, now, change):
        if self.last is None or now - self.last >= self.hi or (now - self.last >= self.lo and change >= self.th): self.last = now; return True
        return False

class Source:
    """kind in perception.consent.SOURCES. reader() returns the next raw item or None when the stream ends. Vendor SDKs plug in by supplying a reader; none is bundled."""
    def __init__(self, kind, reader): self.kind, self.reader = kind, reader
    def items(self, registry, person, purpose, now_fn):
        while registry.allows(person, self.kind, purpose, now_fn()):                  # consent is re-checked before EVERY item: revocation takes effect on the next frame
            item = self.reader()
            if item is None: return
            yield item

def ingest(registry, store, person, person_key, source_kind, purpose, raw, describe, now, app="", duration_s=0.0):
    """One raw item -> at most one event. Returns the Event or None (no consent). `raw` goes only to `describe` and is not kept."""
    if not registry.allows(person, source_kind, purpose, now): return None
    d = describe(raw)                                    # {'activity': str, 'text': str}; the model may be remote, so the caller decides which model/gateway this is
    text, counts = redact(d.get("text", ""))
    ev = Event(id=f"e{len(store.events) + 1}", pseudonym=pseudonym(person, person_key), source=source_kind, t=now, app=app, activity=d.get("activity", "other"), text=text, duration_s=duration_s, redactions=counts)
    store.add(ev); return ev

class EventStore:
    def __init__(self): self.events, self.chain = [], Chain()
    def add(self, ev):
        self.events.append(ev); self.chain.add(event="EVENT", id=ev["id"], t=ev["t"], pseudonym=ev["pseudonym"], source=ev["source"], activity=ev["activity"])
