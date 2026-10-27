#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Draws every figure in docs/figures as SVG from the code and recorded data (standard library only, deterministic). `--check` regenerates into a temp dir and fails if any committed file differs."""
import glob, html, json, math, os, random, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in glob.glob(os.path.join(ROOT, "packages", "*", "src")): sys.path.insert(0, p)
INK, MUTE, BLUE, ORANGE, GREEN, RED, GRID = "#1b1f24", "#6b7280", "#2563eb", "#d97706", "#15803d", "#b91c1c", "#e5e7eb"
def f(x): return f"{x:.1f}"
class Svg:
    def __init__(self, w, h, title): self.w, self.h, self.p, self.title = w, h, [], title
    def rect(self, x, y, w, h, fill="none", stroke=None, rx=0, dash=None, op=1.0, sw=1): self.p.append(f'<rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" rx="{rx}" fill="{fill}"' + (f' stroke="{stroke}" stroke-width="{sw}"' if stroke else "") + (f' stroke-dasharray="{dash}"' if dash else "") + (f' opacity="{op}"' if op != 1 else "") + "/>")
    def text(self, x, y, s, size=12, anchor="start", fill=INK, weight="400", rot=None): self.p.append(f'<text x="{f(x)}" y="{f(y)}" font-size="{size}" text-anchor="{anchor}" fill="{fill}" font-weight="{weight}"' + (f' transform="rotate({rot} {f(x)} {f(y)})"' if rot else "") + f">{html.escape(str(s))}</text>")
    def line(self, x1, y1, x2, y2, stroke=MUTE, w=1, dash=None, op=1.0): self.p.append(f'<line x1="{f(x1)}" y1="{f(y1)}" x2="{f(x2)}" y2="{f(y2)}" stroke="{stroke}" stroke-width="{w}"' + (f' stroke-dasharray="{dash}"' if dash else "") + (f' opacity="{op}"' if op != 1 else "") + "/>")
    def circle(self, x, y, r, fill="none", stroke=None, op=1.0): self.p.append(f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r)}" fill="{fill}"' + (f' stroke="{stroke}"' if stroke else "") + (f' opacity="{op}"' if op != 1 else "") + "/>")
    def arrow(self, x1, y1, x2, y2, stroke=MUTE, w=1.2, dash=None):
        self.line(x1, y1, x2, y2, stroke, w, dash); a = math.atan2(y2 - y1, x2 - x1); s = 7
        self.p.append(f'<polygon points="{f(x2)},{f(y2)} {f(x2 - s * math.cos(a - .4))},{f(y2 - s * math.sin(a - .4))} {f(x2 - s * math.cos(a + .4))},{f(y2 - s * math.sin(a + .4))}" fill="{stroke}"/>')
    def doc(self): return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" height="{self.h}" font-family="system-ui,Segoe UI,Helvetica,Arial,sans-serif" role="img" aria-label="{html.escape(self.title)}">'
                           f'<title>{html.escape(self.title)}</title><rect width="100%" height="100%" fill="white"/>' + "".join(self.p) + "</svg>\n")
def box(s, x, y, w, h, label, sub=None, fill="#f8fafc", stroke=INK, size=12):
    s.rect(x, y, w, h, fill, stroke, 6); s.text(x + w / 2, y + (h / 2 + 4 if not sub else h / 2 - 2), label, size, "middle", weight="600")
    if sub: s.text(x + w / 2, y + h / 2 + 12, sub, 10, "middle", MUTE)
def recorded(): return json.load(open(os.path.join(ROOT, "examples", "recorded_cluster.json")))

