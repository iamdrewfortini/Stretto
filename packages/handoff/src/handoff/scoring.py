# SPDX-License-Identifier: Apache-2.0
"""Step scoring that agrees with itself and stays accurate. Two independent similarity signals between an extracted step and a key step:
  text   - word overlap (misses paraphrases, confuses opposites such as 'remove the belt' and 'refit the belt')
  effect - overlap of what the step REQUIRES, ADDS and REMOVES (sees through wording, separates opposites, but needs the extractor to infer effects)
They are combined with weights and a threshold FITTED on labeled pairs and TESTED on a held-out procedure. Assignment is optimal one-to-one (Hungarian), not greedy. Beyond recall and
precision we also score ORDER (Kendall tau of matched steps) and DEPENDENCY recovery (edge F1), and report the AGREEMENT of the two signals (Cohen's kappa). Standard library only."""
import itertools, math, random
from .procedure import tokens, dag, Procedure

def signature(s): return frozenset([("req", f) for f in s.get("requires", [])] + [("add", f) for f in s.get("adds", [])] + [("rem", f) for f in s.get("removes", [])])
def jaccard(a, b): u = a | b; return len(a & b) / len(u) if u else 0.0
def sim_text(a, b): return jaccard(tokens(a["text"]), tokens(b["text"]))
def sim_effect(a, b): return jaccard(signature(a), signature(b))
def sim(a, b, w): return w * sim_text(a, b) + (1 - w) * sim_effect(a, b)

def hungarian_max(S):
    """Optimal one-to-one assignment maximizing total similarity. Returns [(row, col)]."""
    n = len(S); m = len(S[0]) if n else 0; N = max(n, m); INF = 1e18
    cost = [[(-S[i][j] if i < n and j < m else 0.0) for j in range(N)] for i in range(N)]
    u, v, p, way = [0.0] * (N + 1), [0.0] * (N + 1), [0] * (N + 1), [0] * (N + 1)
    for i in range(1, N + 1):
        p[0] = i; j0 = 0; minv = [INF] * (N + 1); used = [False] * (N + 1)
        while True:
            used[j0] = True; i0 = p[j0]; delta = INF; j1 = 0
            for j in range(1, N + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]: minv[j] = cur; way[j] = j0
                    if minv[j] < delta: delta = minv[j]; j1 = j
            for j in range(N + 1):
                if used[j]: u[p[j]] += delta; v[j] -= delta
                else: minv[j] -= delta
            j0 = j1
            if p[j0] == 0: break
        while True:
            j1 = way[j0]; p[j0] = p[j1]; j0 = j1
            if j0 == 0: break
    return [(p[j] - 1, j - 1) for j in range(1, N + 1) if p[j] - 1 < n and j - 1 < m]
def greedy(S, thr):
    pairs = sorted(((S[i][j], i, j) for i in range(len(S)) for j in range(len(S[0]))), reverse=True); ui, uj, out = set(), set(), []
    for s, i, j in pairs:
        if s >= thr and i not in ui and j not in uj: out.append((i, j)); ui.add(i); uj.add(j)
    return out

def match(extracted, key, w, thr, optimal=True):
    """extracted, key: lists of step dicts. Returns {key_index: extracted_index} for matches scoring at least thr."""
    S = [[sim(k, e, w) for e in extracted] for k in key]
    if not key or not extracted: return {}
    pairs = hungarian_max(S) if optimal else greedy(S, thr)
    return {i: j for i, j in pairs if S[i][j] >= thr}
def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0; r = tp / (tp + fn) if tp + fn else 0.0; return p, r, (2 * p * r / (p + r) if p + r else 0.0)

