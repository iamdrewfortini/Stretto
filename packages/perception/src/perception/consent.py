# SPDX-License-Identifier: Apache-2.0
"""Consent registry. Default is DENY. A person grants specific sources (screen, camera, audio, glasses, stream) for specific purposes, for a limited time, and can revoke at any moment.
Every grant and revoke is appended to a hash chain so the history is tamper-evident. Isolated: no imports outside the standard library."""
import hashlib, json

SOURCES = ("screen", "camera", "audio", "glasses", "stream")
PURPOSES = ("assist", "personal-analytics", "team-analytics", "model-improvement")

class Chain:
    def __init__(self): self.rows = []
    def add(self, **row):
        prev = self.rows[-1]["h"] if self.rows else "0" * 64; body = json.dumps(dict(row, prev=prev), sort_keys=True, default=str)
        self.rows.append(dict(row, prev=prev, h=hashlib.sha256(body.encode()).hexdigest()))
    def verify(self):
        prev = "0" * 64
        for r in self.rows:
            body = json.dumps({k: v for k, v in r.items() if k != "h"}, sort_keys=True, default=str)
            if r["prev"] != prev or hashlib.sha256(body.encode()).hexdigest() != r["h"]: return False
            prev = r["h"]
        return True

class ConsentRegistry:
    def __init__(self): self.grants, self.chain = {}, Chain()
    def grant(self, person, sources, purposes, ttl_s, now):
        bad = [s for s in sources if s not in SOURCES] + [p for p in purposes if p not in PURPOSES]
        if bad: raise ValueError(f"unknown source or purpose: {bad}")
        if ttl_s <= 0: raise ValueError("consent needs a positive time limit")
        self.grants[person] = dict(sources=set(sources), purposes=set(purposes), expires=now + ttl_s, revoked=False); self.chain.add(event="GRANT", person=person, sources=sorted(sources), purposes=sorted(purposes), expires=now + ttl_s, t=now)
    def revoke(self, person, now):
        if person in self.grants: self.grants[person]["revoked"] = True
        self.chain.add(event="REVOKE", person=person, t=now)
    def allows(self, person, source, purpose, now):
        g = self.grants.get(person)
        return bool(g and not g["revoked"] and now < g["expires"] and source in g["sources"] and purpose in g["purposes"])
