"""Consent for reading real browser and system data. The server is the single authority: it refuses ingest from a source whose
family has no active grant for that device, whatever an agent's own config says.

A grant is made by a person typing their name and an exact phrase. It is recorded in an append-only, hash-chained log. Revoking
blocks new ingest at once; deleting what was already imported is a separate, typed-confirm action (purge)."""
import hashlib
import json
import time

BROWSERS = {"chrome", "edge", "brave", "firefox", "chromium", "opera", "vivaldi", "safari"}
VERSION = 1   # bump when a notice changes: every earlier grant then stops counting and the person is asked again

NOTICES = {
    "browser-history": dict(
        title="Import browser history",
        reads=["The History database of each Chrome, Edge, Brave and Firefox profile in YOUR user account. It is copied read-only to a temporary file, read, and the copy is deleted.",
               "Only files your own account can already open. No administrator rights are requested."],
        stores=["For each visit: the time, how long you stayed (when the browser recorded it), the site's domain, and the page title."],
        never=["Full addresses with paths or query strings, page content, cookies, saved passwords, form data, downloads, or anything from private/incognito windows (browsers do not write those)."],
        goes=["Into Stretto's database on the computer that runs the Stretto server. This import sends nothing to Meta or any other service."],
        warn=["Page titles can reveal private things (an email subject, a document name, a person's name). You can blocklist sites or apps so their titles are dropped."],
        revoke=["You can revoke at any time. That stops new imports immediately. You can also delete everything already imported from this source."]),
    "work-history": dict(
        title="Import work history from this computer or server",
        reads=["Commit TIMES and the repository NAME for commits made by you, from git repositories under folders you choose (default: ~/DEV, ~/Projects, ~/src, ~/code, ~/work).",
               "TIMESTAMPS from your shell history files (zsh and bash). The commands themselves are discarded as each line is read.",
               "Your own login times to a Linux computer or server (from the system's login records). Only your own account."],
        stores=["Times, repository names, shell activity markers, and session lengths (a login session is capped at 2 hours: being logged in is presence, not work)."],
        never=["Commit messages, code, file names, command text, passwords, keys, other people's activity, or network addresses."],
        goes=["Into Stretto's database on the computer that runs the Stretto server. For a remote server, the agent runs from a temporary folder over your SSH connection, reads only the sources above, sends the result to Stretto, and deletes its folder. Nothing goes to Meta from this import."],
        warn=["Repository names and the hours you work can reveal clients, projects and habits. Choose the folders to scan with STRETTO_GIT_ROOTS. Each server or computer is accepted separately."],
        revoke=["You can revoke at any time. That stops further imports immediately. You can also delete everything already imported from this family."]),
    "input-activity": dict(
        title="Count keyboard and mouse activity (never what you type)",
        reads=["How often, sampled up to four times a second, the operating system registered any keyboard or mouse input, taken from its own 'time since last input' clock. This is a count of active moments, not of keys or clicks."],
        stores=["A single number per stretch of time in one window: how many of those moments had input. Used to tell active work from reading and to measure focus."],
        never=["Which keys, what you type, the order of keys, which window received a click, or any keyboard hook or key logger. Stretto does not install one."],
        goes=["Into Stretto's database on the computer that runs the Stretto server. Nothing goes to Meta from this."],
        warn=["Counts still reveal when you are typing versus reading, and rhythm can be personal. Without this notice the agent sends no counts, and the server discards any that arrive."],
        revoke=["You can revoke at any time. That stops counts immediately. You can also delete the counts already stored."]),
    "meta-insights": dict(
        title="Send a day's summary to Meta for coaching",
        reads=["Only for a day you ask about: the names of applications, the domains of sites, the minutes spent in each, and Stretto's own measured findings (detours, ping-pong, repeated routes)."],
        stores=["Meta's reply (a headline and a few suggested actions) and a log of each call: model, token counts, estimated cost and time."],
        never=["Window titles, full addresses, screenshots, keystrokes, file contents, your name, or anything from days you did not ask about."],
        goes=["To Meta's Model API (api.meta.ai), using the API key held by the Stretto server. Meta handles it under its own terms. The hackathon's credit notes say content may be used for product improvement while free credits are in use; check Meta's current terms."],
        warn=["App names and site domains can still reveal private things. Suggestions are the model's opinion and are labelled 'inferred'. Stretto drops any suggestion that cites a finding or a number that was not measured, and any medical or mental-health advice."],
        revoke=["You can revoke at any time. That stops further calls immediately. Past replies stay in your local database until you delete them."]),
    "host-system": dict(
        title="Record activity on this computer",
        reads=["While the agent runs, every 5 seconds: which application window is in front, that window's title, how long since your last keyboard or mouse input, and the mouse pointer position.",
               "From your own account's files: the Windows System event log (start-up, shutdown, sleep, wake) and the Windows app-activity cache, if present. No administrator rights are requested."],
        stores=["Time, application name, window title, idle or not, pointer position, and system on/off/sleep/wake times."],
        never=["Keystrokes, what you type, screen contents or screenshots, the clipboard, the microphone or camera, passwords, or the content of any file."],
        goes=["Into Stretto's database on the computer that runs the Stretto server. This recording sends nothing to Meta or any other service."],
        warn=["Window titles can contain private text. Windows in private/incognito browsing and password-manager windows are dropped by default; add more to the blocklist."],
        revoke=["You can revoke at any time. That stops recording and import immediately. You can also delete everything already recorded."]),
}


