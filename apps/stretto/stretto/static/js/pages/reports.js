// Reports over 7 or 30 days, all from the server (/api/range, /api/patterns). Colour follows the harmonic system:
// focus in the tonic, categories in their notes with textures, lost time in the tritone.
import { h, s } from '../lib/dom.js';
import { api } from '../lib/api.js';
import { dur, CAT, catVar } from '../lib/fmt.js';
import { query, patch } from '../lib/router.js';
import { emptyState , deltaChip } from '../ui/kit.js';
import { noteOf } from '../lib/harmony.js';

const wd = (iso) => new Date(iso + 'T12:00:00').toLocaleDateString([], { weekday: 'short' });
const md = (iso) => new Date(iso + 'T12:00:00').toLocaleDateString([], { month: 'short', day: 'numeric' });

function trend(days, goal) {
  const W = 1000, H = 180, n = days.length, max = Math.max(goal * 1.15, ...days.map((d) => d.focus_s), 1);
  const X = (i) => (n === 1 ? W / 2 : (i / (n - 1)) * W), Y = (v) => H - (v / max) * (H - 16);
  let line = ''; days.forEach((d, i) => { line += `${i ? 'L' : 'M'}${X(i).toFixed(1)} ${Y(d.focus_s).toFixed(1)} `; });
  const tip = h('div', { class: 'rp-tip', hidden: true }), dot = h('i', { class: 'rp-dot', hidden: true });
  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', class: 'rp-trend', role: 'img', 'aria-label': `Daily focus over ${n} days; goal ${dur(goal)} a day.` },
    s('defs', {}, s('linearGradient', { id: 'rpg', x1: 0, y1: 0, x2: 0, y2: 1 }, s('stop', { offset: 0, 'stop-color': 'var(--tonic)', 'stop-opacity': .22 }), s('stop', { offset: 1, 'stop-color': 'var(--tonic)', 'stop-opacity': 0 }))),
    [.25, .5, .75].map((f) => s('line', { x1: 0, x2: W, y1: H * f, y2: H * f, class: 'rp-grid', 'vector-effect': 'non-scaling-stroke' })),
    s('path', { d: `${line} L${X(n - 1)} ${H} L${X(0)} ${H} Z`, fill: 'url(#rpg)' }),
    s('path', { d: line, class: 'rp-line', 'vector-effect': 'non-scaling-stroke' }),
    s('line', { x1: 0, x2: W, y1: Y(goal), y2: Y(goal), class: 'rp-goal', 'vector-effect': 'non-scaling-stroke' }));
  const wrap = h('div', { class: 'rp-plot', tabindex: 0, 'aria-label': 'Use left and right arrows to read each day' }, svg, dot, tip, h('span', { class: 'rp-goal-l', style: { top: `${(Y(goal) / H) * 100}%` } }, `goal ${dur(goal)}`));
  let cur = n - 1;
  const show = (i) => { cur = Math.max(0, Math.min(n - 1, i)); const d = days[cur], x = (X(cur) / W) * 100, y = (Y(d.focus_s) / H) * 100;
    dot.hidden = tip.hidden = false; dot.style.left = `${x}%`; dot.style.top = `${y}%`; tip.style.left = `${Math.min(88, Math.max(12, x))}%`; tip.style.top = `${y}%`;
    tip.replaceChildren(h('b', { class: 'num' }, dur(d.focus_s)), h('span', {}, `${wd(d.date)} ${md(d.date)}${d.loss_s ? ` · ${dur(d.loss_s)} lost` : ''}`)); };
  wrap.addEventListener('pointermove', (e) => { const r = wrap.getBoundingClientRect(); show(Math.round(((e.clientX - r.left) / r.width) * (n - 1))); });
  wrap.addEventListener('pointerleave', () => { dot.hidden = tip.hidden = true; });
  wrap.addEventListener('keydown', (e) => { if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); show(cur + (e.key === 'ArrowLeft' ? -1 : 1)); } });
  wrap.addEventListener('focus', () => show(cur)); wrap.addEventListener('blur', () => { dot.hidden = tip.hidden = true; });
  return h('div', {}, wrap, h('div', { class: 'strip-axis' }, h('span', {}, md(days[0].date)), n > 2 ? h('span', {}, md(days[Math.floor(n / 2)].date)) : null, h('span', {}, md(days[n - 1].date))));
}

function heat(days, best) {
  const max = Math.max(1, ...days.flatMap((d) => d.hours));
  return h('div', { class: 'rp-heat', role: 'table', 'aria-label': 'Focus by hour of day' },
    h('div', { class: 'rp-hrow hdr', role: 'row' }, h('span', {}), Array.from({ length: 24 }, (_, i) => h('span', { class: 'num', role: 'columnheader' }, i % 3 === 0 ? String(i).padStart(2, '0') : ''))),
    days.map((d) => h('div', { class: 'rp-hrow', role: 'row' }, h('span', { class: 'num', role: 'rowheader' }, `${wd(d.date)} ${md(d.date).split(' ')[1]}`),
      d.hours.map((v, i) => h('i', { role: 'cell', title: v ? `${md(d.date)} ${String(i).padStart(2, '0')}:00 · ${dur(v)} focus` : '', class: `${v ? 'on' : ''}${best && i >= best.start_hour && i < best.end_hour ? ' best' : ''}`, style: v ? { '--a': String(0.15 + (v / max) * 0.85) } : {} })))));
}