def fig_architecture():
    s = Svg(860, 470, "Two coherent tool sets joined by a mirror"); s.text(430, 24, "Two tool sets, each coherent alone; one mirror between them", 15, "middle", weight="700")
    deps = {os.path.basename(os.path.dirname(p)): open(p).read().split() for p in sorted(glob.glob(os.path.join(ROOT, "packages", "*", "DEPS")))}
    pos = {"telemetry": (60, 110), "adapters": (60, 190), "harness": (60, 270), "metarouter": (230, 270), "cells": (230, 190), "coherence": (350, 110),
           "perception": (640, 110), "humanflow": (640, 190), "handoff": (640, 270), "assistant": (470, 190), "finetune": (470, 270), "resonate": (470, 350), "wf13d": (350, 270), "metacoh": (350, 410)}
    side = {"telemetry": BLUE, "adapters": BLUE, "harness": BLUE, "metarouter": BLUE, "cells": BLUE, "perception": ORANGE, "humanflow": ORANGE, "handoff": ORANGE, "assistant": ORANGE, "finetune": ORANGE, "resonate": ORANGE, "wf13d": GREEN, "coherence": GREEN, "metacoh": MUTE}
    s.rect(30, 55, 380, 270, "#eff6ff", None, 10, op=.6); s.text(40, 75, "MACHINE SIDE: infrastructure coherence", 12, weight="700", fill=BLUE); s.rect(450, 55, 380, 330, "#fffbeb", None, 10, op=.7); s.text(460, 75, "HUMAN SIDE: process coherence (consent first)", 12, weight="700", fill=ORANGE)
    W, H = 130, 44
    for a, ds in sorted(deps.items()):
        for d in ds:
            if a in pos and d in pos: x1, y1 = pos[a][0] + W / 2, pos[a][1] + H / 2; x2, y2 = pos[d][0] + W / 2, pos[d][1] + H / 2; s.arrow(x1, y1, x2, y2, "#9ca3af", 1, "3 3") if a != "metacoh" else None
    for n, (x, y) in sorted(pos.items()): box(s, x, y, W, H, n, "umbrella + CLI" if n == "metacoh" else None, "white", side[n])
    s.text(430, 446, "dashed arrows are the real `DEPS` edges (package A may import package B); verified acyclic by scripts/check_deps.py", 10, "middle", MUTE)
    s.rect(335, 350, 160, 36, "#ecfdf5", GREEN, 6); s.text(415, 366, "coherence.mirror", 12, "middle", GREEN, "700"); s.text(415, 380, "13 human + 13 machine = 26 numbers", 10, "middle", GREEN)
    return s
def fig_wf13d():
    from wf13d.bridge import analyze, pack, SUBS
    s = Svg(860, 380, "WF-13D address layout and a worked ask order"); s.text(430, 24, "WF-13D: one 18-bit word, decoded in a few bit operations", 15, "middle", weight="700")
    x = 40; unit = 18; parts = [("c  class", 5, BLUE, "01111", "material · collective · create · far · undefined"), ("t  type", 6, ORANGE, "000111", "ID · CL · RV · MU · EP · PB"), ("s  sub", 7, GREEN, "1001000", "WHO WHAT WHERE WHEN WHY HOW + tempo")]
    for name, n, col, bits, desc in parts:
        s.rect(x, 50, n * unit, 34, col, None, 4, op=.15); s.rect(x, 50, n * unit, 34, "none", col, 4)
        for i, b in enumerate(bits): s.text(x + i * unit + unit / 2, 73, b, 14, "middle", col, "700")
        s.text(x + n * unit / 2, 100, f"{name} ({n} bits)", 11, "middle", col, "700"); s.text(x + n * unit / 2, 114, desc, 9, "middle", MUTE); x += n * unit + 14
    a = pack(15, 7, 72); v = analyze(a); s.text(40, 150, f"Example 15.07.072 = {v['c']}   (c=15, t=7, s=72)", 13, weight="700")
    order = ["WHAT", "WHY", "WHO", "WHERE", "WHEN", "HOW"]; steps = [("baseline order", list(order))]; o = list(order)
    for lab, name in (("t has MU → pull WHO to front", "WHO"), ("t has PB → pull WHERE", "WHERE"), ("class undefined → pull WHAT", "WHAT")): o = [name] + [q for q in o if q != name]; steps.append((lab, list(o)))
    for i, (lab, lst) in enumerate(steps):
        y = 175 + i * 34; s.text(40, y + 14, lab, 11, fill=MUTE)
        for j, q in enumerate(lst): s.rect(300 + j * 80, y, 74, 24, "#fef3c7" if q in v["known"] else "white", MUTE, 4); s.text(337 + j * 80, y + 16, q, 11, "middle", INK if q not in v["known"] else MUTE)
    s.text(40, 330, "known (stated by the human):", 11, fill=MUTE); s.text(300, 330, ", ".join(v["known"]), 12, weight="700"); s.text(40, 352, "ask next (known removed, max_q = %d):" % v["max_q"], 11, fill=MUTE); s.text(300, 352, ", ".join(v["ask"]), 12, weight="700", fill=BLUE)
    s.text(40, 370, f"path {v['path'][0]}..{v['path'][-1]} ({len(v['path'])} dimensions used)   stops: {', '.join(v['stops']) or 'none'}   ready = {v['ready']}", 11, fill=MUTE)
    return s
