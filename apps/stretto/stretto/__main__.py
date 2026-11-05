"""stretto: the local server and its setup commands.

  python3 -m stretto                    start the server (same as: serve)
  python3 -m stretto doctor             check this computer, the .env, the data folder and the notices; says what to do next
  python3 -m stretto accept <family>    a PERSON accepts a notice by typing their name and an exact phrase
  python3 -m stretto revoke <family>    withdraw acceptance (new data from that family is refused at once)
Families: browser-history, host-system, meta-insights."""
import argparse
import os
import socket
import sys
import tempfile

COMMANDS = {"serve", "doctor", "accept", "revoke", "backup"}


def _args(argv):
    ap = argparse.ArgumentParser(prog="stretto", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="serve", choices=sorted(COMMANDS))
    ap.add_argument("family", nargs="?")
    ap.add_argument("--port", type=int, default=8760)
    ap.add_argument("--data", default=os.path.expanduser("~/.stretto"))
    ap.add_argument("--device", default="local", help="which device a notice is for (default: this computer's own UI)")
    ap.add_argument("--out", default=None, help="backup: folder to write to (default: <data>/backups)")
    ap.add_argument("--host", default="127.0.0.1", help="bind address; anything but 127.0.0.1/localhost is remote mode")
    ap.add_argument("--allow-host", action="append", default=[], help="exact Host header value to accept in remote mode, e.g. mac.tailnet.ts.net:8760")
    return ap.parse_args(argv)


def _store(a):
    from .store import Store
    return Store(os.path.join(a.data, "stretto.sqlite"))


def load_token(data_dir):
    """The master token, kept across restarts so an agent or script holding it is not locked out every time the server restarts.
    Reused when the file holds a plausible token; otherwise a new one is made. The file is readable only by its owner."""
    import secrets
    path = os.path.join(data_dir, "token")
    try:
        with open(path, encoding="utf-8") as f:
            tok = f.read().strip()
        if len(tok) >= 24 and tok.isascii() and tok.replace("-", "").replace("_", "").isalnum():
            return tok
    except OSError:
        pass
    tok = secrets.token_urlsafe(24)
    os.makedirs(data_dir, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(tok)
    return tok


def serve(a):
    import signal
    import threading
    from .server import make_server
    store = _store(a)
    srv, tok = make_server(store, a.port, token=load_token(a.data), host=a.host, allow_hosts=a.allow_host)
    from . import meta
    mode = "REMOTE (token on every API call)" if a.host not in ("127.0.0.1", "localhost") else "loopback only"
    d = store.durability()
    print(f"Stretto on http://{a.host}:{srv.server_address[1]}  [{mode}]  data: {a.data}  Meta models: {meta.mode() or 'not configured (see: doctor)'}"
          f"  durability: {d['journal_mode']}/{d['synchronous']}/fullfsync={'on' if d['fullfsync'] else 'off'}", flush=True)
    # SIGTERM (kill, service managers) and Ctrl-C both end in a clean shutdown: checkpoint the log into the database file, then close.
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=srv.shutdown, daemon=True).start())
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        store.close()


def backup(a):
    """A consistent copy of the database while the server runs (SQLite's online backup), checked for integrity. Keeps the newest 14."""
    import sqlite3
    import time
    src = os.path.join(a.data, "stretto.sqlite")
    if not os.path.isfile(src):
        sys.exit(f"no database at {src}")
    out = a.out or os.path.join(a.data, "backups")
    os.makedirs(out, exist_ok=True)
    dst = os.path.join(out, time.strftime("stretto-%Y%m%d-%H%M%S.sqlite"))
    s, d = sqlite3.connect(src), sqlite3.connect(dst)
    try:
        s.backup(d)
        d.execute("PRAGMA journal_mode=DELETE")          # the copy inherits WAL mode from the source; make it ONE self-contained file
    finally:
        d.close()
        s.close()
    chk = sqlite3.connect(dst)
    ok = chk.execute("PRAGMA integrity_check").fetchone()[0]
    n = chk.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    chk.close()
    for side in ("-wal", "-shm"):                        # SQLite can leave an empty sidecar after leaving WAL mode; the copy is in rollback mode and needs none
        try:
            os.remove(dst + side)
        except OSError:
            pass
    os.chmod(dst, 0o600)
    for old in sorted(f for f in os.listdir(out) if f.startswith("stretto-") and f.endswith(".sqlite"))[:-14]:
        os.remove(os.path.join(out, old))
    print(f"backup: {dst}  ({n} events, integrity {ok}). The token and .env are NOT included.")
    if ok != "ok":
        sys.exit(1)


