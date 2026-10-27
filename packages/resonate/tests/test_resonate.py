# SPDX-License-Identifier: Apache-2.0
import random, unittest
from resonate import *

def simulate(profile, truth, n, rnd):
    picks = []
    for _ in range(n):
        m = profile.choose(); picks.append(m); p, secs = truth[m]; profile.record(m, rnd.random() < p, secs * (0.8 + 0.4 * rnd.random()))
    return picks
class Modality(unittest.TestCase):
    TRUTH = {"number": (0.3, 12), "bar": (0.5, 6), "sentence": (0.6, 9), "analogy": (0.9, 5), "tone": (0.4, 4), "pulse": (0.3, 4)}
    def test_learns_the_modality_that_works_for_this_person(self):
        picks = simulate(Profile("a", seed=1), self.TRUTH, 400, random.Random(1)); late = picks[-100:]; self.assertGreaterEqual(late.count("analogy") / 100, 0.6)
    def test_two_people_learn_different_answers_and_profiles_are_separate(self):
        other = dict(self.TRUTH, analogy=(0.2, 15), number=(0.95, 3)); pa, pb = Profile("a", 2), Profile("b", 3); simulate(pa, self.TRUTH, 400, random.Random(4)); simulate(pb, other, 400, random.Random(5))
        self.assertEqual(pa.best(), "analogy"); self.assertEqual(pb.best(), "number"); self.assertNotEqual(pa.stats, pb.stats)
    def test_respects_missing_senses(self):
        p = Profile("a", 1); [p.record("tone", True, 1) for _ in range(30)]; [p.record("pulse", True, 1) for _ in range(30)]
        self.assertTrue(all(p.choose(can_hear=False, can_feel=False) not in ("tone", "pulse") for _ in range(100)))
class Sound(unittest.TestCase):
    def test_no_beats_when_attention_matches_and_beats_grow_with_mismatch(self):
        u = [1.0] * 13; s = lambda i: [1.0 if k == i else 0.0 for k in range(13)]
        self.assertEqual(beat_hz(u, u), 0.0); self.assertEqual(beat_hz(s(4), s(4)), 0.0); self.assertLess(beat_hz(s(4), s(5)), beat_hz(s(4), s(9))); self.assertAlmostEqual(freq_hz(s(12)) / freq_hz(s(0)), 2.0)
    def test_tone_is_monotone_and_bounded(self):
        a, b, c = tone_for_D(0.0), tone_for_D(0.5), tone_for_D(1.0); self.assertGreater(a["freq_hz"], b["freq_hz"]); self.assertGreater(b["freq_hz"], c["freq_hz"]); self.assertLess(a["pulse_hz"], c["pulse_hz"])
        self.assertEqual(tone_for_D(-3)["freq_hz"], a["freq_hz"]); self.assertEqual(tone_for_D(9)["freq_hz"], c["freq_hz"])
class Explain(unittest.TestCase):
    def test_names_the_largest_term_at_every_level(self):
        contrib = {"intent": 0.05, "balance": 0.003}
        for lvl in ("math", "plain", "analogy"): self.assertIn("intent", explain(contrib, 0.23, lvl))
        self.assertIn("close to", explain(contrib, 0.1)); self.assertIn("far from", explain(contrib, 0.6))
if __name__ == "__main__": unittest.main()
