# SPDX-License-Identifier: Apache-2.0
"""stretto-agent: capture this computer's activity and import its history into a Stretto server, with consent.

  status                 server reachable? consent per notice? enabled sources? spooled batches?
  probe                  list what could be imported (existence and size only; nothing is opened or read)
  consent <family>       show the notice, then a PERSON types their name and the exact phrase to accept
  revoke <family>        stop immediately (new data refused by the server)
  purge <family>         delete what was already imported, after a typed confirmation
  enable|disable <src>   choose which history sources the agent may import (consent is still required)
  import [--max N]       import enabled sources once, incrementally from their cursors
  run                    capture every few seconds and import periodically, until stopped
  pause | resume         stop/start capturing without stopping the agent

Families: browser-history, host-system."""
import argparse
import os
import re
import sys
import time

from . import adapters, cfg as C, importers
from .client import Client, ConsentRequired, Spool


def _client(cfg):
    key = C.device_key(cfg)
    return Client(cfg["server"], "" if key else C.token(cfg), device_key=key)


MARK = {"granted": "[ok]     ", "missing": "[MISSING]", "unknown": "[?]      ", "unsupported": "[N/A]    ", "not_applicable": "[-]      "}


def print_plan(plan):
    print(f"\nThis computer: {plan['os_label']} (user {plan['user']}{', administrator' if plan['admin'] else ''})")
    for it in plan["items"]:
        tag = "" if it["available"] else "  (planned, not built yet)"
        print(f"\n{MARK.get(it['status'], '[?]')} {it['label']}{tag}\n           {it['why']}")
        if it["note"]:
            print(f"           Note: {it['note']}")
        if it["panel"]:
            print(f"           Settings panel: {it['panel']['label']}   ->  stretto-agent perms open {it['id']}")
        if it["elevated"]:
            e = it["elevated"]
            print(f"           Needs elevation: {e['description']}\n             command: {e['display']}\n             authorised by: {e['how']}\n             run it for you:  stretto-agent perms run {it['id']}")
    if plan["required_missing"]:
        print(f"\nStill needed before recording works: {', '.join(plan['required_missing'])}")


def report_env(cfg, cl, log=print):
    from . import perms
    try:
        cl.post("/api/agent/environment", dict(device=cfg["device"], plan=perms.public(perms.detect())))
    except Exception as e:
        log(f"could not report this computer's permission plan: {type(e).__name__}")


def cmd_perms(cfg, a):
    from . import perms
    plan = perms.detect()
    if a.action == "open":
        print("opened" if perms.open_panel(a.id or "") else "no settings panel for that item")
    elif a.action == "run":
        item = next((i for i in plan["items"] if i["id"] == a.id and i["elevated"]), None)
        if not item:
            sys.exit("that item has no elevated command")
        _need_person()
        e = item["elevated"]
        print(f"\n{e['description']}\n\nExact command:\n  {e['display']}\n\nThe operating system will ask you to approve this itself: {e['how']}.")
        if input(f"Type exactly  RUN {item['id']}  to continue: ").strip() != f"RUN {item['id']}":
            sys.exit("not run")
        print(f"finished with code {perms.run_elevated(item['id'])}")
    elif a.action == "report":
        report_env(cfg, _client(cfg))
        print("reported")
    else:
        print_plan(plan)


def cmd_emit(cfg, a):
    """Print work-history batches as JSON. No network, no config written. Used by `remote` on a server, and handy for a dry look.
    stdin (optional): {"cursors": {"<source>": "<cursor>"}}. Only the work-history family can be emitted."""
    import json
    imps = [i for i in importers.discover_work()]
    if a.list:
        print(json.dumps(dict(os=C.os_label(), user=os.environ.get("USER", ""), sources=[p for p in (i.probe() for i in imps) if p])))
        return
    cursors = (json.load(sys.stdin) or {}).get("cursors", {}) if not sys.stdin.isatty() else {}
    batches = []
    for imp in imps:
        samples, new_cursor, power = imp.read(cursors.get(imp.name, ""))
        if samples or power:
            batches.append(dict(src=imp.name, samples=samples, power=power, cursor=new_cursor))
    print(json.dumps(dict(os=C.os_label(), batches=batches)))


