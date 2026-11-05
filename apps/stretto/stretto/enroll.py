# SPDX-License-Identifier: Apache-2.0
"""Device enrolment. The master token never leaves the server's machine; an agent gets its own key.

  1. A signed-in person (admin token) asks for an enrolment code: single use, expires in 15 minutes.
  2. The installer sends the code to /api/agent/register and receives a device key, shown once and stored only as a hash.
  3. From then on the agent proves itself with that key. A device key can send data for ITS OWN device, read its own cursor and
     consent state, and revoke consent. It cannot read the user's data, accept a notice, enrol another device or change settings.
  4. Revoking a device invalidates its key at once."""
import hashlib
import hmac
import secrets
import time

CODE_TTL_S = 900


def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()


def new_code(store, ttl=CODE_TTL_S):
    code = secrets.token_urlsafe(9)
    now = time.time()
    store.x("DELETE FROM enroll_codes WHERE expires < ?", (now - 86400,))       # tidy old rows
    store.x("INSERT INTO enroll_codes(code_hash,created,expires) VALUES(?,?,?)", (_h(code), now, now + ttl))
    return code, now + ttl


def register(store, code, device, name):
    """Exchange a valid, unused, unexpired code for a device key. The code is burned even if the device id is later rejected."""
    device = str(device).strip()[:60]
    if not device or not all(c.isalnum() or c in "-_." for c in device):
        raise ValueError("a device id of letters, digits, - _ . is required")
    row = store.q("SELECT * FROM enroll_codes WHERE code_hash=?", (_h(str(code)),))
    if not row or row[0]["used"] or row[0]["expires"] < time.time():
        time.sleep(0.4)                                                           # slow down guessing
        raise PermissionError("invalid or expired enrolment code")
    store.x("UPDATE enroll_codes SET used=1 WHERE code_hash=?", (_h(str(code)),))
    if store.q("SELECT 1 FROM device_keys WHERE device=? AND revoked=0", (device,)):
        raise ValueError("this device is already enrolled; revoke it first to enrol again")
    key = secrets.token_urlsafe(32)
    store.ux("INSERT OR REPLACE INTO device_keys(device,name,key_hash,created,revoked) VALUES(?,?,?,?,0)", (device, str(name)[:60], _h(key), time.time()))
    store.touch_device(device, name)
    return key


def device_for_key(store, key):
    """The device id a key belongs to, or None. Revoked keys never match."""
    if not key:
        return None
    for r in store.q("SELECT device, key_hash FROM device_keys WHERE key_hash=? AND revoked=0", (_h(key),)):
        if hmac.compare_digest(r["key_hash"], _h(key)):
            return r["device"]
    return None


_ITEM_KEYS = {"id": 60, "source": 40, "label": 160, "why": 400, "status": 20, "note": 400}
_STATUSES = {"granted", "missing", "unknown", "unsupported", "not_applicable"}


def clean_plan(plan):
    """An agent's permission plan is DISPLAY-ONLY data. Keep a fixed shape and short strings; drop everything else, including any argv."""
    if not isinstance(plan, dict) or not isinstance(plan.get("items"), list):
        raise ValueError("plan must be an object with an items list")
    items = []
    for it in plan["items"][:40]:
        if not isinstance(it, dict):
            continue
        c = {k: str(it.get(k, ""))[:n] for k, n in _ITEM_KEYS.items()}
        if c["status"] not in _STATUSES:
            c["status"] = "unknown"
        c["required"], c["available"] = bool(it.get("required")), bool(it.get("available", True))
        p = it.get("panel")
        c["panel"] = {k: str(p.get(k, ""))[:200] for k in ("label", "uri")} if isinstance(p, dict) else None
        e = it.get("elevated")
        c["elevated"] = {k: str(e.get(k, ""))[:400] for k in ("description", "display", "how")} if isinstance(e, dict) else None
        items.append(c)
    return dict(os=str(plan.get("os", ""))[:20], os_label=str(plan.get("os_label", ""))[:60], user=str(plan.get("user", ""))[:60],
                admin=bool(plan.get("admin")), items=items,
                required_missing=[str(x)[:60] for x in (plan.get("required_missing") or [])[:20]], source="reported by the agent; display only")


def revoke(store, device):
    store.ux("UPDATE device_keys SET revoked=1 WHERE device=?", (device,))           # a revocation must not be undone by a power cut


def devices(store):
    return store.q("SELECT d.id, d.name, d.os, d.first_seen, d.last_seen, COALESCE(k.revoked, -1) AS revoked, k.created AS enrolled "
                   "FROM devices d LEFT JOIN device_keys k ON k.device = d.id ORDER BY d.first_seen")
