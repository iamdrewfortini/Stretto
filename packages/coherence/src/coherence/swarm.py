# SPDX-License-Identifier: Apache-2.0
"""Swarm layer for micro cells: (1) Langton's ant, 10,000 steps, escape (highway) direction; (2) ant-colony optimization over a cell's action graph;
(3) real-time streaming of each cell's D through a bounded bus; (4) cache-to-cache gossip so every cell converges to the same view, including cached model answers.
Stdlib only, in-process. Distributed transport is NOT built here."""
import hashlib, math, random, time
from collections import deque

# ---------------- (1) Langton's ant
DIRS = [(0, 1), (1, 0), (0, -1), (-1, 0)]          # up, right, down, left (clockwise)
def langton(steps=10000, seed_cells=(), period=104, extra=0):
    """Rules: on white turn right, on black turn left; flip the cell; move forward. Returns trajectory summary and the escape (highway) vector if found.
    seed_cells: iterable of (x, y) that start black (a cell derives this from its own state)."""
    black = set(seed_cells); x = y = 0; d = 0; path = []
    steps = steps + extra                                   # `extra` = confirmation window: the highway is only recognized after >= 3 periods (312 steps) of repetition
    for _ in range(steps):
        path.append((x, y, d))
        if (x, y) in black: d = (d - 1) % 4; black.discard((x, y))
        else: d = (d + 1) % 4; black.add((x, y))
        x += DIRS[d][0]; y += DIRS[d][1]
    path.append((x, y, d)); n = len(path)
    # highway = the last `window` steps repeat with a fixed displacement every `period` steps (same heading)
    onset = None
    ok = lambda i: path[i + period][2] == path[i][2] and (path[i + period][0] - path[i][0], path[i + period][1] - path[i][1]) == (path[n - 1][0] - path[n - 1 - period][0], path[n - 1][1] - path[n - 1 - period][1])
    if n > 4 * period and all(ok(i) for i in range(n - 1 - 3 * period, n - 1 - period)):
        i = n - 1 - 3 * period
        while i > 0 and ok(i - 1): i -= 1
        onset = i
    vec = (path[-1][0] - path[-1 - period][0], path[-1][1] - path[-1 - period][1]) if onset is not None else None
    return dict(steps=steps, black=len(black), onset=onset, vector=vec, period=period if onset is not None else None, end=(x, y), heading=d)
def seed_from_address(key, n=12, span=6):
    """Deterministic sparse start pattern from a cell's WF-13D address string, so each cell's ant is its own."""
    h = hashlib.sha256(key.encode()).digest(); return {((h[2 * i] % (2 * span + 1)) - span, (h[2 * i + 1] % (2 * span + 1)) - span) for i in range(n)}
