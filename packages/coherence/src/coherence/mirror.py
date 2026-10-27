# SPDX-License-Identifier: Apache-2.0
"""The attention mirror and the four-axis state. Both sides (human, machine) hold a 13-vector of attention over the WF-13D loop dimensions D01..D13: 13 + 13 = 26 numbers.
`mirror_coherence` is 1 - JSD/ln2 between the two distributions (1 = they attend identically). `tesseract_state` reduces four measured yes/no coherence axes to one of the 16 vertices of a 4-cube.
These are measurements of agreement between two attention distributions; nothing here is quantum. Standard library only."""
import cmath, math
from itertools import combinations

def _norm(v):
    s = sum(v)
    if s <= 0: raise ValueError("attention vector must have positive mass")
    return [x / s for x in v]
def kl(p, q): return sum(a * math.log(a / b) for a, b in zip(p, q) if a > 0)
def jsd(p, q):
    p, q = _norm(p), _norm(q); m = [(a + b) / 2 for a, b in zip(p, q)]; return 0.5 * kl(p, m) + 0.5 * kl(q, m)
def mirror_coherence(human, machine):
    """In [0, 1]: 1 when both attend the same way on the 13 dimensions, 0 when their attention is disjoint."""
    if len(human) != 13 or len(machine) != 13: raise ValueError("expected 13 loop dimensions (D01..D13) per side")
    return max(0.0, min(1.0, 1.0 - jsd(human, machine) / math.log(2)))
def per_dimension_gap(human, machine): h, m = _norm(human), _norm(machine); return [round(abs(a - b), 6) for a, b in zip(h, m)]
def intent_split(human, confirmed):
    """Share of the person's attention that sits on dimensions they have consciously confirmed (WF-13D bits they said) versus everything else (unknown to the system)."""
    h = _norm(human); c = sum(h[i] for i in confirmed); return dict(conscious=round(c, 6), unknown=round(1 - c, 6))
def vector26(human, machine): return _norm(human) + _norm(machine)

# ---- rhythm agreement
def phases(times, period): return [2 * math.pi * ((t % period) / period) for t in times]
def phase_locking(times_a, times_b, period):
    """Phase-locking value of paired timestamps: mean resultant length of the phase differences. 1 = perfectly locked, near 0 = unrelated."""
    pa, pb = phases(times_a, period), phases(times_b, period)
    if not pa or len(pa) != len(pb): raise ValueError("need equal, non-empty paired timestamps")
    return abs(sum(cmath.exp(1j * (a - b)) for a, b in zip(pa, pb)) / len(pa))

# ---- the 4-cube
def hypercube_counts(n):
    """Number of k-faces of an n-cube: C(n,k) * 2^(n-k). For n=4: 16 vertices, 32 edges, 24 squares, 8 cubes, 1 tesseract."""
    return {k: math.comb(n, k) * 2 ** (n - k) for k in range(n + 1)}
AXES4 = ("mind_clock", "mind_memory", "body_clock", "body_memory")
def axes_bits(measures, threshold=0.7):
    """measures: {axis: value in [0,1]} for the four axes. A bit is 1 (coherent) when the measure reaches the threshold. Unmeasured axes are None and count as 0 with a flag."""
    bits = tuple(int((measures.get(a) is not None) and measures[a] >= threshold) for a in AXES4); return bits, [a for a in AXES4 if measures.get(a) is None]
def tesseract_state(bits):
    """Vertex index 0..15 (bit order = AXES4, most significant first), coherence level = number of coherent axes, and the single-axis flips (edges of the 4-cube) that move toward all-coherent."""
    if len(bits) != 4: raise ValueError("four axes")
    idx = sum(b << (3 - i) for i, b in enumerate(bits)); return dict(vertex=idx, level=sum(bits), flips=[AXES4[i] for i, b in enumerate(bits) if not b])
def hamming_neighbors(vertex): return sorted(vertex ^ (1 << k) for k in range(4))
