# SPDX-License-Identifier: Apache-2.0
"""Group views. Rules: (1) only shared Summaries go in, with NO person identifier; (2) a group smaller than k is suppressed entirely; (3) each person's contribution is clipped to `cap_s`
and Laplace noise of scale cap_s/epsilon is added to every released sum (epsilon-differential privacy for the released totals); (4) there is no function that returns anything per person."""
import math, random

def laplace(scale, rnd):
    u = rnd.random() - 0.5; return -scale * math.copysign(1, u) * math.log(1 - 2 * abs(u))
def rollup(groups, k=5, cap_s=8 * 3600.0, epsilon=1.0, seed=None):
    """groups: {group_name: [summary, ...]} where each summary is PersonalLedger.summary output shared by its owner. Returns {group: {...}} with suppressed groups reported as such."""
    rnd = random.Random(seed); out = {}
    for g, sums in groups.items():
        if len(sums) < k: out[g] = dict(suppressed=True, reason=f"fewer than {k} contributors"); continue
        b = cap_s / epsilon; res = dict(suppressed=False, contributors=len(sums), epsilon=epsilon, noise_scale_s=b, by_category={})
        for c in sums[0]["by_category"]:
            s = sum(min(x["by_category"][c], cap_s) for x in sums); res["by_category"][c] = max(0.0, s + laplace(b, rnd))
        res["wait_s"] = max(0.0, sum(min(x["loss"]["wait"], cap_s) for x in sums) + laplace(b, rnd)); out[g] = res
    return out
def handoffs(edges, k=5):
    """edges: list of (from_team, to_team, wait_seconds, contributor_pseudonym). Only the number of distinct contributors is used to decide release; pseudonyms are never output."""
    agg = {}
    for a, b, w, who in edges:
        e = agg.setdefault((a, b), dict(total=0.0, who=set(), n=0)); e["total"] += w; e["who"].add(who); e["n"] += 1
    return {f"{a}->{b}": dict(mean_wait_s=e["total"] / e["n"], samples=e["n"]) for (a, b), e in agg.items() if len(e["who"]) >= k}
def doc_gaps(failed_queries, k=5):
    """failed_queries: list of (normalized_query, contributor_pseudonym). A query is reported as a documentation gap only if >= k distinct people hit it."""
    q = {}
    for text, who in failed_queries: q.setdefault(text, set()).add(who)
    return sorted(((t, len(w)) for t, w in q.items() if len(w) >= k), key=lambda x: -x[1])
