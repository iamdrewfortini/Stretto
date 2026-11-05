// The day as harmony: 10-minute bars, each a chord made of the categories that sounded in it (time-weighted).
// Chord colour = its centre on the circle of fifths (DFT f5 phase), saturation = clarity (|f5|); a cluster with no centre goes grey.
// Below, a tension ribbon: offset = distance from the tonic in fifths, width = spread (Herremans & Chew's tension ribbons, simplified).
import { h, s } from '../lib/dom.js';
import { clock, dur } from '../lib/fmt.js';
import { NOTES, TONIC, pcOf, chord, chordColor } from '../lib/harmony.js';

const BAR = 600;
export function bars(blocks, t0, t1) {
  const out = [];
  for (let a = t0; a < t1; a += BAR) {
    const z = a + BAR, vec = new Array(12).fill(0), parts = {}; let rest = 0;
    for (const b of blocks) {
      const o = Math.max(0, Math.min(z, b.end) - Math.max(a, b.start)); if (!o) continue;
      const p = pcOf(b.category); if (p === null) rest += o; else { vec[p] += o; parts[b.category] = (parts[b.category] || 0) + o; }
    }
    const c = chord(vec);
    out.push({ a, z, c: c && c.tot >= rest ? c : null, parts, rest, vec });
  }
  return out;
}

export function harmony(blocks, { t0, t1 }) {
  const bs = bars(blocks, t0, t1), sounded = bs.filter((b) => b.c);
  if (!sounded.length) return h('p', { class: 'muted' }, 'Nothing sounded today yet.');
  const home = sounded.filter((b) => b.c.dist < 0.5 && b.c.clarity > 0.7).length;
  const far = sounded.reduce((m, b) => (b.c.dist > (m ? m.c.dist : -1) ? b : m), null);
  const col = (b) => chordColor(b.vec, b.c.clarity);
  const lane = h('div', { class: 'hl-lane', role: 'list', 'aria-label': 'Chords in 10-minute bars' }, bs.map((b) => {
    if (!b.c) return h('i', { class: 'hl-rest', role: 'listitem', 'aria-label': `${clock(b.a)}: rest` });
    const mix = Object.entries(b.parts).sort((x, y) => y[1] - x[1]).map(([k, v]) => `${k} ${dur(v)}`).join(', ');
    const label = `${clock(b.a)}–${clock(b.z)}: centre ${NOTES[b.c.centre].note}, clarity ${b.c.clarity.toFixed(2)}${b.c.dist >= 0.5 ? `, ${b.c.dist.toFixed(1)} fifths from home` : ', home'} (${mix})`;
    return h('i', { class: 'hl-bar', role: 'listitem', tabindex: 0, title: label, 'aria-label': label, style: { background: col(b), '--clar': String(b.c.clarity) } },
      b.c.clarity > 0.55 ? h('span', {}, NOTES[b.c.centre].note) : null);
  }));
  // tension ribbon
  const W = 1000, H = 64, cw = W / bs.length, mid = 14, pts = bs.map((b, i) => (b.c ? [i * cw + cw / 2, mid + b.c.dist * 7.5, 3 + b.c.spread * 18, col(b)] : null));
  let top = '', bot = ''; pts.forEach((p) => { if (p) top += `${top ? 'L' : 'M'}${p[0]},${p[1] - p[2] / 2} `; }); [...pts].reverse().forEach((p) => { if (p) bot += `L${p[0]},${p[1] + p[2] / 2} `; });
  const ribbon = s('svg', { class: 'hl-ribbon', viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', 'aria-hidden': 'true' },
    s('line', { x1: 0, x2: W, y1: mid, y2: mid, class: 'hl-home', 'vector-effect': 'non-scaling-stroke' }),
    s('path', { d: `${top}${bot}Z`, class: 'hl-band' }),
    pts.flatMap((p, i) => (p && pts[i + 1] ? [s('line', { x1: p[0], y1: p[1], x2: pts[i + 1][0], y2: pts[i + 1][1], 'vector-effect': 'non-scaling-stroke', style: { stroke: p[3] }, class: 'hl-path' })] : [])));
  return h('div', { class: 'hl' },
    h('div', { class: 'hl-head' }, h('div', {}, h('b', { class: 'num' }, `${home} of ${sounded.length}`), h('span', {}, `bars at home (${NOTES[TONIC].note}, clear)`)),
      far && far.c.dist >= 0.5 ? h('div', {}, h('b', { class: 'num' }, `${clock(far.a)}`), h('span', {}, `furthest from home: ${NOTES[far.c.centre].note}, ${far.c.dist.toFixed(1)} fifths`)) : null),
    lane, h('div', { class: 'hl-ribbon-wrap' }, ribbon, h('span', { class: 'hl-home-label' }, `home ${NOTES[TONIC].note}`)),
    h('div', { class: 'strip-axis' }, h('span', {}, clock(t0)), h('span', {}, clock((t0 + t1) / 2)), h('span', {}, clock(t1))),
    h('p', { class: 'faint hl-note' }, 'Each bar is a chord of the categories that sounded in it. Colour is its centre on the circle of fifths; grey means no clear centre. The ribbon drops as the day moves away from home and widens as it scatters.'));
}