def fit(train):
    """train: list of (extracted, key, truth{key_i: ext_j}). Grid-search the text weight and threshold that maximize pair-decision F1 over ALL (key, extracted) pairs."""
    best = (-1, 0.5, 0.5)
    for w in [x / 10 for x in range(11)]:
        for thr in [x / 20 for x in range(1, 20)]:
            tp = fp = fn = 0
            for ext, key, truth in train:
                for i, k in enumerate(key):
                    for j, e in enumerate(ext):
                        pred = sim(k, e, w) >= thr; pos = truth.get(i) == j
                        tp += pred and pos; fp += pred and not pos; fn += (not pred) and pos
            f1 = prf(tp, fp, fn)[2]
            if f1 > best[0] + 1e-12: best = (f1, w, thr)
    return dict(f1=best[0], w_text=best[1], threshold=best[2])
def pair_scores(data, w, thr):
    tp = fp = fn = 0
    for ext, key, truth in data:
        for i, k in enumerate(key):
            for j, e in enumerate(ext):
                pred = sim(k, e, w) >= thr; pos = truth.get(i) == j; tp += pred and pos; fp += pred and not pos; fn += (not pred) and pos
    p, r, f = prf(tp, fp, fn); return dict(precision=p, recall=r, f1=f)
def assignment_scores(data, w, thr, optimal=True):
    tp = fp = fn = 0
    for ext, key, truth in data:
        m = match(ext, key, w, thr, optimal)
        for i in range(len(key)):
            if i in m: tp += truth.get(i) == m[i]; fp += truth.get(i) != m[i]
            else: fn += i in truth
    p, r, f = prf(tp, fp, fn); return dict(precision=p, recall=r, f1=f)
def cohens_kappa(a, b):
    n = len(a); po = sum(x == y for x, y in zip(a, b)) / n; pa, pb = sum(a) / n, sum(b) / n; pe = pa * pb + (1 - pa) * (1 - pb); return 1.0 if pe == 1 else (po - pe) / (1 - pe)
def agreement(data, thr_text, thr_effect):
    """Do the two signals make the same match/no-match decision on every (key, extracted) pair? Cohen's kappa, with the raw decisions."""
    a, b = [], []
    for ext, key, truth in data:
        for k in key:
            for e in ext: a.append(sim_text(k, e) >= thr_text); b.append(sim_effect(k, e) >= thr_effect)
    return dict(kappa=cohens_kappa(a, b), both_yes=sum(x and y for x, y in zip(a, b)), text_only=sum(x and not y for x, y in zip(a, b)), effect_only=sum(y and not x for x, y in zip(a, b)))

# ---- order and dependency
def kendall_tau(pairs):
    """pairs: [(key_index, extracted_index)]. +1 same order, -1 reversed."""
    c = d = 0
    for (a1, b1), (a2, b2) in itertools.combinations(pairs, 2):
        s = (a1 - a2) * (b1 - b2); c += s > 0; d += s < 0
    return (c - d) / (c + d) if c + d else 1.0
def reach(edges):
    nxt = {}
    for a, b in edges: nxt.setdefault(a, set()).add(b)
    out = {}
    for s in list(nxt) + [b for _, b in edges]:
        seen, st = set(), [s]
        while st:
            x = st.pop()
            for y in nxt.get(x, ()):
                if y not in seen: seen.add(y); st.append(y)
        out[s] = seen
    return out
def dependency_f1(key_proc, ext_proc, m):
    """Edges of the key's dependency graph (between matched steps) recovered as reachability in the extracted graph."""
    kids = [s["id"] for s in key_proc.steps]; eids = [s["id"] for s in ext_proc.steps]; kmap = {kids[i]: eids[j] for i, j in m.items()}
    ke = [(a, b) for a, b in dag(key_proc)["edges"] if a in kmap and b in kmap]; r = reach(dag(ext_proc)["edges"]); tp = sum(kmap[b] in r.get(kmap[a], ()) for a, b in ke)
    return dict(edges=len(ke), recovered=tp, recall=tp / len(ke) if ke else 1.0)

