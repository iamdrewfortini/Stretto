# SPDX-License-Identifier: Apache-2.0
"""Handoff core: an expert's hands-on work as a verified procedure graph.
A step has preconditions (`requires`) and effects (`adds`, `removes`) over named facts. Replaying the steps in order finds every gap ("step 7 needs the old belt removed but no step
removes it"); each gap becomes ONE targeted question; answers insert, move or pre-declare until the graph closes. The same graph then guides a trainee. Isolated: standard library only."""
import re
from collections import deque

def step(id, text, requires=(), adds=(), removes=(), tools=(), warnings=()):
    return dict(id=id, text=text, requires=list(requires), adds=list(adds), removes=list(removes), tools=list(tools), warnings=list(warnings))

class Procedure:
    def __init__(self, steps, initial=(), goal=()): self.steps, self.initial, self.goal = [dict(s) for s in steps], set(initial), set(goal)
    def copy(self): return Procedure(self.steps, self.initial, self.goal)
    def index(self, sid): return next(i for i, s in enumerate(self.steps) if s["id"] == sid)

def replay(p):
    """Walk the steps in order. Returns (issues, final_state). Issue kinds: precondition, phantom_removal, goal."""
    state, issues = set(p.initial), []
    for i, s in enumerate(p.steps):
        miss = sorted(set(s["requires"]) - state)
        if miss: issues.append(dict(kind="precondition", step=s["id"], index=i, missing=miss))
        ghost = sorted(set(s["removes"]) - state)
        if ghost: issues.append(dict(kind="phantom_removal", step=s["id"], index=i, missing=ghost))
        state = (state - set(s["removes"])) | set(s["adds"])
    miss = sorted(p.goal - state)
    if miss: issues.append(dict(kind="goal", step="GOAL", index=len(p.steps), missing=miss))
    return issues, state

def gaps(p):
    """One gap per distinct missing fact, with the question to ask. out_of_order = some step produces the fact but later; missing_step = nobody produces it."""
    issues, _ = replay(p); prod = {}
    for s in p.steps:
        for f in s["adds"]: prod.setdefault(f, []).append(s["id"])
    out, seen = [], set()
    for iss in issues:
        for f in iss["missing"]:
            key = (iss["kind"], f)
            if key in seen: continue
            seen.add(key)
            if iss["kind"] == "phantom_removal":
                kind, q = "phantom_removal", f"Step {iss['step']} removes '{f}', but nothing earlier made it true. Was it already true when you started?"
            elif prod.get(f):
                kind, q = "out_of_order", f"Step {iss['step']} needs '{f}', but it only happens later (step {prod[f][0]}). Is the order wrong?"
            else:
                kind, q = "missing_step", f"Step {iss['step']} needs '{f}', but no step makes that true. What did you do to get there?"
            out.append(dict(kind=kind, fact=f, needed_by=iss["step"], producers=prod.get(f, []), question=q))
    return out

def close(p, ask, max_questions=20):
    """Ask the expert one question per gap until nothing is open. `ask(gap)` returns None (cannot answer) or one of:
    {'insert': step, 'before': step_id|None}, {'initial': fact}, {'move': step_id, 'before': step_id}."""
    p = p.copy(); asked = []
    while True:
        g = gaps(p)
        if not g: return dict(closed=True, asked=asked, procedure=p)
        if len(asked) >= max_questions: return dict(closed=False, asked=asked, procedure=p, why="question budget used")
        a = ask(g[0]); asked.append((g[0], a))
        if a is None: return dict(closed=False, asked=asked, procedure=p, why="expert could not answer")
        if "insert" in a:
            at = len(p.steps) if a.get("before") is None else p.index(a["before"]); p.steps.insert(at, dict(a["insert"]))
        elif "initial" in a: p.initial.add(a["initial"])
        elif "move" in a:
            i = p.index(a["move"]); s = p.steps.pop(i); at = p.index(a["before"]); p.steps.insert(at, s)

