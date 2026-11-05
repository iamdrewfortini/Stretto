# SPDX-License-Identifier: Apache-2.0
"""Consent registry. Default is DENY. A person grants specific sources (screen, camera, audio, glasses, stream) for specific purposes, for a limited time, and can revoke at any moment.
Every grant and revoke is appended to a hash chain so the history is tamper-evident. Isolated: no imports outside the standard library."""
import hashlib, json, math
from copy import deepcopy
from threading import RLock

SOURCES = ("screen", "camera", "audio", "glasses", "stream")
PURPOSES = ("assist", "personal-analytics", "team-analytics", "model-improvement")

def valid_time(value):
    try:
        return type(value) in (int, float) and value >= 0 and math.isfinite(value)
    except OverflowError:
        return False


class Chain:
    def __init__(self, content_check=None):
        self.rows, self.content_check = [], content_check
        self._count, self._head = 0, "0" * 64
    def add(self, **row):
        row = deepcopy(row)
        if len(self.rows) != self._count or (self.rows and self.rows[-1].get('h') != self._head):
            raise ValueError("cannot append to a truncated or altered history")
        prev = self._head; body = json.dumps(dict(row, prev=prev), sort_keys=True, allow_nan=False)
        self._head = hashlib.sha256(body.encode()).hexdigest()
        self.rows.append(dict(row, prev=prev, h=self._head))
        self._count += 1
    def verify(self):
        prev = "0" * 64
        try:
            if len(self.rows) != self._count: return False
            for r in self.rows:
                body = json.dumps({k: v for k, v in r.items() if k != "h"}, sort_keys=True, allow_nan=False)
                if r["prev"] != prev or hashlib.sha256(body.encode()).hexdigest() != r["h"]: return False
                prev = r["h"]
            if prev != self._head: return False
            return self.content_check() if self.content_check else True
        except (KeyError, TypeError, ValueError):
            return False

class ConsentRegistry:
    def __init__(self):
        self.grants, self.chain, self._versions, self._lock = {}, Chain(), {}, RLock()
    def grant(self, person, sources, purposes, ttl_s, now):
        if not isinstance(person, str) or not person.strip():
            raise ValueError("consent requires a person identifier")
        if (not isinstance(sources, (list, tuple, set)) or not sources
                or not isinstance(purposes, (list, tuple, set)) or not purposes):
            raise ValueError("consent requires explicit nonempty scope lists")
        bad = [s for s in sources if s not in SOURCES] + [p for p in purposes if p not in PURPOSES]
        if bad: raise ValueError(f"unknown source or purpose: {bad}")
        if not valid_time(now) or not valid_time(ttl_s) or ttl_s <= 0 or not valid_time(now + ttl_s):
            raise ValueError("consent needs finite valid times and a positive time limit")
        with self._lock:
            version = self._versions.get(person, 0) + 1
            self.chain.add(event="GRANT", person=person, sources=sorted(sources), purposes=sorted(purposes), expires=now + ttl_s, t=now, generation=version)
            self._versions[person] = version
            self.grants[person] = dict(sources=set(sources), purposes=set(purposes), starts=now, expires=now + ttl_s, revoked=False)
    def revoke(self, person, now):
        if not valid_time(now): raise ValueError("revocation needs a finite nonnegative time")
        with self._lock:
            version = self._versions.get(person, 0) + 1
            self.chain.add(event="REVOKE", person=person, t=now, generation=version)
            self._versions[person] = version
            if person in self.grants: self.grants[person]["revoked"] = True
    def allows(self, person, source, purpose, now):
        if not valid_time(now): return False
        with self._lock:
            g = self.grants.get(person)
            return bool(g and not g["revoked"] and g["starts"] <= now < g["expires"]
                        and source in g["sources"] and purpose in g["purposes"])

    def ticket(self, person, source, purpose, now):
        with self._lock:
            return self._versions.get(person) if self.allows(person, source, purpose, now) else None

    def current(self, person, source, purpose, now, generation):
        with self._lock:
            return (generation is not None and self._versions.get(person) == generation
                    and self.allows(person, source, purpose, now))

    def commit(self, person, source, purpose, now, generation, callback):
        """Fence revoke/regrant ABA and serialize the final check with event commit."""
        with self._lock:
            if not self.current(person, source, purpose, now, generation): return False
            callback()
            return True
