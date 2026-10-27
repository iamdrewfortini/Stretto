# SPDX-License-Identifier: Apache-2.0
"""Installed-system self check. Each check can fail; none touches the network, a camera, or any cluster."""
import hashlib

def _check(name, fn):
    try: ok, detail = fn(); return name, bool(ok), detail
    except Exception as e: return name, False, f"{type(e).__name__}: {e}"
def versions():
    from importlib import metadata
    names = ["metacoh"] + [f"metacoh-{p}" for p in ("wf13d", "coherence", "metarouter", "harness", "telemetry", "cells", "perception", "humanflow", "assistant", "finetune", "handoff", "resonate", "adapters")]
    got = {n: metadata.version(n) for n in names}; return len(set(got.values())) == 1, f"{len(got)} distributions, all {next(iter(set(got.values())))}" if len(set(got.values())) == 1 else str(got)
def wf13d_table():
    from importlib import resources
    from wf13d import bridge, table
    blob = (resources.files("wf13d") / "data" / "wf13d.tbl").read_bytes(); want = (resources.files("wf13d") / "data" / "wf13d.tbl.sha256").read_text().strip(); got = hashlib.sha256(blob).hexdigest()
    T = table.Table(blob); a = bridge.pack(15, 7, 72); same = T.lookup(a) == bridge.analyze(a)
    return got == want and same and len(blob) == 1048576, f"sha256 {got[:12]}..., lookup == analyze at 15.07.072: {same}"
def ant():
    from coherence.swarm import langton_until_locked
    r = langton_until_locked(); return r["status"] == "LOCKED" and r["guaranteed"] and (r["steps_run"], r["vector"]) == (10608, (-2, -2)), f"{r['status']} after {r['steps_run']} steps, vector {r['vector']}"
def consent():
    from perception import ConsentRegistry
    r = ConsentRegistry(); d = not r.allows("p", "screen", "assist", 0); r.grant("p", ["screen"], ["assist"], 10, 0); r.revoke("p", 1); return d and not r.allows("p", "screen", "assist", 2), "default deny, revocation honoured"
def meta_only():
    from metarouter.policy import check_agent
    return bool(check_agent(dict(id="x", model="gpt-5"))) and not check_agent(dict(id="x", model="muse-wonder-1.0")), "non-Meta model refused, Meta model accepted"
def coherence():
    from coherence.metrics import distance
    d = distance({"speed": None, "energy": None, "balance": 0.12, "scale": None, "intent": 0.5}); return d["lower_bound"] and 0.22 < d["D"] < 0.24, f"D >= {d['D']} (lower bound, 3 axes unmeasured)"
def mirror():
    from coherence.mirror import mirror_coherence, hypercube_counts
    return abs(mirror_coherence([1] * 13, [1] * 13) - 1) < 1e-9 and hypercube_counts(4)[0] == 16, "mirror(identical)=1; 4-cube has 16 vertices"
def handoff():
    from handoff import examples, gaps, close
    p = examples.gearbox(); q = p.copy(); removed = q.steps.pop(q.index("g4")); g = gaps(q)
    r = close(q, lambda gap: dict(insert=removed, before="g5")); return bool(g) and r["closed"], f"removed step flagged ({len(g)} gap(s)); graph closed with {len(r['asked'])} question(s)"
def resonance():
    from resonate import beat_hz
    return beat_hz([1] * 13, [1] * 13) == 0.0, "no beats when attention matches"
def run_all():
    return [_check(n, f) for n, f in (("versions agree", versions), ("wf13d table integrity", wf13d_table), ("ant locks (empty grid)", ant), ("consent default-deny", consent), ("meta-only policy", meta_only),
                                      ("distance from coherence", coherence), ("mirror + tesseract", mirror), ("handoff gap detection", handoff), ("resonance", resonance))]