def fig_distance():
    from coherence.metrics import balance_gap, distance, intent_gap
    r = recorded(); cpu = [a / t for a, t in zip(r["allocated_vcpu"], r["threads"])]; ram = [a / t for a, t in zip(r["allocated_ram_gib"], r["ram_gib"])]
    gaps = dict(speed=None, energy=None, balance=balance_gap({"cpu": cpu, "ram": ram}, r["cluster_commit"]), scale=None, intent=intent_gap(len(r["wf13d_known_bits"]))); d = distance(gaps)
    s = Svg(860, 360, "Distance from coherence for the recorded cluster"); s.text(430, 24, f"Distance from coherence  D ≥ {d['D']}   (a lower bound)", 15, "middle", weight="700")
    base, top, bw = 300, 70, 90; s.line(70, base, 800, base, MUTE); s.line(70, top, 70, base, MUTE)
    for g in (0, .25, .5, .75, 1.0): y = base - g * (base - top); s.line(66, y, 800, y, GRID); s.text(60, y + 4, f"{g:g}", 10, "end", MUTE)
    s.text(22, 190, "gap  g (0 = at the optimum)", 11, "middle", MUTE, rot=-90)
    for i, ax in enumerate(("speed", "energy", "balance", "scale", "intent")):
        x = 110 + i * 140; g = gaps[ax]
        if g is None: s.rect(x, top, bw, base - top, "none", MUTE, 4, dash="5 4"); s.text(x + bw / 2, 180, "not measured", 12, "middle", MUTE); s.text(x + bw / 2, 198, "counts as 0", 10, "middle", MUTE)
        else: h = g * (base - top); s.rect(x, base - h, bw, h, ORANGE if ax == "intent" else BLUE); s.text(x + bw / 2, base - h - 8, f"{g:.3f}", 12, "middle", INK, "700")
        s.text(x + bw / 2, base + 20, ax, 12, "middle", INK, "600")
    tot = sum(d["contribution"].values()); s.text(70, 345, f"share of D²:  intent {100 * d['contribution']['intent'] / tot:.1f}%   balance {100 * d['contribution']['balance'] / tot:.1f}%   (weights 0.2 each, a stated policy choice; unmeasured axes contribute 0)", 11, fill=MUTE)
    return s
def fig_ant():
    from coherence.swarm import langton_cells, langton_until_locked
    r = langton_until_locked(); black, path = langton_cells(r["steps_run"]); xs = [c[0] for c in black | set(path)]; ys = [c[1] for c in black | set(path)]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys); W, H = 520, 520; sc = min((W - 20) / (x1 - x0 + 1), (H - 20) / (y1 - y0 + 1)); s = Svg(860, 560, "Langton's ant at the moment it locks into its highway")
    s.text(430, 24, f"Langton's ant, empty grid: locked after {r['steps_run']} steps", 15, "middle", weight="700"); ox, oy = 20, 40
    for (cx, cy) in sorted(black): s.rect(ox + (cx - x0) * sc, oy + (y1 - cy) * sc, sc, sc, "#111827")
    px, py = path[-1]; s.circle(ox + (px - x0 + .5) * sc, oy + (y1 - py + .5) * sc, 5, RED); vx, vy = r["vector"]; s.arrow(ox + (px - x0 + .5) * sc, oy + (y1 - py + .5) * sc, ox + (px - x0 + .5) * sc + vx * 6 * sc, oy + (y1 - py + .5) * sc - vy * 6 * sc, RED, 2.5)
    s.text(580, 90, "what you are looking at", 13, weight="700"); L = [f"{len(black)} black cells after {r['steps_run']} steps", "chaotic blob (top-right) then a straight diagonal 'highway'", f"highway: period {r['period']} steps, moves {r['vector']} per period", f"escape direction: {r['direction']} (red arrow)", f"lock rule: net changes of {r['locks']} consecutive periods identical", f"frontier clean (nothing ahead): guaranteed = {r['guaranteed']}", "", "Literature: the highway starts near step 9,977.", "Cells seeded from their own address lock at", "different step counts (see ant-steps figure)."]
    for i, t in enumerate(L): s.text(580, 114 + i * 20, t, 11, fill=INK if t else MUTE)
    return s