# ---- the coherent scorer: words stay primary, effects only boost, assignment is optimal, and the threshold is reported rather than hidden
DEFAULT_WEIGHT, DEFAULT_THRESHOLD = 0.25, 0.10        # fitted on the SIMULATED extractor (seeds 0-19, default noise); re-fit on labeled data from a real extractor
def boosted(a, b, we=DEFAULT_WEIGHT):
    """Word similarity, plus a small bonus when BOTH steps carry inferred effects. Never worse than words alone in any noise condition we tested; better when effects are clean."""
    return sim_text(a, b) + (we * sim_effect(a, b) if signature(a) and signature(b) else 0.0)
def assign(ext, key, we=DEFAULT_WEIGHT, thr=DEFAULT_THRESHOLD):
    """Optimal one-to-one assignment on the boosted similarity: {key_index: extracted_index}."""
    if not key or not ext: return {}
    S = [[boosted(k, e, we) for e in ext] for k in key]; return {i: j for i, j in hungarian_max(S) if S[i][j] >= thr}
def step_scores(data, we=DEFAULT_WEIGHT, thr=DEFAULT_THRESHOLD, sim_fn=None):
    """Mean recall and precision of CORRECT matches over jobs. data items: (extracted, key, truth, ...)."""
    rec, prec = [], []
    for item in data:
        ext, key, truth = item[0], item[1], item[2]
        if sim_fn is None: m = assign(ext, key, we, thr)
        else:
            S = [[sim_fn(k, e) for e in ext] for k in key]; m = {i: j for i, j in hungarian_max(S) if S[i][j] >= thr} if key and ext else {}
        ok = sum(truth.get(i) == j for i, j in m.items()); rec.append(ok / len(truth) if truth else 1.0); prec.append(ok / len(m) if m else 1.0)
    return sum(rec) / len(rec), sum(prec) / len(prec)
def threshold_curve(data, sim_fn, thresholds=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7)):
    """Recall and precision at every threshold. Report this curve, not one point: a single threshold can move the headline recall by tens of points."""
    return [(t,) + step_scores(data, thr=t, sim_fn=sim_fn) for t in thresholds]
def bootstrap_ci(values, n=1000, seed=0, level=0.95):
    """Mean and percentile bootstrap interval over jobs: how much of a score is luck of the draw."""
    rnd = random.Random(seed); means = sorted(sum(rnd.choice(values) for _ in values) / len(values) for _ in range(n)); lo, hi = means[int((1 - level) / 2 * n)], means[int((1 + level) / 2 * n) - 1]; return sum(values) / len(values), lo, hi
def job_report(ext, key, truth, ext_proc=None, key_proc=None):
    """Everything we score about one extraction: step recall/precision, order, dependency recovery, and how well the two signals agree (a health check on the inferred effects)."""
    m = assign(ext, key); ok = sum(truth.get(i) == j for i, j in m.items())
    out = dict(recall=ok / len(truth) if truth else 1.0, precision=ok / len(m) if m else 1.0, order_tau=kendall_tau(list(m.items())), signal_kappa=agreement_kappa(ext, key))
    if ext_proc is not None and key_proc is not None: out["dependency_recall"] = dependency_f1(key_proc, ext_proc, m)["recall"]
    return out
def agreement_kappa(ext, key, thr_text=0.5, thr_effect=0.5):
    a = [sim_text(k, e) >= thr_text for k in key for e in ext]; b = [sim_effect(k, e) >= thr_effect for k in key for e in ext]; return cohens_kappa(a, b) if a else 0.0
def discriminates(data, sim_fns, thr=DEFAULT_THRESHOLD, margin=0.02):
    """Can this benchmark tell the matchers apart at all? False means the scores are saturated and say nothing about which matcher is better on harder data."""
    f = {}
    for name, fn in sim_fns.items(): r, p = step_scores(data, thr=thr, sim_fn=fn); f[name] = 2 * r * p / (r + p) if r + p else 0.0
    return (max(f.values()) - min(f.values()) >= margin), f