def escape_direction(vec):
    """Quantize the highway vector to one of 8 compass directions (None if no highway was found: an explicit 'no escape direction', never a guess)."""
    if vec is None: return None
    ang = math.degrees(math.atan2(vec[1], vec[0])) % 360; return ["E", "NE", "N", "NW", "W", "SW", "S", "SE"][int((ang + 22.5) // 45) % 8]

# ---------------- (2) ant-colony optimization on a weighted DAG/graph
def aco(graph, src, dst, ants=20, iters=60, alpha=1.0, beta=2.0, rho=0.3, Q=1.0, seed=0):
    """graph: {u: {v: cost}}. Returns (best_path, best_cost). Standard Ant System: P(u->v) ~ tau^alpha * (1/cost)^beta; evaporate rho; deposit Q/L on tours."""
    rnd = random.Random(seed); tau = {(u, v): 1.0 for u in graph for v in graph[u]}; best, bc = None, math.inf
    for _ in range(iters):
        tours = []
        for _ in range(ants):
            u, path, seen, cost = src, [src], {src}, 0.0
            while u != dst:
                opts = [(v, c) for v, c in graph.get(u, {}).items() if v not in seen]
                if not opts: path = None; break
                w = [tau[(u, v)] ** alpha * (1.0 / max(c, 1e-9)) ** beta for v, c in opts]; r = rnd.random() * sum(w); acc = 0.0
                for (v, c), wi in zip(opts, w):
                    acc += wi
                    if acc >= r: break
                path.append(v); seen.add(v); cost += c; u = v
            if path: tours.append((path, cost));  best, bc = (path, cost) if cost < bc else (best, bc)
        for k in tau: tau[k] *= 1 - rho
        for path, cost in tours:
            for a, b in zip(path, path[1:]): tau[(a, b)] += Q / cost
    return best, bc
def shortest(graph, src, dst):
    import heapq
    dist, pq = {src: 0.0}, [(0.0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == dst: return d
        if d > dist.get(u, math.inf): continue
        for v, c in graph.get(u, {}).items():
            if d + c < dist.get(v, math.inf): dist[v] = d + c; heapq.heappush(pq, (d + c, v))
    return math.inf

# ---------------- (3)+(4) streaming bus and cache-to-cache gossip
class Cache:
    """Content-addressed cache with last-writer-wins on (seq, origin). Entries: key -> (seq, origin, value). Digest = {key: (seq, origin)}."""
    def __init__(self, cap=1024): self.d, self.cap = {}, cap
    def put(self, key, value, seq, origin):
        cur = self.d.get(key)
        if cur is None or (seq, origin) > (cur[0], cur[1]):
            self.d[key] = (seq, origin, value)
            if len(self.d) > self.cap: self.d.pop(min(self.d, key=lambda k: self.d[k][0]))
            return True
        return False
    def digest(self): return {k: (v[0], v[1]) for k, v in self.d.items()}
    def newer_than(self, digest): return {k: v for k, v in self.d.items() if k not in digest or (v[0], v[1]) > tuple(digest[k])}
    def merge(self, entries): return sum(self.put(k, v[2], v[0], v[1]) for k, v in entries.items())

class StreamCell:
    """A neuron: publishes its D stream (bounded ring, drop-oldest) and keeps a cache of peers' latest D, direction and cached model answers."""
    def __init__(self, name, ring=256): self.name, self.cache, self.seq, self.out, self.dropped = name, Cache(), 0, deque(maxlen=ring), 0
    def publish_D(self, D, direction, gaps=None):
        self.seq += 1; rec = dict(cell=self.name, seq=self.seq, t=time.perf_counter(), D=D, dir=direction, gaps=gaps)
        if len(self.out) == self.out.maxlen: self.dropped += 1
        self.out.append(rec); self.cache.put(f"D:{self.name}", rec, self.seq, self.name); return rec
    def remember_answer(self, model, prompt, answer):
        key = "ans:" + hashlib.sha256(f"{model}\0{prompt}".encode()).hexdigest()[:16]; self.seq += 1; self.cache.put(key, answer, self.seq, self.name); return key
    def lookup_answer(self, model, prompt):
        v = self.cache.d.get("ans:" + hashlib.sha256(f"{model}\0{prompt}".encode()).hexdigest()[:16]); return None if v is None else v[2]

def gossip_round(cells, rnd):
    """Each cell pushes its digest to one random peer; the peer returns what the sender lacks and takes what it lacks (push-pull anti-entropy). Returns messages sent."""
    msgs = 0
    for a in cells:
        b = rnd.choice([c for c in cells if c is not a]); msgs += 2
        give = a.cache.newer_than(b.cache.digest()); take = b.cache.newer_than(a.cache.digest()); b.cache.merge(give); a.cache.merge(take)
    return msgs
def converged(cells):
    first = cells[0].cache.digest(); return all(c.cache.digest() == first for c in cells[1:])

def langton_until_locked(seed_cells=(), period=104, locks=5, cap=2_000_000):
    """Run the ant for as many steps as it takes to LOCK into a pattern, then stop. Lock = the NET cell changes of `locks` consecutive periods are identical after
    translating to the ant's position, with the same non-zero displacement every period (a highway). `guaranteed` additionally requires the frontier to be clean:
    no black cell lies ahead of the motif's own footprint, so the motif can only meet white cells and must repeat forever. If `cap` steps pass without a lock the result is
    NOT_LOCKED (Langton's ant is conjectured, not proven, to always build a highway), never a guess."""
    black = set(seed_cells); x = y = d = step = 0; cur = set(); sigs = []
    while step < cap:
        if (x, y) in black: d = (d - 1) % 4; black.discard((x, y))
        else: d = (d + 1) % 4; black.add((x, y))
        cur ^= {(x, y)}; x += DIRS[d][0]; y += DIRS[d][1]; step += 1
        if step % period:
            continue
        sigs.append((step, d, frozenset((cx - x, cy - y) for cx, cy in cur), (x, y))); cur = set()
        if len(sigs) < locks + 1: continue
        tail = sigs[-(locks + 1):]; disp = {(b[3][0] - a[3][0], b[3][1] - a[3][1]) for a, b in zip(tail, tail[1:])}
        if len({(t[1], t[2]) for t in tail}) == 1 and len(disp) == 1 and next(iter(disp)) != (0, 0):
            v = next(iter(disp)); n = math.hypot(*v); u = (v[0] / n, v[1] / n)
            reach = max((cx * u[0] + cy * u[1] for cx, cy in tail[-1][2]), default=0.0); ahead = max(((bx - x) * u[0] + (by - y) * u[1] for bx, by in black), default=-math.inf)
            return dict(status="LOCKED", guaranteed=ahead <= reach + 1e-9, steps_run=step, lock_step=tail[0][0], vector=v, direction=escape_direction(v), period=period, locks=locks,
                        black=len(black), footprint=len(tail[-1][2]), frontier_ahead=round(ahead, 3), footprint_reach=round(reach, 3))
    return dict(status="NOT_LOCKED", guaranteed=False, steps_run=step, vector=None, direction=None, period=period, black=len(black))

def langton_cells(steps, seed_cells=()):
    """Black cells and the visited path after exactly `steps` steps (for figures and tests)."""
    black = set(seed_cells); x = y = d = 0; path = [(0, 0)]
    for _ in range(steps):
        if (x, y) in black: d = (d - 1) % 4; black.discard((x, y))
        else: d = (d + 1) % 4; black.add((x, y))
        x += DIRS[d][0]; y += DIRS[d][1]; path.append((x, y))
    return black, path