def fig_ant_steps():
    from coherence.swarm import langton_until_locked, seed_from_address
    res = sorted(langton_until_locked(seed_from_address(f"{i}.62.080"), cap=400_000)["steps_run"] for i in range(40)); empty = langton_until_locked()["steps_run"]
    s = Svg(860, 330, "Steps each cell needs before its ant locks"); s.text(430, 24, "Steps until locked: 40 address-seeded cells (all 40 locked) and the empty grid", 15, "middle", weight="700")
    lo, hi = math.log10(500), math.log10(60000); mx = lambda v: 70 + (math.log10(v) - lo) / (hi - lo) * 730
    s.line(70, 220, 800, 220, MUTE)
    for t in (1000, 3000, 10000, 30000): s.line(mx(t), 216, mx(t), 224, MUTE); s.text(mx(t), 240, f"{t:,}", 10, "middle", MUTE)
    s.text(435, 262, "steps run before the pattern locked (log scale)", 11, "middle", MUTE)
    for i, v in enumerate(res): s.circle(mx(v), 190 - (i % 5) * 18, 5, BLUE, op=.75)
    s.line(mx(empty), 80, mx(empty), 220, RED, 1.5, "4 3"); s.text(mx(empty), 72, f"empty grid: {empty:,}", 11, "middle", RED, "700")
    s.text(70, 300, f"min {res[0]:,}   median {res[len(res) // 2]:,}   max {res[-1]:,} steps. The ant runs as long as it needs; a cap gives an explicit NOT_LOCKED.", 11, fill=MUTE)
    return s
def fig_tesseract():
    from coherence.mirror import AXES4
    s = Svg(860, 460, "The 4-cube of coherence states"); s.text(430, 24, "Four yes/no axes make a 4-cube: 16 states, 32 edges; each move flips one axis", 15, "middle", weight="700")
    ang1, ang2, cx, cy, R = 0.5, 0.35, 330, 245, 150; pts = {}
    for v in range(16):
        b = [(v >> (3 - i)) & 1 for i in range(4)]; x, y, z, w = [2 * t - 1 for t in b]
        x, w = x * math.cos(ang1) - w * math.sin(ang1), x * math.sin(ang1) + w * math.cos(ang1); z, w = z * math.cos(ang2) - w * math.sin(ang2), z * math.sin(ang2) + w * math.cos(ang2)
        k = 3 / (3 - w); x, y, z = x * k, y * k, z * k; pts[v] = (cx + R * (x + .5 * z) * .62, cy - R * (y + .35 * z) * .62, sum(b))
    cols = ["#b91c1c", "#d97706", "#ca8a04", "#65a30d", "#15803d"]
    for v in range(16):
        for k in range(4):
            u = v ^ (1 << k)
            if u > v: s.line(pts[v][0], pts[v][1], pts[u][0], pts[u][1], "#9ca3af", 1.2, op=.8)
    for v in range(16): x, y, lv = pts[v]; s.circle(x, y, 12, cols[lv], "white"); s.text(x, y + 4, format(v, "04b"), 8, "middle", "white", "700")
    s.text(600, 80, "vertex = (mind_clock, mind_memory, body_clock, body_memory)", 11, weight="700"); s.text(600, 98, "bit 1 = that axis measured coherent (≥ 0.7)", 11, fill=MUTE)
    for lv in range(5): s.circle(612, 130 + lv * 26, 8, cols[lv]); s.text(630, 134 + lv * 26, f"{lv} of 4 axes coherent" + ("  (all coherent)" if lv == 4 else ""), 11)
    s.text(600, 290, "example: bits 1001 = vertex 9, level 2", 11, weight="700"); s.text(600, 308, "flips that help: mind_memory, body_clock", 11, fill=MUTE); s.text(600, 332, "face counts: 16 vertices, 32 edges,", 11); s.text(600, 348, "24 squares, 8 cubes: 16−32+24−8 = 0", 11)
    s.text(600, 380, "a hypothesis about how to organise the measures,", 10, fill=MUTE); s.text(600, 394, "not a physical claim (see docs/STORY.md)", 10, fill=MUTE)
    return s