def _ssh(host, remote_cmd, stdin=None, timeout=120):
    import subprocess
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, remote_cmd], input=stdin, capture_output=True, text=True, timeout=timeout)


def cmd_remote(cfg, a):
    """Read a server's work history over SSH and send it to Stretto as device 'host-<name>'. Nothing is installed: the agent is copied to a
    temporary folder, run, and deleted. The person must have accepted 'work-history' for that device first. Needs the admin token (relay)."""
    import json
    import re
    import subprocess
    dev = a.device or "host-" + re.sub(r"[^A-Za-z0-9_.-]", "-", a.host)[:50]
    cl = Client(cfg["server"], C.token(cfg))
    if not cl.consent(dev)["work-history"]["active"]:
        sys.exit(f"The 'work-history' notice has not been accepted for '{dev}'. On the Stretto server computer run:\n  python3 -m stretto accept work-history --device {dev}")
    here = os.path.dirname(os.path.abspath(__file__))
    tmp = _ssh(a.host, "mktemp -d").stdout.strip()
    if not tmp.startswith("/"):
        sys.exit("could not create a temporary folder on the host")
    try:
        r = subprocess.run(["scp", "-q", "-r", "-o", "BatchMode=yes", here, f"{a.host}:{tmp}/stretto_agent"], capture_output=True, text=True, timeout=120)
        if r.returncode:
            sys.exit("could not copy the agent to the host")
        run = f"cd {tmp} && STRETTO_AGENT_HOME={tmp}/home python3 -c 'import sys; sys.path.insert(0,\".\"); from stretto_agent import cli; cli.main()' emit"
        info = json.loads(_ssh(a.host, run + " --list").stdout or "{}")
        cursors = {s["source"]: cl.get(f"/api/cursor?device={dev}&src={s['source']}")["cursor"] for s in info.get("sources", [])}
        out = json.loads(_ssh(a.host, run, stdin=json.dumps(dict(cursors=cursors))).stdout or "{}")
        total = 0
        for b in out.get("batches", []):
            r = cl.post("/api/ingest", dict(device=dev, device_name=a.host, os=info.get("os", ""), src=b["src"], samples=b["samples"], power=b["power"], cursor=b["cursor"]))
            total += r["stored"]
            print(f"{b['src']}: +{r['stored']} new of {r['received']} read")
        print(f"{a.host}: {total} new rows. Temporary folder removed.")
    finally:
        _ssh(a.host, f"rm -rf {tmp}")


def cmd_enroll(cfg, a):
    """Exchange the installer's one-time code for this computer's own key. The master token is never needed again."""
    r = Client(cfg["server"]).post("/api/agent/register", dict(code=a.code, device=cfg["device"], name=cfg["device_name"], os=C.os_label()))
    p = C.path("device.key")
    C.write_secret(p, r["device_key"])
    cfg["device_key_file"], cfg["token_file"] = p, ""
    C.save(cfg)
    print(f"enrolled as '{cfg['device_name']}'. This computer now has its own key.")


def _need_person():
    if not sys.stdin.isatty():
        sys.exit("This step must be done by a person at a terminal. It cannot be scripted or accepted on someone's behalf.")


def _print_notice(n):
    print(f"\n=== {n['title']}  (notice v{n['version']}) ===")
    for key, head in (("reads", "WHAT IS READ"), ("stores", "WHAT IS STORED"), ("never", "WHAT IS NEVER STORED"), ("goes", "WHERE IT GOES"),
                      ("warn", "THINGS TO KNOW"), ("revoke", "YOUR CONTROL")):
        print(f"\n{head}")
        for line in n[key]:
            print(f"  - {line}")
    print()


def cmd_status(cfg, a):
    cl = _client(cfg)
    print(f"device: {cfg['device_name']} ({cfg['device']})  server: {cfg['server']}")
    try:
        fam = cl.consent(cfg["device"])
        for k, v in fam.items():
            print(f"consent {k}: {'ACTIVE, accepted by ' + str(v['by']) if v['active'] else 'not active'}")
    except Exception as e:
        print(f"server unreachable: {e}")
    print(f"enabled sources: {', '.join(cfg['enabled_sources']) or '(none)'}")
    print(f"spooled batches: {len(Spool().pending())}   paused: {os.path.exists(C.path('paused'))}")


