# SPDX-License-Identifier: Apache-2.0
"""Computes the distance from coherence D for a reference 3-node cluster from commitment ratios. Numbers are a measured example, not a benchmark."""
import statistics
from wf13d.bridge import State, SUBS
from coherence.metrics import *
from coherence.swarm import langton, seed_from_address, escape_direction
# Measured 2026-10-26 (pve inventory): commitment ratio = allocated / capacity per node
nodes = ["node-a", "node-b", "node-c"]; cpu = [14/24, 25/12, 80/64]; ram = [20.5/31.2, 27.0/31.2, 89.0/125.6]
press = {"cpu": 119/100, "ram": 136.5/188.1}                     # cluster commitment ratios = how hard each resource is pushed
st = State(30, 62); st.step({"bits": {"WHAT": 1, "WHY": 1, "HOW": 1}})                    # the owner stated what, why and how in this conversation
gaps = {"speed": None, "energy": None, "balance": balance_gap({"cpu": cpu, "ram": ram}, press), "scale": None, "intent": intent_gap(len(st.view()["known"]))}
d = distance(gaps)
print("WF13D:", st.line()); print("gaps:", {k: (round(v, 4) if v is not None else "NOT MEASURED") for k, v in gaps.items()})
print("D >= %.4f  (lower bound; missing: %s)" % (d["D"], ", ".join(d["missing"]))); print("share of D^2:", {k: f"{100*v/d['D']**2:.1f}%" for k, v in d["contribution"].items()})
print("Jain cpu %.4f ram %.4f" % (jain(cpu), jain(ram)))
# Per-neuron (node) signed direction: how far each node's commitment sits from the cluster mean, per resource
for i, n in enumerate(nodes):
    print(f"  neuron {n}: cpu commit {cpu[i]:.2f} ({cpu[i]-statistics.fmean(cpu):+.2f} vs mean), ram commit {ram[i]:.2f} ({ram[i]-statistics.fmean(ram):+.2f}) -> " + ("SHED cpu" if cpu[i] > 1.2 * statistics.fmean(cpu) else "ABSORB cpu" if cpu[i] < 0.8 * statistics.fmean(cpu) else "hold"))
EFF = {"ask-human": {"intent": -1/6}, "migrate-guest (class B)": {"balance": -0.06}}                # ASSUMED priors: one answered bit = 1/6; a migration removes ~half the measured imbalance over a few moves
print("direction (assumed effects, per unit cost):", direction(gaps, EFF, {"ask-human": 0.5, "migrate-guest (class B)": 3.0}))
r = langton(10000, seed_from_address(st.view()["key"]), extra=400); print("this idea's ant (seeded from its WF-13D address", st.view()["key"], "): highway", r["onset"], r["vector"], escape_direction(r["vector"]))
print("ask next (<= max_q=%d):" % st.view()["max_q"], st.view()["ask"][:st.view()["max_q"]])