def fig_mirror():
    from coherence.mirror import mirror_coherence, jsd, intent_split
    h = [6, 5, 4, 3, 5, 1, 1, 1, 1, 4, 1, 1, 1]; m = [1, 1, 2, 4, 6, 6, 5, 4, 3, 1, 1, 1, 1]; H = [x / sum(h) for x in h]; M = [x / sum(m) for x in m]; c = mirror_coherence(h, m); sp = intent_split(h, confirmed=[0, 1, 2, 3])
    s = Svg(860, 400, "The attention mirror over thirteen loop dimensions"); s.text(430, 24, f"Attention mirror: coherence = 1 − JSD/ln 2 = {c:.3f}   (synthetic example)", 15, "middle", weight="700")
    base, scale = 280, 520
    for i in range(13):
        x = 80 + i * 56; s.rect(x, base - H[i] * scale, 22, H[i] * scale, ORANGE); s.rect(x + 24, base - M[i] * scale, 22, M[i] * scale, BLUE); s.text(x + 23, base + 16, f"D{i + 1:02d}", 10, "middle", MUTE)
        if abs(H[i] - M[i]) > 0.06: s.text(x + 23, base - max(H[i], M[i]) * scale - 6, "gap", 9, "middle", RED, "700")
    s.line(70, base, 810, base, MUTE); s.rect(80, 324, 12, 12, ORANGE); s.text(98, 335, "human attention (13 numbers)", 11); s.rect(300, 324, 12, 12, BLUE); s.text(318, 335, "machine attention (13 numbers)", 11)
    s.text(80, 366, f"Human attention on dimensions the person has consciously confirmed (D01..D04): {sp['conscious']:.0%}; on the rest (unknown to the system): {sp['unknown']:.0%}.", 11, fill=MUTE)
    s.text(80, 384, f"JSD = {jsd(h, m):.3f} nats (max {math.log(2):.3f}); identical attention scores 1, disjoint scores 0.", 11, fill=MUTE)
    return s
def fig_handoff():
    from handoff import dag, gaps; from handoff.examples import gearbox
    p = gearbox(); q = p.copy(); q.steps.pop(q.index("g4")); g = gaps(q)
    def layout(pp):
        d = dag(pp); lvl = {}
        for sid in d["order"]: lvl[sid] = 1 + max([lvl[a] for a, b in d["edges"] if b == sid] or [-1]) if any(b == sid for a, b in d["edges"]) else 0
        return d, lvl
    s = Svg(860, 470, "Handoff: a procedure as a verified graph, and a detected gap"); s.text(430, 24, "Handoff: a missing step is found because something downstream needs what it provides", 15, "middle", weight="700")
    for panel, (pp, ox, title) in enumerate(((p, 20, "complete procedure (garage-door gearbox, synthetic)"), (q, 450, "step g4 'remove the drive belt' deleted"))):
        d, lvl = layout(pp); s.text(ox, 52, title, 12, weight="700"); rows = {}
        for sid in d["order"]: rows.setdefault(lvl[sid], []).append(sid)
        pos = {}
        for L, ids in sorted(rows.items()):
            for j, sid in enumerate(ids): pos[sid] = (ox + 10 + L * 52, 80 + j * 40)
        for a, b in d["edges"]:
            if a in pos and b in pos: s.arrow(pos[a][0] + 38, pos[a][1] + 12, pos[b][0], pos[b][1] + 12, "#9ca3af", 1)
        for sid, (x, y) in sorted(pos.items()): bad = panel == 1 and any(gp["needed_by"] == sid for gp in g); s.rect(x, y, 38, 24, "#fee2e2" if bad else "white", RED if bad else INK, 4); s.text(x + 19, y + 16, sid, 10, "middle", RED if bad else INK, "700")
    s.rect(450, 270, 400, 150, "#fef2f2", RED, 8); s.text(462, 292, "the checker's output", 12, weight="700", fill=RED)
    for i, gp in enumerate(g[:3]): s.text(462, 316 + i * 40, f"{gp['kind']}: fact '{gp['fact']}' needed by {gp['needed_by']}", 11, weight="600"); s.text(462, 330 + i * 40, gp["question"][:62] + ("…" if len(gp["question"]) > 62 else ""), 10, fill=MUTE)
    s.text(20, 300, "Each step lists what must already be true (requires) and what it makes true/false (adds, removes).", 11, fill=MUTE); s.text(20, 318, "Replaying the steps finds every unmet precondition; each becomes ONE targeted question.", 11, fill=MUTE)
    s.text(20, 336, "Answering inserts the step and the graph closes. The trainee guide uses the same graph.", 11, fill=MUTE)
    return s
