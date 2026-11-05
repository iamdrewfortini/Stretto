import { h } from '../lib/dom.js';
import { api } from '../lib/api.js';
import { dur, pct, nice } from '../lib/fmt.js';
import { patch } from '../lib/router.js';
import { icon } from '../ui/icons.js';
import { toast } from '../ui/toast.js';
import { stat, pill, emptyState, findingCard } from '../ui/kit.js';
import { deltaChip } from '../ui/kit.js';
import { dayStrip, stacked, hbars } from '../charts/svg.js';
import { dayPacket, resonance } from '../charts/wave.js';
import { harmony } from '../charts/harmony.js';
import { clock } from '../lib/fmt.js';

export default {
  id: 'today', key: 't', dated: true, title: 'Today', icon: 'sun',
  load: async (ctx) => { const [d, att] = await Promise.all([api.get('/api/day?date=' + ctx.date), api.get('/api/attention?date=' + ctx.date).catch(() => null)]); d.attention = att; return d; },
  view(d, ctx) {
    const sm = d.summary, tight = sm.total_s ? Math.max(0, Math.round(100 * (1 - d.loss_s / sm.total_s))) : null;
    const head = h('div', { class: 'page-head' }, h('div', { class: 'grow' }, h('h1', {}, ctx.isToday ? 'Today' : nice(ctx.date)), h('p', {}, sm.total_s ? `${dur(sm.total_s)} active across ${d.blocks.length} blocks` : nice(ctx.date))),
      d.simulated ? pill('Simulated data', '') : null);
    if (!sm.total_s) {
      return h('div', { class: 'page' }, head, emptyState('Nothing recorded for this day', 'Stretto shows measurements only. Start the collector, or load a clearly labelled simulated day to explore the app.',
        h('button', { class: 'btn primary', onclick: async (e) => { e.target.disabled = true; try { const r = await api.post('/api/demo/seed'); toast('Loaded a simulated day'); patch({ d: r.date }); } catch (er) { toast(er.message, 'bad'); e.target.disabled = false; } } }, 'Load a simulated day')));
    }
    const counts = d.findings.reduce((a, f) => ((a[f.kind] = (a[f.kind] || 0) + 1), a), {});
    const why = Object.entries({ detour: 'detour', ping_pong: 'ping-pong run', repeated_path: 'repeated route' }).filter(([k]) => counts[k]).map(([k, n]) => `${counts[k]} ${n}${counts[k] > 1 ? 's' : ''}`).join(', ');
    const goalFrac = d.goal_s ? sm.focus_s / d.goal_s : 0, xp = d.xp, span = xp.next - xp.floor;
    const first = d.blocks[0].start, last = d.blocks[d.blocks.length - 1].end, t0 = Math.floor(first / 3600) * 3600, t1 = Math.ceil(last / 3600) * 3600;
    const hero = h('section', { class: 'card hero raised', 'aria-labelledby': 'hero-h' }, h('header', {}, h('h3', { id: 'hero-h' }, 'Tightness'), h('small', {}, `${d.blocks.length} blocks · ${dur(sm.total_s)} active`), deltaChip(sm.delta?.focus_s, sm.delta_pct?.focus_s, 1)),
      h('div', { class: 'hero-row' }, h('div', { class: 'hero-num' }, tight, h('small', {}, '%')),
        d.attention && d.attention.enough ? h('div', { class: 'att' }, h('span', { class: 'att-k' }, 'Attention'), h('b', { class: 'num' }, String(d.attention.score)), deltaChip(d.attention.delta_score, null, 1, (v) => String(Math.abs(v))),
          h('details', { class: 'att-f' }, h('summary', {}, 'How it’s measured'), h('p', {}, d.attention.formula), h('p', { class: 'faint' }, `${d.attention.shifts_per_hour} shifts/hour · median stay ${dur(d.attention.dwell_median_s)} · back from a detour in ${dur(d.attention.return_time_s.median)} (median). A summary of three measured things, not a medical measure.`))) : null,
        h('p', { class: 'muted hero-cap' }, d.loss_s ? [h('b', { class: 'signal-text num' }, dur(d.loss_s)), ` of ${dur(sm.total_s)} went to ${why}.`] : `No lost time found in ${dur(sm.total_s)} of active work.`),
        sm.overlap_s ? h('p', { class: 'faint hero-cap' }, `${dur(sm.overlap_s)} still counted twice across computers (a measurement, so a regression would show here).`) : sm.concurrent_s ? h('p', { class: 'faint hero-cap' }, `${dur(sm.concurrent_s)} with both computers active: counted once.`) : null),
      dayPacket(d.blocks, { t0, t1, live: ctx.isToday, day: ctx.date }),
      h('div', { class: 'strip' }, dayStrip(d.blocks, { t0, t1, height: 14 })), h('div', { class: 'strip-axis' }, h('span', {}, clock(t0)), h('span', {}, clock((t0 + t1) / 2)), h('span', {}, clock(t1))),
      h('p', { class: 'faint wave-legend' }, 'Bar height is focus; colour is the category’s note (teal D is focus, sky D♯ is drift); deeper shades are stretches over 40 minutes; dips mark dense switching. Dots above mark each switch.'));
    const harm = h('section', { class: 'card', 'aria-labelledby': 'harm-h' }, h('header', {}, h('h3', { id: 'harm-h' }, 'Harmony'), h('small', {}, '10-minute bars · tonic D = focus')), harmony(d.blocks, { t0, t1 }));
    const spectrum = h('section', { class: 'card', 'aria-labelledby': 'reso-h' }, h('header', {}, h('h3', { id: 'reso-h' }, 'Focus spectrum')), resonance(d.blocks));
    const goal = h('section', { class: 'card goalcard', 'aria-labelledby': 'goal-h' }, h('header', {}, h('h3', { id: 'goal-h' }, 'Focus goal'), h('small', { class: 'num' }, `${pct(sm.focus_s, d.goal_s)}%`)),
      h('div', { class: 'goal-line' }, h('b', { class: 'num' }, dur(sm.focus_s)), h('span', { class: 'muted' }, ` of ${dur(d.goal_s)}`)),
      h('div', { class: 'bar' }, h('i', { style: { '--f': String(Math.min(1, goalFrac)) } })),
      h('p', { class: 'faint goal-meta num' }, `Level ${xp.level} · ${xp.xp} / ${xp.next} XP · ${d.streak ? d.streak + '-day streak' : 'no streak yet'}${d.badges.length ? ' · ' + d.badges.join(', ') : ''}`));
    const kpis = h('div', { class: 'grid g2 mini' }, stat('Focus', dur(sm.focus_s), `${pct(sm.focus_s, sm.total_s)}% of active time`, { tone: 'c-build', frac: sm.focus_s / sm.total_s, flat: true }),
      stat('Distraction', dur(sm.distraction_s), `${pct(sm.distraction_s, sm.total_s)}% of active time`, { tone: 'c-distraction', frac: sm.distraction_s / sm.total_s, flat: true }),
      stat('Idle', dur(sm.idle_s), 'not counted as work', { flat: true }), stat('Switches', String(sm.switches), `${(sm.switches / Math.max(1, sm.total_s / 3600)).toFixed(1)} per active hour`, { flat: true }));
    const where = h('section', { class: 'card', 'aria-labelledby': 'where-h' }, h('header', {}, h('h3', { id: 'where-h' }, 'Where the time went')), stacked(sm.by_category),
      h('h3', { style: { margin: '20px 0 12px' } }, 'Top places'), hbars(sm.by_app.slice(0, 6)));
    let showAll = false; const list = h('div', { class: 'sheet-list' });
    const draw = () => { list.replaceChildren(...d.findings.slice(0, showAll ? 99 : 3).map((f, i) => findingCard(f, { onSee: () => { location.hash = `#/paths?d=${ctx.date}&f=${i}`; } })),
      d.findings.length > 3 ? h('button', { class: 'btn', onclick: () => { showAll = !showAll; draw(); } }, showAll ? 'Show fewer' : `Show ${d.findings.length - 3} more`) : null); };
    draw();
    const loss = h('section', { class: 'card', 'aria-labelledby': 'loss-h' }, h('header', {}, h('h3', { id: 'loss-h' }, 'Where you lost time'), h('small', {}, `${d.findings.length} findings, biggest first`)),
      d.findings.length ? list : h('p', { class: 'muted' }, 'Nothing to fix here. Focus stretches were whole.'));
    goal.append(kpis);
    return h('div', { class: 'page' }, head, hero, harm, h('div', { class: 'grid g-main' }, spectrum, goal), h('div', { class: 'grid g-main' }, loss, where));
  },
};