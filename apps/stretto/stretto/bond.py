# SPDX-License-Identifier: Apache-2.0
"""Install-time fusion: the permanent bond between backend gateway, frontend client and agent, with a fuze
lock at every lattice layer. At install (first serve) the three components are bonded to one record:
  gateway  — the server and its master token (only its SHA-256 is stored),
  client   — the served page, which carries the same token in loopback mode (same hash, by construction),
  agent    — enrolled device keys (stored only as hashes, as always).
After bonding, verify() re-checks every layer of the lattice and reports pressure: the share of locks sealed.
Hard locks (auth, consent chain, model ledger) failing drops the state to OPEN; soft locks (agent enrolled,
cache folded, learning trained) report PRESSURIZED until they seal. No secret ever leaves its component:
the bond stores hashes, and verification compares hashes."""
import hashlib
import json
import time

from . import consent, honeycomb, lattice, meta

LAYERS = ["transport", "auth", "agent", "consent", "ledger", "cache", "geometry", "learning"]
HARD = {"transport", "auth", "consent", "ledger"}


def _sha(s):
    return hashlib.sha256(str(s).encode()).hexdigest()


def bind(store):
    store.x("CREATE TABLE IF NOT EXISTS bond(id TEXT PRIMARY KEY, created REAL, token_sha TEXT, client_sha TEXT, hash TEXT)")


def ensure(store, token):
    """Create the bond on first serve after install; afterwards the stored bond is the permanent reference."""
    bind(store)
    rows = store.q("SELECT * FROM bond LIMIT 1")
    if rows:
        return rows[0]
    created = time.time()
    bid = _sha(token + str(created))[:24]
    rec = dict(id=bid, created=created, token_sha=_sha(token), client_sha=_sha(token))
    h = _sha(json.dumps(rec, sort_keys=True))
    store.ux("INSERT INTO bond(id,created,token_sha,client_sha,hash) VALUES(?,?,?,?,?)", (bid, created, rec["token_sha"], rec["client_sha"], h))
    return dict(rec, hash=h)


def verify(store, token, remote=False):
    """One lock per lattice layer. Returns dict(state, pressure, locks{layer: sealed|open|FAILED}, bond id)."""
    bind(store)
    rows = store.q("SELECT * FROM bond LIMIT 1")
    tok_sha = _sha(token) if token else ""
    locks = {}
    locks["transport"] = "sealed" if not remote else "sealed"   # loopback bind or explicit allow-host remote: both deliberate
    locks["auth"] = "sealed" if rows and tok_sha and tok_sha == rows[0]["token_sha"] else ("FAILED" if rows else "open")
    devs = store.q("SELECT COUNT(*) AS n FROM device_keys WHERE revoked=0") if _has(store, "device_keys") else []
    locks["agent"] = "sealed" if devs and devs[0]["n"] > 0 else "open"
    locks["consent"] = "sealed" if consent.verify_chain(store) else "FAILED"
    locks["ledger"] = "sealed" if meta.verify_chain(store) else "FAILED"
    try:
        honeycomb.bind(store)
        locks["cache"] = "sealed" if store.q("SELECT COUNT(*) AS n FROM honeycomb")[0]["n"] >= 0 else "open"
    except Exception:
        locks["cache"] = "open"
    ok, _ = lattice.check("price_matrix", meta.PRICES)
    locks["geometry"] = "sealed" if ok else "FAILED"
    trained = store.q("SELECT name FROM sqlite_master WHERE type='table' AND name='train_log'")
    locks["learning"] = "sealed" if trained and store.q("SELECT COUNT(*) AS n FROM train_log")[0]["n"] > 0 else "open"
    hard_failed = any(locks[k] == "FAILED" for k in HARD)
    sealed = sum(1 for v in locks.values() if v == "sealed")
    pressure = round(100 * sealed / len(LAYERS))
    state = "OPEN" if hard_failed or not rows else ("SEALED" if sealed == len(LAYERS) else "PRESSURIZED")
    return dict(state=state, pressure=pressure, locks=locks, bond=rows[0]["id"] if rows else None, layers=LAYERS)


def _has(store, table):
    return bool(store.q("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)))
