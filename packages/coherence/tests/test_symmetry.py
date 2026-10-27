# SPDX-License-Identifier: Apache-2.0
import itertools, unittest
from coherence.symmetry import *

class FourPoints(unittest.TestCase):
    def test_there_are_384_symmetries_and_all_preserve_distance(self):
        G = symmetries(); self.assertEqual(len(G), 384)
        for g in G[::7]:
            for a, b in itertools.combinations(range(16), 2): self.assertEqual(hamming(apply(g, a), apply(g, b)), hamming(a, b))
        self.assertEqual(len({tuple(apply(g, v) for v in range(16)) for g in G}), 384)                    # all distinct as maps of the 16 vertices
    def test_the_four_points_are_mutually_equidistant_and_so_is_the_dual_set(self):
        self.assertTrue(equidistant(COHERENT_FOUR)); self.assertTrue(equidistant(dual(COHERENT_FOUR))); self.assertEqual(hamming(COHERENT_FOUR[0], COHERENT_FOUR[1]), 2)
        self.assertEqual(set(COHERENT_FOUR) | set(dual(COHERENT_FOUR)), {v for v in range(16) if bin(v).count("1") % 2 == 0})       # together: the 8 even-weight vertices
    def test_every_ordering_of_the_four_points_is_realised_by_a_cube_symmetry(self):
        s = stabilizer(COHERENT_FOUR); self.assertEqual(len(s), 24); self.assertEqual(induced_permutations(COHERENT_FOUR), set(itertools.permutations(range(4))))
    def test_orbit_stabilizer_arithmetic_is_consistent(self):
        self.assertEqual(len(orbit(COHERENT_FOUR)) * len(stabilizer(COHERENT_FOUR)), 384); self.assertEqual(len(orbit(COHERENT_FOUR)), 16)
    def test_an_unbalanced_set_does_not_have_this_symmetry(self):
        bad = (0b0000, 0b0001, 0b0011, 0b0111); self.assertFalse(equidistant(bad)); self.assertLess(len(induced_permutations(bad)), 24)
if __name__ == "__main__": unittest.main()
