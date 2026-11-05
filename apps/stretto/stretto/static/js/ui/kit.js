import { h } from '../lib/dom.js';
import { icon } from './icons.js';
import { dur, clock } from '../lib/fmt.js';

export const pill = (text, tone = '') => h('span', { class: `pill ${tone}` }, text);
export function stat(label, value, sub, { tone = '', frac = null, flat = false } = {}) {
  return h('div', { class: flat ? 'stat flat' : 'card stat' }, h('span', { class: 'k' }, label), h('span', { class: 'v', style: tone ? { color: `var(--${tone})` } : {} }, value),
    frac == null ? null : h('div', { class: 'bar', role: 'presentation' }, h('i', { style: { '--f': String(Math.max(0, Math.min(1, frac))), background: tone ? `var(--${tone})` : 'var(--accent)' } })),
    h('span', { class: 's' }, sub));
}
export const skeleton = (n = 3) => h('div', { class: 'page quiet skeleton-page', 'aria-busy': 'true', 'aria-label': 'Loading' }, h('div', { class: 'skeleton', style: { height: '44px', width: '40%' } }),
  h('div', { class: 'grid g4' }, Array.from({ length: 4 }, () => h('div', { class: 'skeleton', style: { height: '112px' } }))), Array.from({ length: n }, () => h('div', { class: 'skeleton', style: { height: '180px' } })));
export const emptyState = (title, body, action) => h('div', { class: 'card empty' }, icon('spark', 28), h('h3', {}, title), h('p', {}, body), action);
export const errorState = (msg, retry) => h('div', { class: 'card empty err', role: 'alert' }, icon('alert', 28), h('h3', {}, 'Couldn’t load this view'), h('p', {}, msg), h('button', { class: 'btn primary', onclick: retry }, 'Try again'));

export const KIND = {
  detour: { icon: 'alert', title: 'Detour', tone: 'bad' }, ping_pong: { icon: 'swap', title: 'Ping-pong', tone: 'warn' },
  repeated_path: { icon: 'repeat', title: 'Repeated route', tone: 'signal' }, fragmented_focus: { icon: 'timer', title: 'Broken focus', tone: 'info' },
};
export function findingCard(f, { open = false, onSee, on = false, lead = null, note = null } = {}) {
  const k = KIND[f.kind] || KIND.detour;
  const card = h('article', { class: 'finding', 'data-open': String(open), 'data-on': String(on) });
  const toggle = h('button', { class: 'btn sm ghost', 'aria-expanded': String(open), onclick: () => { const o = card.dataset.open !== 'true'; card.dataset.open = String(o); toggle.setAttribute('aria-expanded', String(o)); } }, 'Evidence');
  card.append(h('div', { class: `ico ${f.kind}` }, icon(k.icon)),
    h('div', { class: 'stack', style: { gap: '4px' } }, h('div', { class: 'row wrap' }, h('span', { class: 't' }, k.title), f.basis && f.basis !== 'measured' ? pill(f.basis === 'inferred' ? 'Inferred' : 'Estimated', 'info') : null, h('span', { class: 'cost num' }, dur(f.seconds))), lead ? h('div', { class: 'lead' }, lead) : null, h('p', { class: 'muted' }, f.suggestion), note ? h('p', { class: 'bound' }, note) : null),
    h('div', { class: 'row' }, onSee ? h('button', { class: 'btn sm', onclick: onSee }, 'See route') : null, toggle),
    h('div', { class: 'evid' }, f.blocks.slice(0, 12).map((b) => h('div', { class: 'trunc' }, `${clock(b.start)}–${clock(b.end)}  ${b.what}`)), f.blocks.length > 12 ? h('div', {}, `+ ${f.blocks.length - 12} more`) : null));
  return card;
}
export const route = (names) => h('div', { class: 'route' }, names.flatMap((n, i) => [i ? h('span', { class: 'arr', 'aria-hidden': 'true' }, '→') : null, h('span', { class: 'chip' }, n)]));
// Rolling digits: only the digits that changed move, each sliding in the direction of the change (R09).
export function roll(el, text) {
  const prev = el.dataset.v ?? ''; if (prev === text) return; el.dataset.v = text; el.classList.add('roll');
  const kids = [...text].map((ch, i) => { const was = prev[prev.length - text.length + i]; const sp = h('i', {}, ch);
    if (was != null && was !== ch && /\d/.test(ch) && /\d/.test(was)) sp.className = Number(ch) > Number(was) ? 'up' : 'dn'; return sp; });
  el.replaceChildren(...kids);
}
// A tick that draws itself: the circle, then the stroke (R11).
export function okDraw() { const s = (t, a) => { const e = document.createElementNS('http://www.w3.org/2000/svg', t); for (const k in a) e.setAttribute(k, a[k]); return e; };
  const svg = s('svg', { class: 'ok-draw', viewBox: '0 0 22 22', 'aria-hidden': 'true' }); svg.append(s('circle', { cx: 11, cy: 11, r: 9 }), s('path', { d: 'M6.5 11.5 L9.5 14.5 L15.5 8' })); return svg; }

// Delta chip: arrow + signed change; tone = sign(Δ) · polarity of the metric (+1 when up is good, −1 when up is bad). Absent delta → nothing.
export function deltaChip(delta, pct, polarity = 1, fmt = (v) => dur(Math.abs(v))) {
  if (delta == null || delta === 0) return null;
  const up = delta > 0, tone = up * polarity > 0 || (!up && polarity < 0) ? 'good' : 'bad';
  return h('span', { class: `chip delta ${tone}`, title: 'vs the previous day with data' }, h('span', { 'aria-hidden': 'true' }, up ? '↗' : '↘'), h('span', { class: 'num' }, `${up ? '+' : '−'}${pct != null ? Math.round(Math.abs(pct) * 100) + ' %' : fmt(delta)}`));
}
