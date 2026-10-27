# SPDX-License-Identifier: Apache-2.0
"""One read-only sample of the cluster into the telemetry store. Calls `inventory CLI --output json inventory` (GET /cluster/resources) only.
Usage: python sampler.py [db_path]. Intended to run from a timer once approved; running it by hand is safe and idempotent per timestamp."""
import json, os, subprocess, sys, time
from telemetry.store import Store, ingest_pve, maturity

INVENTORY = os.environ.get("INVENTORY_CMD")   # path to a read-only cluster inventory CLI; set it explicitly
def fetch():
    if not INVENTORY: raise RuntimeError('set INVENTORY_CMD to the inventory CLI (read-only: inventory only)')
    t0 = time.time(); p = subprocess.run([INVENTORY, "--output", "json", "inventory"], capture_output=True, text=True, timeout=120)
    if p.returncode != 0 or not p.stdout.strip(): raise RuntimeError(f"inventory CLI failed rc={p.returncode}: {p.stderr[:200]}")
    return json.loads(p.stdout), time.time() - t0

if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/.metacoh/telemetry.db")
    os.makedirs(os.path.dirname(db), exist_ok=True); inv, secs = fetch(); s = Store(db); n = ingest_pve(s, inv)
    print(json.dumps(dict(rows=n, fetch_seconds=round(secs, 2), db=db, store_rows=s.count(), maturity=maturity(s, 3600)), indent=1))
