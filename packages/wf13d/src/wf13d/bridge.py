# SPDX-License-Identifier: Apache-2.0
"""WF-13D bridge arithmetic, bit-packed. One address = 18-bit int: c(5) | t(6) | s(7). Everything below is masks, shifts and popcounts.
Verified against the wf13d MCP tool (10 live addresses) and an independent reference over all 2^18 addresses (test_bridge.py)."""
from functools import lru_cache

CLASSES = ["REPAIR:FixRecord", "SYMPTOM:ProblemStatement", "RECOVERY:ExperimentSpec", "DRIFT:ContextMap", "BUILD:Artifact", "TINKER:ExperimentLog", "VENTURE:DecisionRecord", "DREAM:ProblemStatement",
           "INCIDENT:Postmortem", "TRIAGE:ObservationLog", "TURNAROUND:SystemChangeRecord", "DECLINE:EvidenceLedger", "PROJECT:Decomposition", "PROTOTYPE:ExperimentSpec", "ENTERPRISE:OperatingSystem", "FRONTIER:QuestionRegister",
           "CLARIFY:DecisionRecord", "CONFUSION:QuestionRegister", "RETRAIN:SystemChangeRecord", "IDENTITY:PrincipleRecord", "COMPOSE:Artifact", "SPARK:ProblemStatement", "MASTERY:LearningRecord", "VOCATION:PrincipleRecord",
           "DISPUTE:PerspectiveMatrix", "FRICTION:ObservationLog", "REFORM:SystemChangeRecord", "CULTURE:ContextMap", "CAMPAIGN:Artifact", "EXPLORATION:ExperimentSpec", "INSTITUTION:OperatingSystem", "MOVEMENT:PrincipleRecord"]
CLASS = [c.split(":")[0] for c in CLASSES]; CRYSTAL = [c.split(":")[1] for c in CLASSES]
SUBS = ("WHO", "WHAT", "WHERE", "WHEN", "WHY", "HOW")                      # s bits 6..1 (MSB first), tempo = bit 0 (1 = U)
SB = {n: 1 << (6 - i) for i, n in enumerate(SUBS)}; U = 1
BASE = ("WHAT", "WHY", "WHO", "WHERE", "WHEN", "HOW")
TF = (("ID", "AR"), ("CL", "CP"), ("RV", "IR"), ("SO", "MU"), ("ER", "EP"), ("PF", "PB"))   # t bits 5..0, MSB first
TB = [1 << (5 - i) for i in range(6)]
AR, CP, IR, MU, EP, PB = TB                                                # masks in t
DOMAIN, SCOPE, MODE, HORIZON, DEF = 16, 8, 4, 2, 1                         # masks in c

def pack(c, t, s): assert 0 <= c < 32 and 0 <= t < 64 and 0 <= s < 128; return c << 13 | t << 7 | s
def unpack(a): return a >> 13 & 31, a >> 7 & 63, a & 127

@lru_cache(maxsize=None)
def analyze(a):
    c, t, s = unpack(a); gaps = [n for n in SUBS if not s & SB[n]]; known = [n for n in SUBS if s & SB[n]]; tempoU = s & U
    order = list(BASE)
    for cond, name in ((t & CP, "HOW"), (t & MU, "WHO"), (t & PB, "WHERE"), (tempoU, "WHEN"), (c & DEF, "WHAT")):        # pull-to-front, applied in this order
        if cond: order.remove(name); order.insert(0, name)
    ask = [n for n in order if not s & SB[n]]
    max_q = 1 if tempoU else (2 if len(gaps) > 3 else 3)
    where_res = None
    if t & PB and not s & SB["WHERE"]: where_res = ("jurisdiction" if c & SCOPE else ("site" if not c & DOMAIN else "locale"))
    far, undefined, no_what, no_why = c & HORIZON, c & DEF, not s & SB["WHAT"], not s & SB["WHY"]
    path = ["D01", "D02", "D03"]
    if undefined or no_what: path += ["D04", "D05"]
    if far or t & MU: path += ["D06", "D07"]
    if t & EP or no_why: path += ["D08"]
    if t & IR: path += ["D09"]
    path += ["D10"]
    if t & AR or t & CP: path += ["D11"]
    if far: path += ["D12", "D13"]
    stops = []
    if t & IR: stops.append("S2")
    if t & EP and t & IR: stops.append("S3")
    if tempoU and len(gaps) >= 4: stops.append("S4")
    if c & SCOPE and t & MU and t & IR: stops.append("S6")
    crystal = CRYSTAL[c]
    return dict(c=CLASS[c], t=".".join(TF[i][1 if t & TB[i] else 0] for i in range(6)), s="".join("1" if s & SB[n] else "0" for n in SUBS) + ("U" if tempoU else "D"),
                known=known, ask=ask, max_q=max_q, where_res=where_res, path=path, stops=stops, out=(crystal if crystal == "ProblemStatement" else "ProblemStatement>" + crystal),
                ready=round(len(known) / 6, 3), key=f"{c:02d}.{t:02d}.{s:03d}")

class State:
    """Forward-only state for one idea. Bits are set only from a human statement or confirmed restatement; 'idk' = explicit unknown + ASSUMPTION (counts as set so it is not re-asked: UNVERIFIED against the tool)."""
    def __init__(self, c=0, t=0, s=0): self.a, self.A, self.idk, self.log = pack(c, t, s), 0, set(), []
    def step(self, delta, source="human"):
        c, t, s = unpack(self.a)
        if "c" in delta: c = delta["c"]
        if "t" in delta: t = delta["t"]
        if "tempo" in delta: s = (s & ~U) | (1 if delta["tempo"] else 0)
        for name, v in delta.get("bits", {}).items():
            if name not in SB: raise ValueError(f"unknown bit {name}")
            if v == 1 or v == "idk":
                if source != "human": raise PermissionError(f"bit {name} may only be set from what the human said or confirmed, not by {source}")
                s |= SB[name]
                if v == "idk": self.idk.add(name); self.A += 1
            elif v == 0: s &= ~SB[name]; self.idk.discard(name); self.log.append(("RETRACT", name))       # 0 on a set bit = explicit human retraction
        self.A += len(delta.get("A", [])); self.a = pack(c, t, s); return self
    def view(self): return analyze(self.a)
    def line(self):
        v = self.view(); return f"WF13D {v['key']} t={v['t']} s={v['s']} ready={v['ready']} ask={','.join(v['ask']) or '-'} max_q={v['max_q']} out={v['out']} stops={','.join(v['stops']) or '-'} A={self.A}"
