# SPDX-License-Identifier: Apache-2.0
"""Translating a measurement into a form that lands for THIS person. If the math is not readable to someone, show it another way. The profile is learned from that person's own
comprehension checks, stays on their device, and is never pooled. `sonify` turns the human/machine mismatch into audible beats: no beats means coherent. Standard library only."""
import math, random

MODALITIES = ("number", "bar", "sentence", "analogy", "tone", "pulse")
AUDIO, HAPTIC = {"tone"}, {"pulse"}

class Profile:
    """Per-person modality preference: Beta posterior of 'understood' and an EWMA of seconds-to-understand. Thompson sampling picks the modality with the best expected understanding per second."""
    def __init__(self, person, seed=0): self.person, self.stats, self.secs, self.rnd = person, {m: [1, 1] for m in MODALITIES}, {m: 10.0 for m in MODALITIES}, random.Random(seed)
    def choose(self, can_hear=True, can_feel=True):
        allowed = [m for m in MODALITIES if (can_hear or m not in AUDIO) and (can_feel or m not in HAPTIC)]
        return max(allowed, key=lambda m: self.rnd.betavariate(*self.stats[m]) / max(self.secs[m], 0.5))
    def record(self, modality, understood, seconds):
        w, l = self.stats[modality]; self.stats[modality] = [w + bool(understood), l + (not understood)]; self.secs[modality] = 0.7 * self.secs[modality] + 0.3 * seconds
    def best(self): return max(MODALITIES, key=lambda m: (self.stats[m][0] / sum(self.stats[m])) / self.secs[m])

def centroid(weights):
    """Attention centre of mass over the 13 loop dimensions, in [0, 12]."""
    s = sum(weights); return sum(i * w for i, w in enumerate(weights)) / s
def freq_hz(weights, base_hz=220.0): return base_hz * 2 ** (centroid(weights) / 12)          # one octave across the 13 dimensions
def beat_hz(human, machine, base_hz=220.0): return abs(freq_hz(human, base_hz) - freq_hz(machine, base_hz))
def tone_for_D(D, base_hz=220.0):
    """Pitch rises as the system gets more coherent (D falls); the pulse is slow when coherent and fast when far."""
    D = max(0.0, min(1.0, D)); return dict(freq_hz=base_hz * 2 ** (2 * (1 - D)), pulse_hz=1.0 + 4.0 * D)

def explain(contribution, D, level="plain"):
    """Deterministic wording of D at three reading levels, naming the largest contributor. `contribution` is {axis: share of D squared}."""
    top = max(contribution, key=contribution.get); share = contribution[top] / max(sum(contribution.values()), 1e-12)
    if level == "math": return f"D = {D:.3f}; the largest term is '{top}' at {share:.0%} of D squared."
    if level == "analogy": return ("Like a car whose wheels are nearly aligned: " if D < 0.3 else "Like a car pulling hard to one side: ") + f"most of the pull comes from '{top}'."
    return f"The system is {'close to' if D < 0.3 else 'far from'} balanced (score {D:.2f}). The biggest reason is '{top}', about {share:.0%} of the gap."