def phrase(family):
    return f"I AGREE: {family}"


def family_of(src):
    """The consent family a source belongs to, or None when it needs none (simulated demo data)."""
    s = str(src).split(":")[0]
    if s in ("git-history", "shell-history", "login-sessions"):        # checked first: these end in '-history' too but are NOT browser data
        return "work-history"
    if s in ("collector", "activities-cache", "power"):
        return "host-system"
    if s.endswith("-history") and s[: -len("-history")] in BROWSERS:
        return "browser-history"
    if s.endswith("-history"):
        return "unknown-history"                                        # an unrecognised history source must never slip through ungated
    return None


def _hash(prev, rec):
    return hashlib.sha256((prev + json.dumps(rec, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()


def log(store, device=None):
    q, a = "SELECT * FROM consent", ()
    if device:
        q, a = q + " WHERE device=?", (device,)
    return store.q(q + " ORDER BY id", a)


def status(store, device):
    """Per family: is there an active grant for the CURRENT notice version?"""
    out = {}
    for fam in NOTICES:
        rows = store.q("SELECT * FROM consent WHERE device=? AND family=? ORDER BY id DESC LIMIT 1", (device, fam))
        last = rows[0] if rows else None
        out[fam] = dict(active=bool(last and last["action"] == "grant" and last["version"] == VERSION), version=last["version"] if last else None,
                        action=last["action"] if last else None, by=last["granted_by"] if last else None, ts=last["ts"] if last else None)
    return out


def active(store, device, family):
    return status(store, device).get(family, {}).get("active", False)


def record(store, device, family, action, by, typed=""):
    if family not in NOTICES:
        raise ValueError("unknown consent family")
    if action not in ("grant", "revoke"):
        raise ValueError("action must be grant or revoke")
    by = str(by).strip()[:80]
    if not by:
        raise ValueError("a name is required: the person who accepts must be identifiable")
    if action == "grant" and typed.strip() != phrase(family):
        raise ValueError(f"to accept, type exactly: {phrase(family)}")
    prev = (store.q("SELECT hash FROM consent ORDER BY id DESC LIMIT 1") or [{"hash": "0" * 64}])[0]["hash"]
    rec = dict(device=device, family=family, version=VERSION, action=action, granted_by=by, ts=round(time.time(), 3))
    store.x("INSERT INTO consent(device,family,version,action,granted_by,ts,prev,hash) VALUES(?,?,?,?,?,?,?,?)",
            (rec["device"], rec["family"], rec["version"], rec["action"], rec["granted_by"], rec["ts"], prev, _hash(prev, rec)))
    store.checkpoint(force=True)                       # an acceptance or a withdrawal must never be lost to a power cut
    return status(store, device)[family]


def verify_chain(store):
    """True when no consent record was altered or removed."""
    prev = "0" * 64
    for r in store.q("SELECT * FROM consent ORDER BY id"):
        rec = dict(device=r["device"], family=r["family"], version=r["version"], action=r["action"], granted_by=r["granted_by"], ts=r["ts"])
        if r["prev"] != prev or r["hash"] != _hash(prev, rec):
            return False
        prev = r["hash"]
    return True


def purge(store, device, family, confirm):
    """Delete what was imported for a family from a device. Typed confirmation, and it is logged by the consent record that precedes it."""
    if confirm != f"DELETE {family}":
        raise ValueError(f"to delete, type exactly: DELETE {family}")
    srcs = [r["src"] for r in store.q("SELECT DISTINCT src FROM events WHERE device=?", (device,)) if family_of(r["src"]) == family]
    n = 0
    for s in srcs:
        n += store.q("SELECT COUNT(*) AS n FROM events WHERE device=? AND src=?", (device, s))[0]["n"]
        store.x("DELETE FROM events WHERE device=? AND src=?", (device, s))
        store.x("DELETE FROM sources WHERE device=? AND src=?", (device, s))
    if family == "host-system":
        store.x("DELETE FROM power WHERE device=?", (device,))
    store.checkpoint(force=True)                       # a deletion the person asked for must stay deleted
    return dict(deleted=n, sources=srcs)
