# SPDX-License-Identifier: Apache-2.0
import math, os, subprocess, sys, unittest
from resonate.keyboard import *

class Frequencies(unittest.TestCase):
    def test_the_standard_anchor_pitches(self):
        self.assertAlmostEqual(key_freq(49), 440.0); self.assertAlmostEqual(key_freq(1), 27.5); self.assertAlmostEqual(key_freq(88), 4186.0090448, places=6); self.assertAlmostEqual(key_freq(40), 261.6255653, places=6)       # middle C
        self.assertEqual((key_name(1), key_name(4), key_name(40), key_name(49), key_name(88)), ("A0", "C1", "C4", "A4", "C8"))
    def test_every_half_step_is_the_same_ratio_and_every_twelve_double(self):
        r = 2 ** (1 / 12)
        for n in range(1, 88): self.assertAlmostEqual(key_freq(n + 1) / key_freq(n), r, places=12)
        for n in range(1, 77): self.assertAlmostEqual(key_freq(n + 12) / key_freq(n), 2.0, places=12)
    def test_out_of_range_is_refused(self):
        for bad in (0, 89, -1):
            with self.assertRaises(ValueError): key_freq(bad)
class Layout(unittest.TestCase):
    def test_88_is_3_plus_7_octaves_of_12_plus_1(self):
        g = groups_of_12(); self.assertEqual([len(x) for x in g], [12] * 7 + [4]); self.assertEqual(sum(len(x) for x in g), 88)
        enc = {encode(f, l) for f in FAMILIES for l in range(12)}; self.assertEqual(enc, set(range(4, 88))); self.assertEqual(len(enc), 84); self.assertEqual(sorted(ANCHORS), [1, 2, 3, 88])
        self.assertEqual(len(enc) + len(ANCHORS), 88); self.assertEqual(len(FAMILIES), 7)
    def test_each_family_octave_starts_on_a_c_and_ends_on_a_b(self):
        for i, f in enumerate(FAMILIES): self.assertEqual((key_name(encode(f, 0)), key_name(encode(f, 11))), (f"C{i + 1}", f"B{i + 1}"))
    def test_encode_decode_round_trip_and_anchors(self):
        for f in FAMILIES:
            for l in range(12): d = decode(encode(f, l)); self.assertEqual((d["family"], d["level"]), (f, l))
        self.assertIn("anchor", decode(1)); self.assertIn("anchor", decode(88)); self.assertEqual(len({decode(k).get("anchor") for k in ANCHORS}), 4)
    def test_values_quantize_to_twelve_half_steps(self):
        self.assertEqual([level_for_value(x, 0, 12) for x in (0, 0.9, 1.0, 11.99, 12, 99)], [0, 0, 1, 11, 11, 11]); self.assertEqual(level_for_value(1000, 1, 1000, log=True), 11); self.assertEqual(level_for_value(1, 1, 1000, log=True), 0)
    def test_a_word_is_the_same_key_on_every_run_and_machine(self):
        code = "from resonate.keyboard import key_for_word; print([key_for_word(w) for w in ('coherence','Coherence','handoff','mirror')])"; outs = set()
        for seed in ("0", "1", "2"):
            r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=os.pathsep.join(sys.path))); self.assertEqual(r.returncode, 0, r.stderr[-200:]); outs.add(r.stdout)
        self.assertEqual(len(outs), 1); self.assertEqual(key_for_word("Coherence"), key_for_word("coherence"))
class Rhythm(unittest.TestCase):
    def test_time_signatures(self):
        self.assertEqual([pulses_per_bar(*t) for t in ((4, 4), (3, 4), (6, 8), (7, 8), (12, 8))], [8, 6, 6, 7, 12]); self.assertEqual(grouping(6, 8), [3, 3]); self.assertEqual(grouping(4, 4), [2, 2]); self.assertEqual(grouping(7, 8), [2, 2, 2, 1])
    def test_polyrhythm_cycle_is_lcm_and_the_polygons_share_gcd_vertices(self):
        for a, b in ((3, 4), (2, 3), (4, 6), (5, 7), (6, 9), (12, 8)):
            p = polyrhythm(a, b); self.assertEqual(p["cycle"], a * b // math.gcd(a, b)); self.assertEqual(len(p["shared"]), math.gcd(a, b))
            pa, pb = set(clock_points(a)), set(clock_points(b)); self.assertEqual(len(pa & pb), math.gcd(a, b))                     # the geometric clock agrees with the rhythm
    def test_clock_points_are_a_regular_polygon(self):
        for n in (3, 4, 7, 12):
            pts = clock_points(n); d = [math.dist(pts[i], pts[(i + 1) % n]) for i in range(n)]; self.assertAlmostEqual(max(d), min(d), places=9); self.assertTrue(all(abs(math.hypot(*p) - 1) < 1e-9 for p in pts))
if __name__ == "__main__": unittest.main()
