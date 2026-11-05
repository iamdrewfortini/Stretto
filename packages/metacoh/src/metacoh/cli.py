# SPDX-License-Identifier: Apache-2.0
"""metacoh command line: `metacoh gateway` (the self-hosted runtime), `metacoh sensors` (the desktop agent), `metacoh doctor` (self-check of an installed system), `metacoh wf13d c.t.s`, `metacoh ant`, `metacoh version`."""
import argparse, json, os, sys
from importlib import metadata

PACKAGES = ["wf13d", "coherence", "metarouter", "harness", "telemetry", "cells", "perception", "humanflow", "assistant", "finetune", "handoff", "resonate", "adapters", "runtime", "sensors"]
def version():
    try: return metadata.version("metacoh")
    except metadata.PackageNotFoundError: return "0+source"
def doctor():
    from . import doctor as d
    results = d.run_all(); width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results: print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    bad = [n for n, ok, _ in results if not ok]; print(f"\n{len(results) - len(bad)}/{len(results)} checks passed" + (f"; failing: {', '.join(bad)}" if bad else "")); return 1 if bad else 0
def _gateway_env(environ, home):
    """Assemble the gateway env for an installed, self-hosted run.

    Non-secret defaults match .env.example; the real env file (mode
    600, outside any install prefix) overrides them when present, and
    the process environment wins over both. Events and the ledger
    live under the user's data directory, not the working directory.
    """
    env = {"RUNTIME_MODE": "local", "GATEWAY_BIND": "127.0.0.1:8787",
           "VOICE_BIND": "127.0.0.1:8788", "EGRESS_ALLOWLIST": "api.meta.ai",
           "META_BASE_URL": "https://api.meta.ai/v1",
           "META_ASR_URL": "wss://api.meta.ai/v1/asr/realtime",
           "OWNER_ID": "owner", "SPEND_LIMIT_USD": "5.00"}
    path = environ.get("HUMANFLOW_ENV") or os.path.join(
        home, ".config", "humanflow", "runtime.env")
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.split(" #", 1)[0].strip() if not v.lstrip().startswith(
                ("'", '"')) else v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            env[k.strip()] = v
    env.update({k: v for k, v in environ.items() if k in env or k in (
        "HUMANFLOW_ENV", "SENSORS_CONSENT", "REGISTRY_PATH", "MODEL_API_KEY",
        "EVENT_LOG", "LEDGER_PATH")})
    env["HUMANFLOW_ENV"] = path
    data = os.path.join(home, ".local", "share", "humanflow")
    env.setdefault("EVENT_LOG", os.path.join(data, "events.jsonl"))
    env.setdefault("LEDGER_PATH", os.path.join(data, "ledger.jsonl"))
    return env


def gateway(environ=None, home=None):
    from runtime.gateway import serve
    serve(_gateway_env(environ or os.environ,
                       home or os.path.expanduser("~")))
    return 0


def sensors(argv):
    from sensors.__main__ import main as sensors_main
    return sensors_main(argv)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="metacoh"); sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("version"); sub.add_parser("doctor"); sub.add_parser("gateway", help="run the local runtime gateway (starts keyless; add the key at /settings)")
    s = sub.add_parser("sensors", help="desktop sensor agent: probe | grant | revoke | run"); s.add_argument("args", nargs=argparse.REMAINDER)
    w = sub.add_parser("wf13d"); w.add_argument("address", help="decimal c.t.s, e.g. 15.07.072"); sub.add_parser("ant")
    a = ap.parse_args(argv)
    if a.cmd == "version": print(version()); return 0
    if a.cmd == "doctor": return doctor()
    if a.cmd == "gateway": return gateway()
    if a.cmd == "sensors": return sensors(a.args)
    if a.cmd == "wf13d":
        from wf13d.bridge import analyze, pack
        c, t, s = (int(x) for x in a.address.split(".")); print(json.dumps(analyze(pack(c, t, s)), indent=1)); return 0
    if a.cmd == "ant":
        from coherence.swarm import langton_until_locked
        print(json.dumps(langton_until_locked(), indent=1, default=str)); return 0
if __name__ == "__main__": sys.exit(main())