def fig_step_scores():
    import statistics
    from handoff.scoring import threshold_curve, sim_text, agreement_kappa, step_scores, DEFAULT_THRESHOLD
    from handoff.simulate import dataset
    s = Svg(860, 400, "Step scores: the hidden threshold, and how the two signals agree"); s.text(430, 24, "Step scores: one extraction, very different headline numbers", 15, "middle", weight="700")
    d = dataset(range(100, 140)); cur = threshold_curve(d, sim_text); ox, oy, W, H = 60, 60, 340, 220
    s.text(ox, 50, "A. word-overlap recall and precision vs matcher threshold", 11, weight="700"); s.line(ox, oy + H, ox + W, oy + H, MUTE); s.line(ox, oy, ox, oy + H, MUTE)
    for g in (0, .5, 1.0): y = oy + H - g * H; s.line(ox - 4, y, ox + W, y, GRID); s.text(ox - 8, y + 4, f"{g:g}", 10, "end", MUTE)
    mx = lambda t: ox + (t - 0.1) / 0.6 * W; my = lambda v: oy + H - v * H
    for i in range(len(cur) - 1): s.line(mx(cur[i][0]), my(cur[i][1]), mx(cur[i + 1][0]), my(cur[i + 1][1]), BLUE, 2); s.line(mx(cur[i][0]), my(cur[i][2]), mx(cur[i + 1][0]), my(cur[i + 1][2]), ORANGE, 2, "5 3")
    for t, r, p in cur: s.circle(mx(t), my(r), 4, BLUE); s.text(mx(t), oy + H + 16, f"{t:g}", 10, "middle", MUTE)
    s.text(ox + W / 2, oy + H + 34, "matcher threshold", 11, "middle", MUTE); s.rect(ox + 8, oy + 8, 10, 10, BLUE); s.text(ox + 24, oy + 17, "recall", 11); s.line(ox + 80, oy + 13, ox + 100, oy + 13, ORANGE, 2, "5 3"); s.text(ox + 106, oy + 17, "precision", 11)
    r2, r5 = [r for t, r, p in cur if t == 0.2][0], [r for t, r, p in cur if t == 0.5][0]; s.text(ox + 20, oy + H - 150, f"recall {r2:.2f} at 0.2", 11, fill=INK); s.text(ox + 190, oy + 30, f"{r5:.2f} at 0.5", 11, fill=RED, weight="700")
    levels = [("clean", dict(p_fact_drop=0.0, p_halluc=0.0)), ("default", dict()), ("heavy", dict(p_fact_drop=0.35, p_halluc=0.25)), ("extreme", dict(p_fact_drop=0.6, p_halluc=0.4)), ("none", dict(p_fact_drop=1.0, p_halluc=0.0))]
    bx = 470; s.text(bx, 50, "B. signal agreement (kappa) and F1 as effects get noisier", 11, weight="700"); s.line(bx, oy + H, bx + 360, oy + H, MUTE)
    for i, (lab, kw) in enumerate(levels):
        dd = dataset(range(100, 130), **kw); k = statistics.fmean(agreement_kappa(e, kk) for e, kk, t, n in dd); rb, pb = step_scores(dd); f1 = 2 * rb * pb / (rb + pb); x = bx + 10 + i * 70
        s.rect(x, oy + H - k * H, 28, k * H, GREEN, None, 2); s.text(x + 14, oy + H - k * H - 5, f"{k:.2f}", 10, "middle", GREEN, "700"); s.rect(x + 30, oy + H - f1 * H, 28, f1 * H, BLUE, None, 2, op=.55); s.text(x + 44, oy + H - f1 * H - 5, f"{f1:.2f}", 10, "middle", BLUE); s.text(x + 30, oy + H + 16, lab, 10, "middle", MUTE)
    s.rect(bx + 10, oy + 6, 10, 10, GREEN); s.text(bx + 26, oy + 15, "kappa (words vs effects)", 11); s.rect(bx + 190, oy + 6, 10, 10, BLUE, None, 0, op=.55); s.text(bx + 206, oy + 15, "F1 of the boosted scorer", 11)
    s.text(60, 352, "Recall of the same extraction moves from 0.99 to 0.61 with the threshold, so every score is reported with its threshold curve, never as a single number.", 11, fill=MUTE); s.text(60, 372, "Everything here is on a SIMULATED extractor and saturates near 1.0: it cannot rank matchers on hard data (docs/SCORING.md).", 11, fill=MUTE)
    return s
