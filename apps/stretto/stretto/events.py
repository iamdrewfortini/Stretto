"""Server-sent events: a bounded in-memory broadcaster and a watcher that turns database changes into events.

Events (all JSON, each with a monotonic integer id so a client can resume with Last-Event-ID):
  hello   {server_ts, timer}            first message on every connection
  timer   <the GET /api/timer body>     when a timer starts, stops or changes
  block   <one element of /api/day blocks[]>   when a block of TODAY is new or has changed (the whole block, never a diff)
  day     {date, summary}               when TODAY's totals changed
The stream is only a hint that something changed: a client that misses events refetches, and 15 s polling remains the fallback.
Nothing runs while nobody is connected: the watcher thread exits when the last subscriber leaves."""
import collections
import json
import queue
import threading
import time


class Bus:
    def __init__(self, ring=200, heartbeat_s=15.0, poll_s=1.0):
        self.lock = threading.Lock()
        self.subs = set()
        self.next = 1
        self.ring = collections.deque(maxlen=ring)
        self.heartbeat_s, self.poll_s = heartbeat_s, poll_s
        self.watcher = None

    def publish(self, event, data):
        with self.lock:
            msg = (self.next, event, data)
            self.next += 1
            self.ring.append(msg)
            subs = list(self.subs)
        for q in subs:
            try:
                q.put_nowait(msg)
            except queue.Full:                 # a client that cannot keep up is dropped; it reconnects and refetches
                self.unsubscribe(q)
        return msg[0]

    def subscribe(self, last_id=None):
        """Returns (queue, replay). replay is the list of events after last_id when that id is still in the buffer, else None (send hello)."""
        q = queue.Queue(maxsize=200)
        with self.lock:
            replay = None
            if last_id is not None and self.ring and self.ring[0][0] - 1 <= last_id <= self.next - 1:
                replay = [m for m in self.ring if m[0] > last_id]
            self.subs.add(q)
        return q, replay

    def stamp(self):
        """A fresh id for a message sent to one connection only (hello): not stored, so a reconnect with that id gets a new hello."""
        with self.lock:
            i = self.next
            self.next += 1
            return i

    def unsubscribe(self, q):
        with self.lock:
            self.subs.discard(q)

    def count(self):
        with self.lock:
            return len(self.subs)


def frame(msg):
    i, event, data = msg
    return f"id: {i}\nevent: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n".encode()


def block_view(b):
    return {k: v for k, v in b.items() if k != "key"}


def _sig(b):
    return (b["start"], b["end"], b["seconds"], b["app"], b["domain"], b["category"])


class Watcher(threading.Thread):
    """While anyone is connected, notices new data for TODAY (one cheap index-only query per tick) and publishes what changed."""

    def __init__(self, api, bus, today=None):
        super().__init__(daemon=True)
        self.api, self.bus, self.today = api, bus, today
        self.state = dict(date=None, fp=None, blocks={}, summary=None)

    def _fp(self, date):
        from . import daycache
        a, b = daycache.day_range(date)
        r = self.api.s.q("SELECT COUNT(*) AS n, MAX(id) AS m, ROUND(SUM(dur),1) AS s FROM events WHERE ts>=? AND ts<?", (a, b))[0]
        return (r["n"], r["m"], r["s"])

    def tick(self, quiet=False):
        """Compare today with what was last seen and publish the differences. quiet=True only records the baseline (no events): a client that
        has just connected already gets the current state from hello plus a fetch, so replaying every existing block would be noise."""
        import datetime as dt
        date = self.today() if self.today else dt.date.today().isoformat()
        st = self.state
        fp = self._fp(date)
        if date == st["date"] and fp == st["fp"]:
            return
        day = self.api.day(date)
        blocks = {i: block_view(b) for i, b in enumerate(day["blocks"])}
        new_day = date != st["date"]
        if not quiet:
            old = {} if new_day else st["blocks"]
            for i, b in blocks.items():
                if i not in old or _sig(old[i]) != _sig(b):
                    self.bus.publish("block", b)
            if new_day or day["summary"] != st["summary"]:
                self.bus.publish("day", dict(date=date, summary=day["summary"]))
        st.update(date=date, fp=fp, blocks=blocks, summary=day["summary"])

    def run(self):
        while True:
            time.sleep(self.bus.poll_s)
            if self.bus.count() == 0:
                with self.bus.lock:
                    if not self.bus.subs:            # nobody left: stop, and start fresh (and re-diff) at the next connection
                        self.bus.watcher = None
                        return
            try:
                self.tick()
            except Exception:
                pass                                 # a failed tick must never end the stream; the next tick tries again


def ensure_watcher(api, bus, today=None):
    """Start the watcher if it is not running, with its baseline taken first so nothing that already exists is announced as new."""
    with bus.lock:
        running = bus.watcher is not None and bus.watcher.is_alive()
    if not running:
        w = Watcher(api, bus, today)
        w.tick(quiet=True)
        with bus.lock:
            if bus.watcher is None or not bus.watcher.is_alive():
                bus.watcher = w
                w.start()
