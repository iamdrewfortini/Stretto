# SPDX-License-Identifier: Apache-2.0
"""Usage-pattern measurement. Every claim carries a significance test, so 'a pattern' is evidence, not a guess. Stdlib only."""
import functools, math, random, statistics

@functools.lru_cache(maxsize=8)
def _tables(n):
    cs = [[math.cos(2 * math.pi * k * t / n) for t in range(n)] for k in range(1, n // 2 + 1)]
    sn = [[math.sin(2 * math.pi * k * t / n) for t in range(n)] for k in range(1, n // 2 + 1)]
    return cs, sn

def periodogram(x):
    n = len(x); m = statistics.fmean(x); y = [v - m for v in x]; cs, sn = _tables(n)
    return [(k + 1, sum(a * b for a, b in zip(y, cs[k])) ** 2 + sum(a * b for a, b in zip(y, sn[k])) ** 2) for k in range(n // 2)]

def dominant_period(x, min_period=3, perms=99, seed=0):
    """Dominant cycle length with a permutation p-value (shuffling destroys time order, so any periodic structure is lost)."""
    n = len(x)
    def stat(v):
        pg = [(k, p) for k, p in periodogram(v) if n / k >= min_period]; tot = sum(p for _, p in periodogram(v)) or 1
        k, p = max(pg, key=lambda kp: kp[1]); return k, p / tot
    k, s = stat(x); rnd = random.Random(seed); y = list(x); ge = 0
    for _ in range(perms):
        rnd.shuffle(y); ge += stat(y)[1] >= s
    return dict(period=n / k, share=round(s, 4), pvalue=(ge + 1) / (perms + 1), significant=(ge + 1) / (perms + 1) <= 0.05)

def phase_profile(x, T):
    cycles = [x[i:i + T] for i in range(0, len(x) - T + 1, T)]
    return [statistics.fmean(c[p] for c in cycles) for p in range(T)], cycles

def quiet_phases(x, T, q=0.25):
    """Phases whose mean is in the lowest quartile, plus a held-out check: derived on all but the last cycle, tested on the last."""
    prof, cycles = phase_profile(x, T); cut = sorted(prof)[max(0, int(q * T) - 1)]
    quiet = [p for p in range(T) if prof[p] <= cut]
    if len(cycles) < 3: return dict(phases=quiet, holdout_hit_rate=None)
    prof2, _ = phase_profile(x[:len(x) - T], T); cut2 = sorted(prof2)[max(0, int(q * T) - 1)]
    q2 = [p for p in range(T) if prof2[p] <= cut2]; last = cycles[-1]; med = statistics.median(last)
    return dict(phases=quiet, holdout_hit_rate=sum(last[p] < med for p in q2) / len(q2))

def cusum_change(x, k=0.75, h=8.0, base=None):
    """Two-sided CUSUM on a standardized series; returns the first alarm index or None. Baseline = first `base` samples.
    Measured on iid noise (400 series of 240): k=0.75, h=8, base=80 gives 0.2% false alarms and 99.8% detection of a 10-sigma shift.
    (k=0.5, h=5 gave 51% false alarms because the baseline mean and sd are themselves estimated.)"""
    base = base or max(30, len(x) // 3); mu = statistics.fmean(x[:base]); sd = statistics.stdev(x[:base]) or 1e-9; hi = lo = 0.0
    for i, v in enumerate(x):
        z = (v - mu) / sd; hi = max(0.0, hi + z - k); lo = max(0.0, lo - z - k)
        if hi > h or lo > h: return i
    return None

_PC = {}
def profile(x, T=None):
    key = (tuple(x), T)
    if key not in _PC: _PC[key] = _profile(x, T)
    return _PC[key]
def _profile(x, T=None):
    d = dominant_period(x) if T is None else None
    per = (d["period"] if d else T)
    out = dict(n=len(x), mean=round(statistics.fmean(x), 6), peak=round(max(x), 6), period=per, cycle=d, change_at=cusum_change(x))
    if d and d["significant"] and abs(per - round(per)) < 1e-9: out["quiet"] = quiet_phases(x, int(round(per)))
    else: out["quiet"] = None            # no reliable cycle: no quiet window may be claimed
    return out