def fig_privacy():
    s = Svg(860, 330, "Privacy flow: every arrow passes a gate that has a test"); s.text(430, 24, "Data path: nothing moves without a gate, and no gate is optional", 15, "middle", weight="700")
    steps = [("person", "owns all data"), ("consent gate", "default deny · expiry · revoke"), ("describe(frame)", "injected Meta model"), ("redact", "PII patterns · Luhn"), ("event", "no media field"), ("personal ledger", "owner-only reads"), ("shared summary", "owner chooses"), ("roll-up", "k ≥ 5 · clip · noise")]
    for i, (a, b) in enumerate(steps):
        x = 20 + (i % 4) * 210; y = 70 + (i // 4) * 120; gate = i in (1, 3, 5, 7); box(s, x, y, 180, 56, a, b, "#ecfdf5" if gate else "white", GREEN if gate else INK)
        if i < 7:
            if i % 4 == 3: s.arrow(x + 90, y + 56, 20 + 90, y + 120, "#9ca3af", 1.2)
            else: s.arrow(x + 180, y + 28, x + 210, y + 28, "#9ca3af", 1.2)
    s.text(20, 290, "raw frames and audio stop at 'redact': they are dropped, never stored. A revoked consent stops the next frame.", 11, fill=MUTE); s.text(20, 308, "Group views contain no person identifier and are suppressed below 5 contributors.", 11, fill=MUTE)
    return s
def fig_gossip():
    from coherence.swarm import StreamCell, gossip_round, converged
    Ns = [8, 16, 32, 64, 128, 256]; data = []
    for n in Ns:
        rs = []
        for seed in range(8):
            rnd = random.Random(seed); cells = [StreamCell(f"c{i}") for i in range(n)]; [c.publish_D(round(rnd.random(), 3), "N") for c in cells]; k = 0
            while not converged(cells) and k < 60: gossip_round(cells, rnd); k += 1
            rs.append(k)
        data.append(sum(rs) / len(rs))
    s = Svg(860, 340, "Gossip convergence versus number of cells"); s.text(430, 24, "Cache-to-cache gossip: rounds until every cell holds identical state", 15, "middle", weight="700")
    base, top = 280, 60; mx = lambda i: 110 + i * 130; my = lambda v: base - v / 14 * (base - top)
    s.line(80, base, 800, base, MUTE); s.line(80, top, 80, base, MUTE)
    for v in (0, 4, 8, 12): s.line(76, my(v), 800, my(v), GRID); s.text(70, my(v) + 4, str(v), 10, "end", MUTE)
    for i, n in enumerate(Ns): s.text(mx(i), base + 18, f"{n} cells", 10, "middle", MUTE)
    for i in range(len(Ns) - 1): s.line(mx(i), my(data[i]), mx(i + 1), my(data[i + 1]), BLUE, 2)
    for i, (n, v) in enumerate(zip(Ns, data)): s.circle(mx(i), my(v), 5, BLUE); s.text(mx(i), my(v) - 10, f"{v:.1f}", 11, "middle", INK, "700"); s.circle(mx(i), my(math.log2(n)), 4, "none", ORANGE);
    s.text(90, 310, "blue: measured mean rounds (8 seeds each)   orange rings: log2(N)", 11, fill=MUTE)
    return s
def fig_speed():
    p = os.path.join(ROOT, "docs", "data", "bench.json"); s = Svg(860, 330, "Rust versus Python speed")
    if not os.path.exists(p): s.text(430, 160, "run scripts/bench_record.py to record the benchmark", 13, "middle", MUTE); return s
    b = json.load(open(p)); s.text(430, 24, f"Measured speed, same machine ({b['host']}): Python vs Rust", 15, "middle", weight="700")
    rows = [("WF-13D table build (262,144 entries)", b["py_table_ms"], b["rs_table_ms"], "ms"), ("WF-13D one address", b["py_word_ns"], b["rs_word_ns"], "ns"), ("ant, per step", b["py_ant_ns"], b["rs_ant_ns"], "ns")]
    for i, (lab, py, rs, u) in enumerate(rows):
        y = 70 + i * 80; s.text(30, y + 4, lab, 12, weight="600"); lo, hi = 0, math.log10(max(py, rs) * 3)
        wpy = (math.log10(py) + 1) / (hi + 1) * 520; wrs = (math.log10(rs) + 1) / (hi + 1) * 520
        s.rect(30, y + 12, wpy, 18, BLUE); s.text(36 + wpy, y + 26, f"Python {py:,.1f} {u}", 10); s.rect(30, y + 34, wrs, 18, ORANGE); s.text(36 + wrs, y + 48, f"Rust {rs:,.1f} {u}  ({py / rs:.0f}x faster)", 10, weight="700")
    s.text(30, 312, "log-scaled bars; ratios depend on the machine; reproduce with scripts/bench_record.py", 10, fill=MUTE)
    return s
def fig_pipeline():
    s = Svg(860, 330, "Packaging and install pipeline"); s.text(430, 24, "Release: build once from a clean commit, verify everywhere, install offline, roll back on failure", 15, "middle", weight="700")
    top = [("clean git tree", "refuses dirty"), ("release_check", "license · SPDX · deps · scan"), ("wheels + sdists", "SOURCE_DATE_EPOCH"), ("cargo --locked", "libs + C headers"), ("SBOM · SHA256SUMS", "CycloneDX · optional ssh sig"), ("bundle .tar.gz", "deterministic")]
    for i, (a, b) in enumerate(top):
        x = 15 + i * 140; box(s, x, 50, 128, 52, a, b, "white", INK, 11)
        if i < 5: s.arrow(x + 128, 76, x + 140, 76, "#9ca3af", 1.2)
    bot = [("verify", "sha256 (+ signature)"), ("venv + pip", "offline, --require-hashes"), ("native libs", "lib · include · pkg-config"), ("metacoh doctor", "9 self-checks"), ("receipt", "uninstall list"), ("rollback", "on any failure")]
    for i, (a, b) in enumerate(bot):
        x = 15 + i * 140; box(s, x, 190, 128, 52, a, b, "#ecfdf5" if i != 5 else "#fef2f2", GREEN if i != 5 else RED, 11)
        if i < 4: s.arrow(x + 128, 216, x + 140, 216, "#9ca3af", 1.2)
    s.arrow(430, 102, 430, 190, MUTE, 1.5, "4 3"); s.text(440, 150, "install.sh", 12, weight="700"); s.text(30, 280, "Linux x86_64 is tested end to end. The Windows installer is written but untested; macOS is not supported yet.", 11, fill=MUTE)
    return s
FIGS = [("architecture", fig_architecture), ("wf13d-address", fig_wf13d), ("distance-from-coherence", fig_distance), ("ant-highway", fig_ant), ("ant-steps", fig_ant_steps), ("tesseract", fig_tesseract),
        ("attention-mirror", fig_mirror), ("handoff-graph", fig_handoff), ("step-scores", fig_step_scores), ("privacy-flow", fig_privacy), ("gossip", fig_gossip), ("speed", fig_speed), ("pipeline", fig_pipeline)]
def main():
    check = "--check" in sys.argv; out = tempfile.mkdtemp() if check else os.path.join(ROOT, "docs", "figures"); os.makedirs(out, exist_ok=True); bad = []
    for name, fn in FIGS:
        svg = fn().doc(); path = os.path.join(out, name + ".svg"); open(path, "w", encoding="utf-8", newline="\n").write(svg)
        if check:
            cur = os.path.join(ROOT, "docs", "figures", name + ".svg")
            if not os.path.exists(cur) or open(cur, encoding="utf-8").read() != svg: bad.append(name)
    print(("figures: " + ("STALE: " + ", ".join(bad) if bad else f"all {len(FIGS)} identical to the committed files")) if check else f"wrote {len(FIGS)} figures to {out}"); sys.exit(1 if bad else 0)
if __name__ == "__main__": main()
