import { s, h } from '../lib/dom.js';
import { catVar, dur, clock, CAT } from '../lib/fmt.js';
import { tooltip } from '../ui/tip.js';
import { noteOf } from '../lib/harmony.js';

// Ring: progress toward a goal. Text lives in the DOM beside it, so it is readable and selectable.
export function ring(frac, { size = 132, stroke = 12, label }) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r, f = Math.max(0, Math.min(1, frac));
  return s('svg', { viewBox: `0 0 ${size} ${size}`, width: size, height: size, role: 'img', 'aria-label': label },
    s('circle', { cx: size / 2, cy: size / 2, r, fill: 'none', stroke: 'var(--surface-3)', 'stroke-width': stroke }),
    s('circle', { cx: size / 2, cy: size / 2, r, fill: 'none', stroke: 'var(--accent)', 'stroke-width': stroke, 'stroke-linecap': 'round',
      'stroke-dasharray': `${c * f} ${c}`, transform: `rotate(-90 ${size / 2} ${size / 2})`, style: { transition: 'stroke-dasharray .6s var(--ease)' } }));
}

// Day strip: every block of the day on one line, colour plus a tooltip with the exact times. Keyboard: each block is focusable.
// Category texture patterns for SVG: tone plus a pattern, so categories never rely on colour alone.
const PAT = { learn: 'dots', other: 'dots', design: 'hatch', distraction: 'cross', idle: 'lines' };
export function patterns() {
  return s('defs', {}, Object.entries(PAT).map(([c, kind]) => s('pattern', { id: `tx-${c}`, width: 4, height: 4, patternUnits: 'userSpaceOnUse' },
    s('rect', { width: 4, height: 4, style: { fill: `var(--c-${c})` } }),
    kind === 'dots' || kind === 'fine' ? s('circle', { cx: 2, cy: 2, r: kind === 'dots' ? .8 : .6, style: { fill: kind === 'dots' ? 'var(--surface)' : 'var(--text)' }, opacity: kind === 'dots' ? .7 : .25 })
      : kind === 'lines' ? s('line', { x1: 0, y1: 0, x2: 0, y2: 4, style: { stroke: 'var(--text)' }, 'stroke-width': .5, opacity: .15 })
      : [s('path', { d: 'M-1 5 5 -1', style: { stroke: 'var(--surface)' }, 'stroke-width': .7, opacity: .6 }), kind === 'cross' ? s('path', { d: 'M-1 -1 5 5', style: { stroke: 'var(--surface)' }, 'stroke-width': .7, opacity: .6 }) : null])));
}
export const catFill = (c) => (PAT[String(c).toLowerCase()] ? `url(#tx-${String(c).toLowerCase()})` : catVar(c));

export function dayStrip(blocks, { t0, t1, height = 56 }) {
  const W = 1000, x = (t) => ((t - t0) / (t1 - t0)) * W;
  const el = s('svg', { viewBox: `0 0 ${W} ${height}`, preserveAspectRatio: 'none', role: 'img', 'aria-label': `Day timeline, ${blocks.length} blocks` }, patterns());
  for (const b of blocks) {
    const r = s('rect', { x: x(b.start), y: 0, width: Math.max(1.2, x(b.end) - x(b.start)), height, style: { fill: catFill(b.category) }, tabindex: 0,
      'aria-label': `${b.app} ${b.domain}, ${b.category}, ${clock(b.start)} to ${clock(b.end)}, ${dur(b.seconds)}`, opacity: b.category === 'Idle' ? 0.5 : 1 });
    tooltip(r, () => [h('b', {}, b.domain || b.app), h('div', { class: 'faint num' }, `${clock(b.start)}–${clock(b.end)} · ${dur(b.seconds)}`), h('div', {}, b.category)]);
    el.append(r);
  }
  return el;
}

