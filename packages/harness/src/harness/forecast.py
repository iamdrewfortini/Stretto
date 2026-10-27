# SPDX-License-Identifier: Apache-2.0
"""Training step: additive Holt-Winters fitted on the first 70%, scored on a true one-step holdout against the best simple baseline. Stdlib only."""
import statistics

def hw_run(x, T, a, b, g, upto=None):
    """Runs the filter over x; returns list of one-step-ahead forecasts for t>=T (forecast[t] predicts x[t] from x[:t])."""
    L = statistics.fmean(x[:T]); B = (statistics.fmean(x[T:2 * T]) - L) / T if len(x) >= 2 * T else 0.0; S = [x[i] - L for i in range(T)]; f = {}
    for t in range(T, len(x) if upto is None else upto):
        f[t] = L + B + S[t % T]; e = x[t] - f[t]
        Lp = L; L = L + B + a * e; B = B + a * b * e; S[t % T] = S[t % T] + g * (1 - a) * e
    return f

def mae(f, x, lo, hi):
    ks = [t for t in f if lo <= t < hi]; return statistics.fmean(abs(x[t] - f[t]) for t in ks) if ks else float("inf")

def train(x, T, margin=0.10):
    """Fit on [0,0.7n), evaluate on [0.7n,n). Accept only if the holdout MAE beats the best of {mean, last value, seasonal naive} by `margin`."""
    n = len(x)
    if n < 3 * T: return dict(accepted=False, reason=f"need >= {3*T} samples (3 cycles), have {n}")
    cut = int(0.7 * n); best = None
    for a in (0.05, 0.1, 0.2, 0.3, 0.5):
        for b in (0.0, 0.05, 0.2):
            for g in (0.05, 0.1, 0.3, 0.6):
                f = hw_run(x, T, a, b, g, upto=cut); e = mae(f, x, T, cut)
                if best is None or e < best[0]: best = (e, a, b, g)
    _, a, b, g = best; f = hw_run(x, T, a, b, g); m_model = mae(f, x, cut, n)
    mu = statistics.fmean(x[:cut])
    base = {"mean": statistics.fmean(abs(x[t] - mu) for t in range(cut, n)), "last": statistics.fmean(abs(x[t] - x[t - 1]) for t in range(cut, n)), "seasonal_naive": statistics.fmean(abs(x[t] - x[t - T]) for t in range(cut, n))}
    nb = min(base, key=base.get); skill = 1 - m_model / base[nb]
    return dict(accepted=skill >= margin, skill=round(skill, 4), model_mae=round(m_model, 5), best_baseline=nb, baseline_mae=round(base[nb], 5), params=dict(alpha=a, beta=b, gamma=g), holdout=n - cut)

def predict(x, T, params, h):
    """h-step-ahead forecast by running the filter and rolling the seasonal profile forward."""
    f = hw_run(x, T, params["alpha"], params["beta"], params["gamma"])
    L = statistics.fmean(x[-T:]); prof = [statistics.fmean(x[i::T]) - statistics.fmean(x) for i in range(T)]; n = len(x)
    return [L + prof[(n + i) % T] for i in range(h)]