def cmd_probe(cfg, a):
    for imp in importers.discover():
        p = imp.probe()
        if p:
            print(f"{p['source']:36} {p['family']:16} {str(p['bytes']) + ' bytes' if p['bytes'] is not None else 'system log':>14}  {p['path']}")
    print("\nNothing was opened or read. Accept the notice with 'consent <family>' before importing.")


def cmd_consent(cfg, a):
    _need_person()
    cl = _client(cfg)
    n = cl.get(f"/api/consent/notice?family={a.family}")
    _print_notice(n)
    by = input("Your full name (who is accepting): ").strip()
    typed = input(f"To accept, type exactly  {n['phrase']}  : ").strip()
    try:
        r = cl.post("/api/consent", dict(device=cfg["device"], family=a.family, action="grant", granted_by=by, typed=typed))
    except RuntimeError as e:
        if "out_of_scope" in str(e):
            sys.exit("This computer's key can stop recording but cannot accept a notice. Accept it in the Stretto app, "
                     "or on the server computer run:  python3 -m stretto accept " + a.family)
        raise
    print("Accepted." if r.get("active") else "Not accepted.")


def cmd_revoke(cfg, a):
    _need_person()
    by = input("Your full name: ").strip()
    r = _client(cfg).post("/api/consent", dict(device=cfg["device"], family=a.family, action="revoke", granted_by=by))
    print("Revoked. New data from this family is now refused." if not r.get("active") else "Still active?")


def cmd_purge(cfg, a):
    _need_person()
    typed = input(f"This deletes everything imported for '{a.family}' from this device. Type exactly  DELETE {a.family}  : ").strip()
    print(_client(cfg).post("/api/purge", dict(device=cfg["device"], family=a.family, confirm=typed)))


def cmd_enable(cfg, a):
    names = {i.name for i in importers.discover()}
    if a.source not in names:
        sys.exit(f"unknown source. Available: {', '.join(sorted(names)) or '(none)'}")
    cfg["enabled_sources"] = sorted(set(cfg["enabled_sources"]) | {a.source})
    C.save(cfg)
    print(f"enabled {a.source}. Importing still requires an accepted notice.")


def cmd_disable(cfg, a):
    cfg["enabled_sources"] = [s for s in cfg["enabled_sources"] if s != a.source]
    C.save(cfg)


def import_once(cfg, cl, max_batches=1000, log=print):
    """Import every enabled source, incrementally. Returns total new rows. Stops a family the moment the server says consent is missing."""
    fam = cl.consent(cfg["device"])
    total = 0
    for imp in importers.discover():
        if imp.name not in cfg["enabled_sources"]:
            continue
        if not fam.get(imp.family, {}).get("active"):
            log(f"skip {imp.name}: the '{imp.family}' notice has not been accepted")
            continue
        for _ in range(max_batches):
            cursor = cl.get(f"/api/cursor?device={cfg['device']}&src={imp.name}")["cursor"]
            samples, new_cursor, power = imp.read(cursor)
            if not samples and not power:
                break
            try:
                r = cl.post("/api/ingest", dict(device=cfg["device"], device_name=cfg["device_name"], os=C.os_label(), src=imp.name,
                                                samples=samples, power=power, cursor=new_cursor))
            except ConsentRequired as e:
                log(f"stopped {imp.name}: consent for '{e.family}' is no longer active")
                break
            total += r["stored"] + r.get("power", 0)
            log(f"{imp.name}: +{r['stored']} new of {r['received']} read")
            if new_cursor == cursor:
                break
    return total


def cmd_import(cfg, a):
    print(f"imported {import_once(cfg, _client(cfg), a.max)} new rows")


