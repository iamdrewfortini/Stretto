# SPDX-License-Identifier: Apache-2.0
"""Dimensional distillation: compress a high-dimensional signal vector (external telemetry across levels, or a cell's internal state) to k dimensions.
PCA by power iteration with deflation (exact identity for the error), plus the Johnson-Lindenstrauss bound for distance-preserving random projections. Stdlib only."""
import math, random

def _mean(X): n = len(X); return [sum(r[j] for r in X) / n for j in range(len(X[0]))]
def _cov(Xc):
    n, d = len(Xc), len(Xc[0]); return [[sum(r[i] * r[j] for r in Xc) / (n - 1) for j in range(d)] for i in range(d)]
def _matvec(M, v): return [sum(a * b for a, b in zip(row, v)) for row in M]
def pca(X, var_target=0.95, kmax=None, iters=500, seed=0):
    n, d = len(X), len(X[0]); mu = _mean(X); Xc = [[a - b for a, b in zip(r, mu)] for r in X]; C = _cov(Xc); total = sum(C[i][i] for i in range(d)); rnd = random.Random(seed)
    comps, vals, M = [], [], [row[:] for row in C]
    for _ in range(kmax or d):
        v = [rnd.gauss(0, 1) for _ in range(d)]
        for _ in range(iters):
            w = _matvec(M, v); nw = math.sqrt(sum(x * x for x in w))
            if nw < 1e-15: break
            v = [x / nw for x in w]
        lam = sum(a * b for a, b in zip(_matvec(M, v), v))
        if lam <= 1e-12 * max(total, 1e-12): break
        comps.append(v); vals.append(lam); M = [[M[i][j] - lam * v[i] * v[j] for j in range(d)] for i in range(d)]
        if sum(vals) / total >= var_target: break
    return dict(mean=mu, comps=comps, eig=vals, k=len(comps), d=d, n=n, retained=sum(vals) / total, total=total)
def project(m, x): xc = [a - b for a, b in zip(x, m["mean"])]; return [sum(a * b for a, b in zip(xc, c)) for c in m["comps"]]
def reconstruct(m, z): return [m["mean"][j] + sum(zi * c[j] for zi, c in zip(z, m["comps"])) for j in range(m["d"])]
def recon_error(m, X): return sum(sum((a - b) ** 2 for a, b in zip(x, reconstruct(m, project(m, x)))) for x in X)

def jl_min_dim(n, eps): return math.ceil(4 * math.log(n) / (eps ** 2 / 2 - eps ** 3 / 3))
def random_projection(d, k, seed=0): rnd = random.Random(seed); return [[rnd.gauss(0, 1 / math.sqrt(k)) for _ in range(d)] for _ in range(k)]
def rp_apply(R, x): return [sum(a * b for a, b in zip(row, x)) for row in R]

def compression(m): return dict(from_dims=m["d"], to_dims=m["k"], ratio=round(m["d"] / m["k"], 2), variance_retained=round(m["retained"], 4))
