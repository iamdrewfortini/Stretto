# SPDX-License-Identifier: Apache-2.0
import math, random, unittest
from coherence.mirror import *

U = [1.0] * 13
def spike(i): v = [0.0] * 13; v[i] = 1.0; return v
class Mirror(unittest.TestCase):
    def test_identical_attention_is_fully_coherent_disjoint_is_zero(self):
        self.assertAlmostEqual(mirror_coherence(U, U), 1.0); self.assertAlmostEqual(mirror_coherence(spike(0), spike(12)), 0.0, places=9); self.assertAlmostEqual(mirror_coherence(spike(3), spike(3)), 1.0)
    def test_symmetric_bounded_and_monotone_in_overlap(self):
        r = random.Random(1)
        for _ in range(200):
            a, b = [r.random() + 0.01 for _ in range(13)], [r.random() + 0.01 for _ in range(13)]; c = mirror_coherence(a, b)
            self.assertAlmostEqual(c, mirror_coherence(b, a)); self.assertTrue(0.0 <= c <= 1.0); self.assertTrue(jsd(a, b) <= math.log(2) + 1e-12)
        h = spike(5); m1 = [0.0] * 13; m1[5], m1[6] = 0.8, 0.2; m2 = [0.0] * 13; m2[5], m2[6] = 0.4, 0.6; self.assertGreater(mirror_coherence(h, m1), mirror_coherence(h, m2))
    def test_needs_thirteen_dimensions_and_positive_mass(self):
        with self.assertRaises(ValueError): mirror_coherence([1] * 12, [1] * 12)
        with self.assertRaises(ValueError): mirror_coherence([0] * 13, U)
    def test_26_numbers_sum_to_two(self): v = vector26(U, spike(2)); self.assertEqual(len(v), 26); self.assertAlmostEqual(sum(v), 2.0)
    def test_conscious_intent_versus_unknown(self):
        h = [0.0] * 13; h[0], h[1], h[7] = 0.5, 0.3, 0.2; s = intent_split(h, confirmed=[0, 1]); self.assertAlmostEqual(s["conscious"], 0.8); self.assertAlmostEqual(s["unknown"], 0.2); self.assertAlmostEqual(s["conscious"] + s["unknown"], 1.0)
    def test_per_dimension_gap_locates_the_disagreement(self): g = per_dimension_gap(U, [1.0] * 12 + [5.0]); self.assertEqual(g.index(max(g)), 12)
class Rhythm(unittest.TestCase):
    def test_locked_rhythms_score_one_unrelated_near_zero(self):
        t = [i * 7.0 for i in range(400)]; self.assertAlmostEqual(phase_locking(t, [x + 3.0 for x in t], 60.0), 1.0, places=9)           # constant lag = still locked
        r = random.Random(2); u = [r.random() * 1000 for _ in range(400)]; self.assertLess(phase_locking(t, u, 60.0), 0.15)
    def test_paired_input_required(self):
        with self.assertRaises(ValueError): phase_locking([1.0], [], 10.0)
class Tesseract(unittest.TestCase):
    def test_face_counts_and_euler_characteristic(self):
        c = hypercube_counts(4); self.assertEqual(c, {0: 16, 1: 32, 2: 24, 3: 8, 4: 1}); self.assertEqual(sum((-1) ** k * v for k, v in c.items() if k < 4), 0)           # 16-32+24-8 = 0
        self.assertEqual(hypercube_counts(3), {0: 8, 1: 12, 2: 6, 3: 1})
    def test_state_level_and_flips(self):
        bits, missing = axes_bits(dict(mind_clock=0.9, mind_memory=0.5, body_clock=None, body_memory=0.8)); self.assertEqual(bits, (1, 0, 0, 1)); self.assertEqual(missing, ["body_clock"])
        s = tesseract_state(bits); self.assertEqual((s["vertex"], s["level"]), (9, 2)); self.assertEqual(s["flips"], ["mind_memory", "body_clock"])
        self.assertEqual(tesseract_state((1, 1, 1, 1))["flips"], []); self.assertEqual(tesseract_state((0, 0, 0, 0))["level"], 0)
    def test_each_vertex_has_exactly_four_neighbours_and_16_vertices_are_distinct(self):
        self.assertTrue(all(len(hamming_neighbors(v)) == 4 for v in range(16))); self.assertEqual(len({tesseract_state(tuple((v >> (3 - i)) & 1 for i in range(4)))["vertex"] for v in range(16)}), 16)
    def test_one_flip_per_move_reaches_coherence_in_level_complement_steps(self):
        for v in range(16):
            bits = tuple((v >> (3 - i)) & 1 for i in range(4)); steps = 0
            while tesseract_state(bits)["flips"]:
                ax = AXES4.index(tesseract_state(bits)["flips"][0]); bits = bits[:ax] + (1,) + bits[ax + 1:]; steps += 1
            self.assertEqual(steps, 4 - sum(tuple((v >> (3 - i)) & 1 for i in range(4))))
if __name__ == "__main__": unittest.main()
