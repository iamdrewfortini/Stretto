# SPDX-License-Identifier: Apache-2.0
"""WF-13D binary lookup table: all 2^18 addresses in 4 bytes each (1,048,576 bytes), language-agnostic (little-endian uint32). Lets a wearable, a browser or a Rust/Kotlin service
read the full bridge arithmetic with one array index and no code port. Layout of each uint32:
  bits  0-9   index of the ask-order permutation (0..719, lexicographic over the six sub-question names)
  bits 10-11  max_q (1..3)
  bits 12-13  where_res (0 none, 1 site, 2 jurisdiction, 3 locale)
  bits 14-17  stops mask (bit14 S2, bit15 S3, bit16 S4, bit17 S6)
  bits 18-30  path mask (bit18 = D01 ... bit30 = D13)
Everything else is derived from the address bits themselves (known from s, ready = known/6, class label from c, t codes from t)."""
import itertools, struct
from wf13d import bridge as B

NAMES = ("WHO", "WHAT", "WHERE", "WHEN", "WHY", "HOW")
PERMS = list(itertools.permutations(NAMES)); PERM_INDEX = {p: i for i, p in enumerate(PERMS)}
WR = {None: 0, "site": 1, "jurisdiction": 2, "locale": 3}; WR_INV = {v: k for k, v in WR.items()}; STOP_BITS = ("S2", "S3", "S4", "S6")

def _order(a):
    """Full pulled-to-front order (before removing known bits), recomputed from the address with the same pull rules as bridge.analyze."""
    c, t, s = B.unpack(a); order = list(B.BASE)
    for cond, name in ((t & B.CP, "HOW"), (t & B.MU, "WHO"), (t & B.PB, "WHERE"), (s & B.U, "WHEN"), (c & B.DEF, "WHAT")):
        if cond: order.remove(name); order.insert(0, name)
    return tuple(order)
def encode(a):
    v = B.analyze(a); w = PERM_INDEX[_order(a)] | v["max_q"] << 10 | WR[v["where_res"]] << 12
    for i, st in enumerate(STOP_BITS): w |= (st in v["stops"]) << (14 + i)
    for p in v["path"]: w |= 1 << (18 + int(p[1:]) - 1)
    return w
def build():
    return b"".join(struct.pack("<I", encode(a)) for a in range(1 << 18))
class Table:
    def __init__(self, blob):
        if len(blob) != 4 << 18: raise ValueError("bad table size")
        self.m = memoryview(blob).cast("I") if struct.pack("=I", 1) == struct.pack("<I", 1) else None
        self.blob = blob
    def word(self, a): return self.m[a] if self.m is not None else struct.unpack_from("<I", self.blob, 4 * a)[0]
    def lookup(self, a):
        w = self.word(a); c, t, s = B.unpack(a); order = PERMS[w & 1023]; known = [n for n in B.SUBS if s & B.SB[n]]
        return dict(c=B.CLASS[c], t=".".join(B.TF[i][1 if t & B.TB[i] else 0] for i in range(6)), s="".join("1" if s & B.SB[n] else "0" for n in B.SUBS) + ("U" if s & B.U else "D"),
                    known=known, ask=[n for n in order if not s & B.SB[n]], max_q=w >> 10 & 3, where_res=WR_INV[w >> 12 & 3], path=[f"D{i + 1:02d}" for i in range(13) if w >> (18 + i) & 1],
                    stops=[st for i, st in enumerate(STOP_BITS) if w >> (14 + i) & 1], out=(B.CRYSTAL[c] if B.CRYSTAL[c] == "ProblemStatement" else "ProblemStatement>" + B.CRYSTAL[c]),
                    ready=round(len(known) / 6, 3), key=f"{c:02d}.{t:02d}.{s:03d}")

def load():
    """The table shipped inside the wf13d distribution (packaged data)."""
    from importlib import resources
    return Table((resources.files("wf13d") / "data" / "wf13d.tbl").read_bytes())
