# SPDX-License-Identifier: Apache-2.0
"""CLI: probe | grant | revoke | run. Stdlib only, Python 3.9+.

  python3 -m sensors probe
  python3 -m sensors grant window idle [--ttl 8h]
  python3 -m sensors revoke [source...]
  python3 -m sensors run --gateway http://127.0.0.1:8787 [--hz 1] [--titles off]

grant/revoke write ~/.config/humanflow/consent.json (0600) and print
the consent.changed event; when SENSORS_GATEWAY is set they also POST
it to that loopback gateway so the dashboard consent strip updates.
"""
import argparse
import json
import os
import socket
import sys

from .adapters import discover
from .consent import ConsentStore, SOURCES, parse_ttl
from .importer import Importer
from .ingest import IngestClient


def _emit(event, gateway=None):
    print(json.dumps(event))
    gw = gateway or os.environ.get("SENSORS_GATEWAY")
    if gw:
        try:
            c = IngestClient(gw)
            c.push(event)
            c.flush(force=True)
        except Exception as e:
            print(f"note: not sent ({e})", file=sys.stderr)


def main(argv=None):
    p = argparse.ArgumentParser(prog="sensors")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe")
    g = sub.add_parser("grant")
    g.add_argument("sources", nargs="+", choices=SOURCES)
    g.add_argument("--ttl", default="8h")
    r = sub.add_parser("revoke")
    r.add_argument("sources", nargs="*", choices=SOURCES)
    run = sub.add_parser("run")
    run.add_argument("--gateway", required=True)
    run.add_argument("--hz", type=float, default=1.0)
    run.add_argument("--titles", choices=("on", "off"), default=None)
    run.add_argument("--idle-threshold", type=float, default=120.0)
    a = p.parse_args(argv)
    store = ConsentStore()

    if a.cmd == "probe":
        rows = discover(include_unavailable=True)
        width = max((len(x.name) for x, _, _ in rows), default=4)
        for ad, ok, why in rows:
            print(f"{ad.name:<{width}}  {ad.source:<8} "
                  f"{'available' if ok else why}")
        return 0
    if a.cmd == "grant":
        _emit(store.grant(a.sources, parse_ttl(a.ttl)))
        return 0
    if a.cmd == "revoke":
        _emit(store.revoke(a.sources or None))
        return 0
    if a.cmd == "run":
        titles_on = None
        if a.titles is not None:
            titles_on = a.titles == "on"
        client = IngestClient(a.gateway,
                              source_host=socket.gethostname())
        imp = Importer(discover(include_unavailable=True), store,
                       client, titles_on=titles_on, hz=a.hz,
                       idle_threshold_s=a.idle_threshold)
        print(f"sensors: gateway={a.gateway} host={client.source_host}",
              file=sys.stderr)
        try:
            imp.run()
        except KeyboardInterrupt:
            imp.close()
            client.flush(force=True)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