def doctor(a):
    from . import consent, meta
    ok = True
    lines = []

    def row(good, label, detail="", blocker=True):
        nonlocal ok
        mark = "ok  " if good else ("FAIL" if blocker else "warn")
        if not good and blocker:
            ok = False
        lines.append(f"[{mark}] {label}{(': ' + detail) if detail else ''}")

    row(sys.version_info >= (3, 8), "Python 3.8 or newer", sys.version.split()[0])
    try:
        os.makedirs(a.data, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=a.data):
            pass
        row(True, "data folder is writable", a.data)
    except OSError as e:
        row(False, "data folder is writable", f"{a.data} ({e.strerror})")
    here = os.path.dirname(os.path.abspath(__file__))
    row(os.path.isfile(os.path.join(here, "static", "index.html")), "web interface files present")
    row(os.path.isdir(os.path.join(here, "..", "agent", "stretto_agent")), "agent files present (for the 'Install agent' download)")
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", a.port))
        row(True, f"port {a.port} is free")
    except OSError:
        row(True, f"port {a.port} is in use", "Stretto may already be running here", blocker=False)
    finally:
        s.close()
    path = meta.load_env(a.data)
    row(bool(path), ".env found", path or f"none. Copy .env.example to {os.path.join(a.data, '.env')} (or ./.env)", blocker=False)
    mode = meta.mode()
    row(mode is not None, "Meta Model API access", {"direct": "MODEL_API_KEY is set (value not shown)", "replay": "keyless replay of recorded runs"}.get(mode, "MODEL_API_KEY is not set and no STRETTO_REPLAY: insights will be unavailable"), blocker=False)
    if os.environ.get("STRETTO_REPLAY"):
        row(os.path.isdir(os.environ["STRETTO_REPLAY"]), "STRETTO_REPLAY folder exists", os.environ["STRETTO_REPLAY"])
    try:
        store = _store(a)
        d = store.durability()
        good = d["journal_mode"] == "wal" and d["synchronous"] in ("FULL", "EXTRA") and (d["fullfsync"] or sys.platform != "darwin")
        row(good, "database survives a power cut", f"{d['journal_mode']}, synchronous={d['synchronous']}, fullfsync={'on' if d['fullfsync'] else 'off'}")
        st = consent.status(store, a.device)
        for fam in consent.NOTICES:
            row(st[fam]["active"], f"notice '{fam}' accepted", ("by " + str(st[fam]["by"])) if st[fam]["active"] else f"not yet: python3 -m stretto accept {fam}", blocker=False)
    except Exception as e:
        row(False, "database opens", type(e).__name__)
    print("\n".join(lines))
    print("\nReady." if ok else "\nFix the FAIL lines above, then run doctor again.")
    if ok:
        print(f"Start:  python3 -m stretto --data {a.data}      then open http://127.0.0.1:{a.port}")
    return 0 if ok else 1


def accept(a):
    from . import consent
    if a.family not in consent.NOTICES:
        sys.exit("family must be one of: " + ", ".join(consent.NOTICES))
    if not sys.stdin.isatty():
        sys.exit("A notice must be accepted by a person at a terminal. It cannot be scripted or accepted on someone's behalf.")
    n = consent.NOTICES[a.family]
    print(f"\n=== {n['title']}  (notice v{consent.VERSION}, device '{a.device}') ===")
    for key, head in (("reads", "WHAT IS READ"), ("stores", "WHAT IS STORED"), ("never", "WHAT IS NEVER STORED"), ("goes", "WHERE IT GOES"), ("warn", "THINGS TO KNOW"), ("revoke", "YOUR CONTROL")):
        print(f"\n{head}")
        for line in n[key]:
            print(f"  - {line}")
    by = input("\nYour full name (who is accepting): ").strip()
    typed = input(f"To accept, type exactly  {consent.phrase(a.family)}  : ").strip()
    try:
        st = consent.record(_store(a), a.device, a.family, "grant", by, typed)
    except ValueError as e:
        sys.exit(f"Not accepted: {e}")
    print("Accepted." if st["active"] else "Not accepted.")


def revoke(a):
    from . import consent
    if a.family not in consent.NOTICES:
        sys.exit("family must be one of: " + ", ".join(consent.NOTICES))
    if not sys.stdin.isatty():
        sys.exit("Run this at a terminal.")
    by = input("Your full name: ").strip()
    consent.record(_store(a), a.device, a.family, "revoke", by)
    print("Revoked. New data from this family is now refused.")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    a = _args(argv)
    from . import meta
    meta.load_env(a.data)
    code = {"serve": serve, "doctor": doctor, "accept": accept, "revoke": revoke, "backup": backup}[a.command](a)
    sys.exit(code or 0)


if __name__ == "__main__":
    main()
