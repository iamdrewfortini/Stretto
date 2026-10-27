# SPDX-License-Identifier: Apache-2.0
"""Symmetry of the 4-cube and of the four-point coherence set. A symmetry permutes the four axes and flips any subset of them (4! * 2^4 = 384 of them) and preserves every Hamming distance.
Four vertices that are all the same distance apart form a regular tetrahedron in 4-space; the cube's symmetries realise EVERY ordering of those four points. Standard library only."""
import itertools

COHERENT_FOUR = (0b0000, 0b0011, 0b0101, 0b0110)          # pairwise Hamming distance 2: a regular tetrahedron
def hamming(a, b): return bin(a ^ b).count("1")
def symmetries(): return [(p, f) for p in itertools.permutations(range(4)) for f in range(16)]
def apply(sym, v):
    perm, flip = sym; bits = [(v >> (3 - i)) & 1 for i in range(4)]; r = 0
    for i in range(4): r = (r << 1) | bits[perm[i]]
    return r ^ flip
def equidistant(points): return len({hamming(a, b) for a, b in itertools.combinations(points, 2)}) == 1
def dual(points): return tuple(15 ^ v for v in points)
def stabilizer(points): s = set(points); return [g for g in symmetries() if {apply(g, v) for v in points} == s]
def induced_permutations(points): return {tuple(points.index(apply(g, v)) for v in points) for g in stabilizer(points)}
def orbit(points): return {frozenset(apply(g, v) for v in points) for g in symmetries()}
