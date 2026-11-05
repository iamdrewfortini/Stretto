# SPDX-License-Identifier: Apache-2.0
"""Ant colony over the transition graph: optimized circuits and bridges, from measured moves only.
Ants walk places by transition counts, laying pheromone on edges that end in long focus stays; pheromone
evaporates each generation. After G generations the strongest trail is the optimized circuit (the route the
day already wants to take), and bridges are the articulation places whose removal would split focus from
distraction. Deterministic (seeded), exact, and priced: every pheromone value traces to counts and stays."""
import random

FOCUS = {"Build", "Write", "Learn", "Plan", "Design", "Research"}


def simulate(transitions, cat_of, generations=24, ants_per_gen=16, seed=7, evap=0.12, alpha=1.0, beta=2.0):
    """Returns dict(circuit=[places], pheromone={(src,dst): v}, bridges=[places], generations). Pure and seeded."""
    edges = {}
    for t in transitions:
        edges.setdefault(t["src"], []).append(t)
    places = sorted({t["src"] for t in transitions} | {t["dst"] for t in transitions})
    if not places:
        return dict(circuit=[], pheromone={}, bridges=[], generations=0)
    tau = {(t["src"], t["dst"]): 1.0 for t in transitions}
    stay = {(t["src"], t["dst"]): max(1, t["avg_stay_s"]) for t in transitions}
    rng = random.Random(seed)
    best, best_score = [], -1.0
    for _ in range(generations):
        for _a in range(ants_per_gen):
            cur = rng.choice(places)
            path, score, seen = [cur], 0.0, {cur}
            for _step in range(6):
                outs = edges.get(cur, [])
                if not outs:
                    break
                weights = []
                for t in outs:
                    reward = (stay[(t["src"], t["dst"])] / 600.0) * (2.0 if cat_of.get(t["dst"]) in FOCUS else 0.4)
                    weights.append((tau[(t["src"], t["dst"])] ** alpha) * (reward ** beta))
                tot = sum(weights) or 1.0
                pick, r, acc = outs[-1], rng.random() * tot, 0.0
                for t, w in zip(outs, weights):
                    acc += w
                    if r <= acc:
                        pick = t; break
                cur = pick["dst"]
                if cur in seen and len(path) > 2:
                    break
                seen.add(cur); path.append(cur)
                score += (stay[(pick["src"], pick["dst"])] / 60.0) * (2.0 if cat_of.get(cur) in FOCUS else 0.4)
            for a, b in zip(path, path[1:]):
                tau[(a, b)] += 1.0 + score / 100.0
            if score > best_score:
                best, best_score = list(path), score
        for k in tau:
            tau[k] *= (1.0 - evap)
    # bridges: places whose removal disconnects a focus place from every other focus place
    adj = {}
    for (a, b) in tau:
        adj.setdefault(a, set()).add(b); adj.setdefault(b, set()).add(a)
    focus_places = [p for p in places if cat_of.get(p) in FOCUS]
    def focus_connected(skip):
        if len(focus_places) < 2:
            return True
        seen, stack = set(), [focus_places[0]]
        while stack:
            n = stack.pop()
            if n == skip or n in seen:
                continue
            seen.add(n); stack.extend(adj.get(n, ()))
        return all(p in seen or p == skip for p in focus_places)
    bridges = [p for p in places if cat_of.get(p) not in FOCUS and not focus_connected(p)]
    return dict(circuit=best, circuit_score=round(best_score, 3),
                pheromone={f"{a}>{b}": round(v, 4) for (a, b), v in sorted(tau.items(), key=lambda kv: -kv[1])[:12]},
                bridges=bridges, generations=generations)