def dag(p):
    """Precedence graph: producer -> consumer for every required fact, and consumer -> remover when a later step removes what an earlier step still needed. Kahn order; cycle = defect."""
    edges, n = set(), len(p.steps)
    for j, s in enumerate(p.steps):
        for f in s["requires"]:
            prods = [i for i in range(j) if f in p.steps[i]["adds"]]
            if prods: edges.add((p.steps[prods[-1]]["id"], s["id"]))
        for f in s["removes"]:
            for i in range(j):
                if f in p.steps[i]["requires"]: edges.add((p.steps[i]["id"], s["id"]))
    ids = [s["id"] for s in p.steps]; indeg = {i: 0 for i in ids}; kids = {i: [] for i in ids}
    for a, b in sorted(edges): indeg[b] += 1; kids[a].append(b)      # sorted: a set's order changes with the hash seed, and so would the topological order
    q = deque(i for i in ids if indeg[i] == 0); order = []
    while q:
        x = q.popleft(); order.append(x)
        for k in kids[x]:
            indeg[k] -= 1
            if indeg[k] == 0: q.append(k)
    return dict(edges=sorted(edges), order=order, cycle=len(order) != n)

class Guide:
    """Trainee guidance: tell it which step the camera/glasses saw; it speaks up on skipped, out-of-order, repeated or unmet-precondition steps."""
    def __init__(self, p): self.p, self.done, self.state = p, [], set(p.initial)
    def observe(self, step_id, confidence=1.0, min_confidence=0.6):
        if confidence < min_confidence: return [dict(alert="low_confidence", step=step_id)]
        i = self.p.index(step_id); s = self.p.steps[i]; alerts = []
        if step_id in self.done: alerts.append(dict(alert="repeated", step=step_id))
        skipped = [x["id"] for x in self.p.steps[:i] if x["id"] not in self.done]
        if skipped: alerts.append(dict(alert="skipped", steps=skipped))
        miss = sorted(set(s["requires"]) - self.state)
        if miss: alerts.append(dict(alert="precondition_unmet", step=step_id, missing=miss))
        self.state = (self.state - set(s["removes"])) | set(s["adds"])
        if step_id not in self.done: self.done.append(step_id)
        return alerts
    def progress(self): return len(set(self.done)) / len(self.p.steps)

# ---- evaluation against a hand-written key
def tokens(t): return set(re.findall(r"[a-z0-9]+", t.lower())) - {"the", "a", "an", "and", "to", "of", "in", "on", "for", "with"}
def match_steps(extracted, key, threshold=0.5):
    """Greedy one-to-one match by token Jaccard. Returns recall (key steps recovered) and precision (extracted steps that are real)."""
    used, hits = set(), 0
    for k in key:
        tk = tokens(k); best, bj = None, 0.0
        for j, e in enumerate(extracted):
            if j in used: continue
            te = tokens(e); sim = len(tk & te) / max(1, len(tk | te))
            if sim > bj: best, bj = j, sim
        if best is not None and bj >= threshold: used.add(best); hits += 1
    return dict(recall=hits / max(1, len(key)), precision=hits / max(1, len(extracted)), matched=hits)

def removal_audit(p):
    """Delete each step in turn. A removal is DETECTABLE if some other step or the goal depends on something only that step provides; detectable removals must all be flagged."""
    detectable = flagged = 0; undetectable = []
    for i, s in enumerate(p.steps):
        q = p.copy(); q.steps.pop(i)
        needed = {f for f in s["adds"] if any(f in t["requires"] for t in q.steps) or f in q.goal} | {f for f in s["removes"] if any(f in t["requires"] for t in q.steps[i:])}
        if not needed: undetectable.append(s["id"]); continue
        detectable += 1; flagged += bool(gaps(q))
    return dict(steps=len(p.steps), detectable=detectable, flagged=flagged, undetectable=undetectable, detectable_fraction=detectable / len(p.steps))