function cats(days) {
  const shown = days.length > 14 ? days.slice(-14) : days, max = Math.max(1, ...shown.map((d) => d.total_s));
  const used = CAT.filter((c) => c !== 'Idle' && shown.some((d) => d.by_category[c]));
  return h('div', {}, h('div', { class: 'rp-cols' }, shown.map((d) => h('div', { class: 'rp-col', title: `${md(d.date)}: ${dur(d.total_s)} active` },
    h('div', { class: 'rp-stack', style: { height: `${(d.total_s / max) * 100}%` } }, used.filter((c) => d.by_category[c]).map((c) => h('i', { class: `tx tx-${c.toLowerCase()}`, style: { flexGrow: String(d.by_category[c]), '--c': catVar(c) } }))),
    h('small', { class: 'num' }, wd(d.date).slice(0, 2))))),
    h('div', { class: 'legend' }, used.map((c) => h('span', {}, h('i', { class: `swatch tx tx-${c.toLowerCase()}`, style: { '--c': catVar(c) } }), c, h('i', { class: 'note' }, noteOf(c))))));
}

function goalCal(days, goal) {
  const first = new Date(days[0].date + 'T12:00:00'), lead = (first.getDay() + 6) % 7;   // weeks start Monday
  const C = 2 * Math.PI * 15;
  return h('div', { class: 'rp-cal' }, ['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((x) => h('b', {}, x)), Array.from({ length: lead }, () => h('span')),
    days.map((d) => { const f = Math.min(1, d.focus_s / goal), met = f >= 1;
      return h('span', { class: `rp-day${met ? ' met' : ''}`, title: `${md(d.date)}: ${dur(d.focus_s)} of ${dur(goal)}${met ? ' · goal met' : ''}` },
        s('svg', { viewBox: '0 0 36 36', 'aria-hidden': 'true' }, s('circle', { cx: 18, cy: 18, r: 15, class: 'rp-ring-bg' }), f > 0 ? s('circle', { cx: 18, cy: 18, r: 15, class: 'rp-ring', 'stroke-dasharray': `${C * f} ${C}`, transform: 'rotate(-90 18 18)' }) : null),
        h('i', { class: 'num' }, String(new Date(d.date + 'T12:00:00').getDate()))); }));
}

export default {
  id: 'reports', key: 'r', dated: false, title: 'Reports', icon: 'chart',
  load: async () => { const n = Number(query('r', '7')) || 7; const [range, pat] = await Promise.all([api.get(`/api/range?days=${n}`), api.get(`/api/patterns?days=${n}`).catch(() => null)]); return { range, pat, n }; },
  view(d) {
    const days = d.range.days, goal = d.range.goal_s || 14400, active = days.filter((x) => x.total_s > 0);
    const seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Range' }, [7, 30].map((n) => h('button', { 'aria-pressed': String(d.n === n), onclick: () => patch({ r: n === 7 ? '' : String(n) }) }, `${n} days`)));
    const head = h('div', { class: 'page-head' }, h('div', { class: 'grow' }, h('h1', {}, 'Reports'), h('p', {}, `${md(days[0].date)} – ${md(days[days.length - 1].date)} · ${active.length} active day${active.length === 1 ? '' : 's'}`)), seg);
    if (!active.length) return h('div', { class: 'page' }, head, emptyState('Nothing measured in this range', 'Reports fill in as the collector records days. Load the simulated day from Today to explore.'));
    const tot = days.reduce((a, x) => a + x.focus_s, 0), lost = days.reduce((a, x) => a + (x.loss_s || 0), 0), bestDay = days.reduce((m, x) => (x.focus_s > m.focus_s ? x : m), days[0]), met = days.filter((x) => x.focus_s >= goal).length;
    const tile = (k, v, sub, tone) => h('div', { class: 'stat flat' }, h('span', { class: 'k' }, k), h('span', { class: 'v', style: tone ? { color: `var(--${tone})` } : {} }, v), h('span', { class: 's' }, sub));
    const kpis = h('section', { class: 'card' }, h('div', { class: 'grid g5 rp-kpis' }, tile('Focus', dur(tot), `${d.n} days`, 'tonic'), tile('Daily average', dur(tot / Math.max(1, active.length)), 'on active days'),
      tile('Best day', dur(bestDay.focus_s), `${wd(bestDay.date)} ${md(bestDay.date)}`), tile('Lost time', dur(lost), 'detours, ping-pong, repeats', 'signal-text'), tile('Goal days', `${met} / ${days.length}`, `goal ${dur(goal)}`)));
    const p = d.pat;
    const notes = p && p.enough !== false ? h('p', { class: 'muted rp-notes' }, `Your best window is ${String(p.best_window.start_hour).padStart(2, '0')}:00–${String(p.best_window.end_hour).padStart(2, '0')}:00; you drift most around ${String(p.most_distracted_hour).padStart(2, '0')}:00.`) :
      h('p', { class: 'faint rp-notes' }, 'Patterns (best window, drift hour, trend) appear after a few measured days.');
    return h('div', { class: 'page' }, head, kpis,
      h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'Focus per day'), h('small', {}, 'hover or use the arrow keys'), d.range.prev_total_focus_s ? deltaChip(tot - d.range.prev_total_focus_s, (tot - d.range.prev_total_focus_s) / d.range.prev_total_focus_s, 1) : null), trend(days, goal)),
      h('div', { class: 'grid g-main' }, h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'When you focus'), h('small', {}, 'focus minutes by hour')), heat(days.slice(-14), p && p.enough !== false ? p.best_window : null), notes),
        h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'Goal')), goalCal(days, goal))),
      h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'Where the time went'), h('small', {}, days.length > 14 ? 'last 14 days' : 'by day')), cats(days)));
  },
};
