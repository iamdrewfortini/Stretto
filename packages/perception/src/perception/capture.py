# SPDX-License-Identifier: Apache-2.0
"""Capture adapters and the event pipeline. A source yields raw frames/audio chunks; every frame is checked against consent, described by an INJECTED model call (so the model can be a Meta
API/gateway model or an on-device one), redacted, turned into a small event and then DROPPED. Raw pixels or audio are never stored and the Event type has no field for them."""
import hashlib, hmac, json, re, time
from copy import deepcopy
from threading import RLock
from .consent import ConsentRegistry, Chain, SOURCES, valid_time
from .redact import redact

class Event(dict):
    """pseudonym, source, t, app, activity, text (already redacted), duration_s, id. Deliberately no raw media field."""
    FIELDS = ("id", "pseudonym", "source", "t", "app", "activity", "text", "duration_s", "redactions")

    def __init__(self, *args, **kwargs):
        value = dict(*args, **kwargs)
        if set(value) != set(self.FIELDS): raise ValueError("event fields do not match the closed schema")
        for name in ("id", "pseudonym", "source", "app", "activity", "text"):
            text = value[name]
            if (not isinstance(text, str) or len(text) > 65536
                    or re.search(r"data:(?:image|audio|video)/", text, re.I)):
                raise ValueError("event fields must be bounded text without embedded media")
        if any(not value[name].strip() for name in ("id", "pseudonym", "source", "activity")):
            raise ValueError("event identifiers, source and activity must be nonempty")
        if value['source'] not in SOURCES or not valid_time(value['t']) or not valid_time(value['duration_s']):
            raise ValueError("invalid event source or times")
        counts = value['redactions']
        categories = {'EMAIL', 'API_KEY', 'SSN', 'IPV4', 'PHONE', 'CARD'}
        if (not isinstance(counts, dict) or any(k not in categories or type(v) is not int or v < 0
                                               for k, v in counts.items())):
            raise ValueError("event redactions must be nonnegative integer counts")
        super().__init__(deepcopy(value))

    def _frozen(self, *args, **kwargs): raise TypeError("events are immutable snapshots")
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _frozen

    def __deepcopy__(self, memo): return Event(deepcopy(dict(self), memo))

def pseudonym(person, person_key): return hmac.new(person_key, person.encode(), hashlib.sha256).hexdigest()[:16]     # key stays with the person/device

class AdaptiveSampler:
    """Decide whether to capture now. Never faster than 1/min_interval_s, never idle longer than max_interval_s, and in between sample when the scene changed (score >= threshold)."""
    def __init__(self, min_interval_s=1.0, max_interval_s=30.0, threshold=0.2):
        if (not valid_time(min_interval_s) or min_interval_s <= 0 or not valid_time(max_interval_s)
                or max_interval_s < min_interval_s or not valid_time(threshold)):
            raise ValueError("sampler requires finite ordered positive intervals and nonnegative threshold")
        self.lo, self.hi, self.th, self.last = min_interval_s, max_interval_s, threshold, None
    def should_capture(self, now, change):
        if not valid_time(now) or not valid_time(change) or (self.last is not None and now < self.last):
            raise ValueError("sampler requires finite nonnegative monotonic inputs")
        if self.last is None or now - self.last >= self.hi or (now - self.last >= self.lo and change >= self.th): self.last = now; return True
        return False

class Source:
    """kind in perception.consent.SOURCES. reader() returns the next raw item or None when the stream ends. Vendor SDKs plug in by supplying a reader; none is bundled."""
    def __init__(self, kind, reader):
        if kind not in SOURCES or not callable(reader): raise ValueError("invalid source or reader")
        self.kind, self.reader = kind, reader
    def items(self, registry, person, purpose, now_fn):
        while True:
            generation = registry.ticket(person, self.kind, purpose, now_fn())
            if generation is None: return
            item = self.reader()
            if item is None: return
            if not registry.current(person, self.kind, purpose, now_fn(), generation): return
            yield item

def ingest(registry, store, person, person_key, source_kind, purpose, raw, describe, now, app="", duration_s=0.0, *, now_fn=None):
    """One raw item -> at most one event. Returns the Event or None (no consent). `raw` goes only to `describe` and is not kept."""
    generation = registry.ticket(person, source_kind, purpose, now)
    if generation is None: return None
    started = time.monotonic()
    d = describe(raw)                                    # {'activity': str, 'text': str}; the model may be remote, so the caller decides which model/gateway this is
    if not isinstance(d, dict) or set(d) - {'activity', 'text'}:
        raise ValueError("description contains unsupported fields")
    if any(not isinstance(d.get(name, ''), str) for name in ('activity', 'text')) or not isinstance(app, str):
        raise ValueError("description and app metadata must be text")
    text, counts = redact(d.get("text", ""))
    activity, activity_counts = redact(d.get('activity', 'other'))
    app, app_counts = redact(app)
    for extra in (activity_counts, app_counts):
        for key, value in extra.items(): counts[key] = counts.get(key, 0) + value
    ev = Event(id=store.next_id(), pseudonym=pseudonym(person, person_key), source=source_kind, t=now, app=app, activity=activity, text=text, duration_s=duration_s, redactions=counts)
    current_time = now_fn() if now_fn is not None else now + (time.monotonic() - started)
    if not registry.commit(person, source_kind, purpose, current_time, generation, lambda: store.add(ev)):
        return None
    return ev

class EventStore:
    def __init__(self):
        self._events, self._lock, self._sequence = [], RLock(), 0
        self.chain = Chain(content_check=self._content_intact)

    @property
    def events(self):
        """Detached snapshots for inspection; changes to this view are not stored."""
        with self._lock: return deepcopy(self._events)

    def next_id(self):
        with self._lock:
            self._sequence += 1
            return f'e{self._sequence}'

    def _content_intact(self):
        with self._lock:
            if len(self._events) != len(self.chain.rows): return False
            for row, event in zip(self.chain.rows, self._events):
                Event(event)
                if (json.dumps(row.get('payload'), sort_keys=True, allow_nan=False)
                        != json.dumps(event, sort_keys=True, allow_nan=False)):
                    return False
            return True

    def verify(self):
        with self._lock: return self.chain.verify()

    def add(self, ev):
        if type(ev) is not Event: raise ValueError("store accepts schema-validated Event instances only")
        snapshot = deepcopy(dict(ev))
        Event(snapshot)  # Revalidate even if a caller bypassed the Event mutation guard.
        with self._lock:
            if any(old['id'] == ev['id'] for old in self._events): raise ValueError("duplicate event identifier")
            self.chain.add(event="EVENT", payload=snapshot)
            self._events.append(snapshot)