// One stacked bar for parts of a whole, with direct labels beneath (no pie).
export function stacked(by) {
  const tot = Object.values(by).reduce((a, b) => a + b, 0) || 1;
  const order = CAT.filter((c) => by[c]);
  return h('div', { class: 'stack' },
    h('div', { class: 'tonebar', role: 'img', 'aria-label': order.map((c) => `${c} ${Math.round((by[c] / tot) * 100)} percent`).join(', ') },
      order.map((c) => h('i', { class: `tx tx-${c.toLowerCase()}`, style: { flexBasis: `${(by[c] / tot) * 100}%`, '--c': catVar(c) }, title: `${c} ${dur(by[c])}` }))),
    h('div', { class: 'legend' }, order.map((c) => h('span', {}, h('i', { class: `swatch tx tx-${c.toLowerCase()}`, style: { '--c': catVar(c) } }), c, noteOf(c) ? h('i', { class: 'note', title: 'scale degree' }, noteOf(c)) : null, ' ', h('b', { class: 'num nowrap' }, dur(by[c]))))));
}

export function hbars(rows, color = 'var(--text)') {
  const max = Math.max(1, ...rows.map((r) => r[1]));
  return h('div', { class: 'sheet-list' }, rows.map(([name, v]) => h('div', { class: 'hbar' },
    h('span', { class: 'trunc', title: name }, name), h('div', { class: 'bar', role: 'presentation' }, h('i', { style: { '--f': String(v / max), background: color } })), h('span', { class: 'num nowrap' }, dur(v)))));
}

// Flow graph of the paths taken. Node size = time spent, edge width = how often. `hot` highlights one route.
export function flow(trans, byApp, hot = []) {
  const names = [...new Set([...byApp.map((a) => a[0]), ...trans.flatMap((t) => [t.src, t.dst])])].slice(0, 12);
  const compact = matchMedia('(max-width: 640px)').matches;   // phones: smaller canvas so labels stay readable
  const secs = Object.fromEntries(byApp), W = compact ? 340 : 640, H = compact ? 380 : 420, cx = W / 2, cy = H / 2, R = compact ? 100 : 160;
  const pos = Object.fromEntries(names.map((n, i) => { const a = (i / names.length) * 2 * Math.PI - Math.PI / 2; return [n, [cx + R * Math.cos(a), cy + R * Math.sin(a), a]]; }));
  const maxC = Math.max(1, ...trans.map((t) => t.count)), maxS = Math.max(1, ...Object.values(secs));
  const hotSet = new Set(hot.slice(0, -1).map((n, i) => `${n}>${hot[i + 1]}`));
  const svg = s('svg', { class: 'flow', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': `Paths between ${names.length} apps. The table below lists every move.` },
    s('defs', {}, s('marker', { id: 'ah', viewBox: '0 0 8 8', refX: 7, refY: 4, markerUnits: 'userSpaceOnUse', markerWidth: 9, markerHeight: 9, orient: 'auto' }, s('path', { d: 'M0 0 8 4 0 8z', fill: 'var(--accent)' }))));
  for (const t of trans) {
    if (!pos[t.src] || !pos[t.dst]) continue;
    const [x1, y1] = pos[t.src], [x2, y2] = pos[t.dst], mx = (x1 + x2) / 2 + (cy - (y1 + y2) / 2) * 0.28, my = (y1 + y2) / 2 + ((x1 + x2) / 2 - cx) * 0.28;
    const isHot = hotSet.has(`${t.src}>${t.dst}`);
    svg.append(s('path', { class: `edge${isHot ? ' hot' : hot.length ? ' dim' : ''}`, d: `M${x1},${y1} Q${mx},${my} ${x2},${y2}`, 'stroke-width': 1 + (t.count / maxC) * 5, 'marker-end': 'url(#ah)' },
      s('title', {}, `${t.src} to ${t.dst}: ${t.count} times, average stay ${t.avg_stay_s}s`)));
  }
  for (const n of names) {
    const [x, y, a] = pos[n], r = 7 + ((secs[n] || 0) / maxS) * 15, right = Math.cos(a) >= 0;
    svg.append(s('g', { class: 'node' }, s('circle', { cx: x, cy: y, r, fill: hot.includes(n) ? 'var(--accent-2)' : 'var(--accent)' }, s('title', {}, `${n}: ${dur(secs[n] || 0)}`)),
      s('text', { x: x + (right ? r + 6 : -r - 6), y: y + 4, 'text-anchor': right ? 'start' : 'end' }, n.length > (compact ? 13 : 18) ? n.slice(0, compact ? 12 : 17) + '…' : n)));
  }
  return svg;
}