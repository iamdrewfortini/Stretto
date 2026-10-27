# SPDX-License-Identifier: Apache-2.0
"""The 88-key keyboard as a coordinate system for signals. Equal temperament: key n (1..88) sounds at 440 * 2^((n-49)/12) Hz, so adjacent keys are one half step apart (ratio 2^(1/12)) and every 12 keys double the frequency.
88 = 3 + 7*12 + 1: three keys below the first full octave (A0, A#0, B0), seven full octaves C1..B7 (84 keys), and C8. The seven octaves carry seven signal families; the four leftover keys are four anchors.
Time signatures and polyrhythms map onto a geometric clock (regular polygons on a circle). Standard library only."""
import hashlib, math

A4_KEY, A4_HZ = 49, 440.0
NOTES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
FAMILIES = ("distillation", "decomposition", "digestion", "distribution", "code_quality", "phrases", "words")      # octaves 1..7
ANCHORS = {1: "anchor-1 (A0)", 2: "anchor-2 (A#0)", 3: "anchor-3 (B0)", 88: "anchor-4 (C8)"}

def key_freq(n, a4=A4_HZ):
    if not 1 <= n <= 88: raise ValueError("key must be 1..88")
    return a4 * 2 ** ((n - A4_KEY) / 12)
def key_name(n):
    if not 1 <= n <= 88: raise ValueError("key must be 1..88")
    m = n + 8; return f"{NOTES[m % 12]}{m // 12}"
def groups_of_12():
    """Keys 1..88 in consecutive groups of 12 half steps (the last group holds the remaining 4)."""
    return [list(range(s, min(s + 12, 89))) for s in range(1, 89, 12)]
def encode(family, level):
    """family (one of the seven) and level 0..11 (the half step within its octave) -> key number in 4..87."""
    if family not in FAMILIES or not 0 <= level <= 11: raise ValueError("family or level out of range")
    return 4 + FAMILIES.index(family) * 12 + level
def decode(key):
    if key in ANCHORS: return dict(anchor=ANCHORS[key])
    if not 4 <= key <= 87: raise ValueError("key must be 1..88")
    f, l = divmod(key - 4, 12); return dict(family=FAMILIES[f], level=l, name=key_name(key), hz=key_freq(key))
def level_for_value(x, lo, hi, log=False):
    """Quantize a measurement into one of 12 half steps (0 = lowest, 11 = highest), clamped."""
    if hi <= lo: raise ValueError("hi must exceed lo")
    if log:
        if lo <= 0: raise ValueError("log scale needs lo > 0")
        t = (math.log(max(min(x, hi), lo)) - math.log(lo)) / (math.log(hi) - math.log(lo))
    else: t = (max(min(x, hi), lo) - lo) / (hi - lo)
    return min(11, int(t * 12))
def key_for_word(word, family="words"):
    """Deterministic (sha256, not Python's salted hash): the same word is the same key on every machine and every run."""
    return encode(family, hashlib.sha256(word.lower().encode()).digest()[0] % 12)

# ---- time signatures and polyrhythm on a geometric clock
def pulses_per_bar(num, den):
    """Eighth-note pulses in a bar of num/den (4/4 -> 8, 3/4 -> 6, 6/8 -> 6, 7/8 -> 7). Compound meters (6, 9, 12 over 8) group in threes."""
    return num * 8 // den
def grouping(num, den):
    return [3] * (num // 3) if den == 8 and num % 3 == 0 and num >= 6 else [2] * (num // 2) + ([1] if num % 2 else [])
def clock_points(n):
    """n equally spaced points on the unit circle, starting at 12 o'clock and going clockwise: the vertices of a regular n-gon."""
    return [(round(math.sin(2 * math.pi * k / n), 12), round(math.cos(2 * math.pi * k / n), 12)) for k in range(n)]
def polyrhythm(a, b):
    """a against b over one shared cycle: it repeats after lcm(a, b) pulses, the two polygons share exactly gcd(a, b) vertices, and onsets coincide at those instants."""
    L = a * b // math.gcd(a, b); onsets_a = [k * L // a for k in range(a)]; onsets_b = [k * L // b for k in range(b)]
    return dict(cycle=L, shared=sorted(set(onsets_a) & set(onsets_b)), onsets_a=onsets_a, onsets_b=onsets_b)