def cmd_run(cfg, a, stop=lambda: False, clock=time.time, sleep=time.sleep):
    """Capture exact stays at the OS's polling rate and import history periodically. `stop`, `clock` and `sleep` are injectable for tests."""
    cl, spool = _client(cfg), Spool()
    cap, why = adapters.make()
    if cap is None:
        print(f"no window capture here ({why}). Running history imports only.")
    tracker = adapters.FocusTracker(cfg)
    seen_apps, new_apps, buf = set(), [], []
    poll = adapters.poll_interval()
    next_flush, next_check, next_import, ok, record_inputs = 0, 0, clock() + 60, False, False
    print("agent running. Ctrl-C to stop.")
    report_env(cfg, cl)
    while not stop():
        now = clock()
        if now >= next_check:
            try:
                fam = cl.consent(cfg["device"])
                ok, record_inputs = fam["host-system"]["active"], fam.get("input-activity", {}).get("active", False)
            except Exception:
                ok, record_inputs = False, False
            tracker.count_inputs = record_inputs
            next_check = now + 300
            if cap is not None and not ok:
                print("waiting: the 'host-system' notice has not been accepted (or the server is unreachable). Nothing is being recorded.")
        if cap is not None and ok and not os.path.exists(C.path("paused")):
            try:
                snap = cap()
                buf.extend(tracker.update(now, snap))
                nm = re.sub(r"\.exe$", "", snap.get("app", ""), flags=re.I) if snap.get("app") else ""
                if nm and nm not in seen_apps and snap.get("path") and hasattr(cap, "version_info"):
                    seen_apps.add(nm)
                    meta = cap.version_info(snap["path"])
                    if meta:
                        new_apps.append(dict(app=nm, **meta))
            except Exception as e:      # one bad look must never stop the agent
                print(f"look skipped: {type(e).__name__}")
        elif tracker.cur:
            buf.extend(tracker.flush(now))                   # paused or consent withdrawn: close the open stay, record nothing more
        if now >= next_flush:
            if buf or new_apps:
                spool.add(dict(device=cfg["device"], device_name=cfg["device_name"], os=C.os_label(), src="collector", samples=buf, apps=new_apps))
                buf, new_apps = [], []
            try:
                spool.flush(cl)
            except ConsentRequired:
                ok, next_check = False, now + 300
                print("server refused: consent not active. Stopped recording.")
            next_flush = now + 30
        if now >= next_import:
            try:
                import_once(cfg, cl, 50, log=lambda m: None)
            except Exception:
                pass
            next_import = now + cfg["import_every_s"]
        sleep(poll if cap is not None else 30)


def cmd_pause(cfg, a):
    open(C.path("paused"), "w").close()
    print("paused")


def cmd_resume(cfg, a):
    try:
        os.remove(C.path("paused"))
    except OSError:
        pass
    print("resumed")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="stretto-agent", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server")
    ap.add_argument("--token-file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("status", cmd_status), ("probe", cmd_probe), ("run", cmd_run), ("pause", cmd_pause), ("resume", cmd_resume)):
        sub.add_parser(name).set_defaults(fn=fn)
    for name, fn in (("consent", cmd_consent), ("revoke", cmd_revoke), ("purge", cmd_purge)):
        p = sub.add_parser(name)
        p.add_argument("family", choices=["browser-history", "host-system", "work-history"])
        p.set_defaults(fn=fn)
    for name, fn in (("enable", cmd_enable), ("disable", cmd_disable)):
        p = sub.add_parser(name)
        p.add_argument("source")
        p.set_defaults(fn=fn)
    p = sub.add_parser("enroll")
    p.add_argument("code")
    p.set_defaults(fn=cmd_enroll)
    p = sub.add_parser("emit", help="print work-history batches as JSON (no network)")
    p.add_argument("--list", action="store_true")
    p.set_defaults(fn=cmd_emit)
    p = sub.add_parser("remote", help="read a server's work history over SSH, nothing installed")
    p.add_argument("host")
    p.add_argument("--device")
    p.set_defaults(fn=cmd_remote)
    p = sub.add_parser("perms", help="what this computer needs: native settings panels and exact elevated commands")
    p.add_argument("action", nargs="?", choices=["open", "run", "report"])
    p.add_argument("id", nargs="?")
    p.set_defaults(fn=cmd_perms)
    p = sub.add_parser("import")
    p.add_argument("--max", type=int, default=1000)
    p.set_defaults(fn=cmd_import)
    a = ap.parse_args(argv)
    cfg = C.load()
    changed = False
    for k, v in (("server", a.server), ("token_file", a.token_file)):
        if v:
            cfg[k], changed = v, True
    if changed:
        C.save(cfg)
    a.fn(cfg, a)


if __name__ == "__main__":
    main()
