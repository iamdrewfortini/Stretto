# SPDX-License-Identifier: Apache-2.0
"""Consent for sensor sources. Default-deny, file-backed, owner-only.

Sources are ``window``, ``input``, ``pointer`` and ``idle``. This module
extends the source vocabulary of ``perception.consent`` without editing
that package: the on-disk grant shape mirrors
``ConsentRegistry.grant/revoke/allows(person, source, purpose, now)``
semantics (positive TTL required, revoke is immediate). Grants live in
``~/.config/humanflow/consent.json`` with mode 0600. The running agent
re-reads the file every tick, so a revoke lands within one tick.
"""
import json
import os
import time

SOURCES = ("window", "input", "pointer", "idle")
DEFAULT_PATH = os.path.expanduser("~/.config/humanflow/consent.json")


def _now():
    return time.time()


class ConsentStore:
    """JSON-file consent store. ``allows`` never raises on bad files."""

    def __init__(self, path=None, person="owner"):
        self.path = path or os.environ.get(
            "SENSORS_CONSENT", DEFAULT_PATH)
        self.person = person
        self._grants = {}
        self._mtime = None
        self.reload(force=True)

    # persistence --------------------------------------------------
    def _write(self):
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = self.path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, json.dumps(
                {"grants": self._grants}, sort_keys=True).encode())
        finally:
            os.close(fd)
        os.replace(tmp, self.path)
        os.chmod(self.path, 0o600)
        self._mtime = os.stat(self.path).st_mtime

    def reload(self, force=False):
        try:
            m = os.stat(self.path).st_mtime
        except OSError:
            if force:
                self._grants, self._mtime = {}, None
            return
        if not force and m == self._mtime:
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                self._grants = json.load(f).get("grants", {})
        except (OSError, ValueError):
            self._grants = {}
        self._mtime = m

    # API (mirrors perception.consent.ConsentRegistry) --------------
    def grant(self, sources, ttl_s, now=None, person=None):
        bad = [s for s in sources if s not in SOURCES]
        if bad:
            raise ValueError(f"unknown sensor source: {bad}")
        if ttl_s <= 0:
            raise ValueError("consent needs a positive time limit")
        now = _now() if now is None else now
        person = person or self.person
        g = self._grants.setdefault(
            person, {"sources": {}, "revoked": False})
        g["revoked"] = False
        for s in sources:
            g["sources"][s] = now + ttl_s
        self._write()
        return {"type": "consent.changed", "data": {
            "person": person, "action": "grant",
            "sources": sorted(sources), "expires": now + ttl_s}}

    def revoke(self, sources=None, now=None, person=None):
        person = person or self.person
        g = self._grants.setdefault(
            person, {"sources": {}, "revoked": False})
        if sources:
            bad = [s for s in sources if s not in SOURCES]
            if bad:
                raise ValueError(f"unknown sensor source: {bad}")
            for s in sources:
                g["sources"].pop(s, None)
        else:
            g["sources"] = {}
            g["revoked"] = True
        self._write()
        return {"type": "consent.changed", "data": {
            "person": person, "action": "revoke",
            "sources": sorted(sources or SOURCES)}}

    def _allows(self, source, now, person):
        g = self._grants.get(person or self.person)
        if not g or g.get("revoked"):
            return False
        exp = g.get("sources", {}).get(source)
        return bool(exp and now < exp)

    def allows(self, source, now=None, person=None):
        self.reload()
        return self._allows(source, _now() if now is None else now, person)

    def state(self, now=None, person=None):
        self.reload()
        now = _now() if now is None else now
        return {s: self._allows(s, now, person) for s in SOURCES}


def parse_ttl(text):
    """Parse '8h', '30m', '3600s' or bare seconds into seconds."""
    text = str(text).strip().lower()
    mult = {"h": 3600, "m": 60, "s": 1}
    if text and text[-1] in mult:
        return int(float(text[:-1]) * mult[text[-1]])
    return int(float(text))
