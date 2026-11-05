// Leaks: where the day goes missing. Leak data arrives either inside GET /api/insights
// or live from the raw runtime stream (/v1/events); the latest of each event wins.
import { h, s, clear } from '../lib/dom.js';
import { api } from '../lib/api.js';
import { pill, emptyState } from '../ui/kit.js';
import { hbars, ring } from '../charts/svg.js';

const COMPS = [['switching', 'Switching'], ['waiting', 'Waiting'], ['re-finding', 'Re-finding'], ['admin', 'Admin']];
const PERIODS = ['week', 'month', 'year', 'decade'];
const usd = (x) => `$${Number(x || 0).toFixed(Math.abs(Number(x)) < 1 && Number(x) !== 0 ? 2 : 0)}`;
const num = (x, d = 0) => { const v = Number(x); return Number.isFinite(v) ? v : d; };
const compOf = (per, key) => num(per[key] ?? per[key.replace('-', '_')], 0);
const hasBoth = (it) => it && Number.isFinite(Number(it.winback_hours_year)) && Number.isFinite(Number(it.winback_usd_year))
  && Number.isFinite(Number(it.adopt_cost_min)) && Number.isFinite(Number(it.adopt_cost_usd));

function trajChart(d) {
  const W = 320, H = 180, PL = 36, PR = 8, PT = 10, PB = 22;
  const n = Math.min(d.weeks.length, d.current_hours.length, d.adopted_hours.length);
  let maxY = 1;
  for (let i = 0; i < n; i++) maxY = Math.max(maxY, num(d.current_hours[i]), num(d.adopted_hours[i]));
  const X = (i) => PL + ((W - PL - PR) * (n <= 1 ? 0 : i / (n - 1)));
  const Y = (v) => PT + ((H - PT - PB) * (1 - Math.max(0, v) / maxY));
  const el = s('svg', { class: 'lk-traj', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': `Cumulative leaked hours over ${n} weeks` });
  [maxY, maxY / 2, 0].forEach((g) => {
    el.append(s('line', { x1: PL, x2: W - PR, y1: Y(g), y2: Y(g), class: 'lk-grid' }),
      s('text', { x: 2, y: Y(g) + 3, class: 'lk-axis' }, `${Math.round(g)}h`));
  });
  const series = (vals, cls) => el.append(s('polyline', {
    class: cls, points: vals.slice(0, n).map((v, i) => `${X(i).toFixed(1)},${Y(num(v)).toFixed(1)}`).join(' '),
  }));
  series(d.current_hours, 'lk-cur'); series(d.adopted_hours, 'lk-adp');
  el.append(s('text', { x: PL, y: H - 6, class: 'lk-axis' }, 'week 1'),
    s('text', { x: W - PR - 44, y: H - 6, class: 'lk-axis' }, `week ${d.weeks[n - 1]}`));
  return el;
}

export default {
  id: 'leaks', key: 'l', dated: true, title: 'Leaks', icon: 'alert',
  load: async (ctx) => {
    try {
      const ins = await api.get('/api/insights?date=' + ctx.date);
      if (ins && (ins.leak_score != null || ins.per_day_min)) return { seed: ins };
    } catch { /* the runtime stream below is the other source */ }
    return { seed: null };
  },
  view(d) {
    const head = h('div', { class: 'page-head' }, h('div', { class: 'grow' }, h('h1', {}, 'Leaks'), h('p', {}, 'Where the day goes missing. Lower is better.')), pill('Lower is better', 'good'));
    const scoreSec = h('section', { class: 'card hero raised' }, h('header', {}, h('h3', {}, 'Leak score')), h('div', { class: 'lk-score-body' }));
    const changesSec = h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'Small changes, ranked')), h('div', { class: 'lk-changes-body' }));
    const progSec = h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'Progress')), h('div', { class: 'lk-prog-body' }));
    const trajSec = h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'Trajectory')), h('div', { class: 'lk-traj-body' }));

    const renderLeaks = (lk) => {
      const body = scoreSec.querySelector('.lk-score-body'); clear(body);
      if (!lk || lk.leak_score == null) { body.append(emptyState('No leak data yet', 'Leak scores arrive from the runtime stream once the day has measured blocks.')); return; }
      const per = lk.per_day_min || {};
      body.append(
        h('div', { class: 'lk-score num', 'aria-label': `Leak score ${Math.round(num(lk.leak_score))}` }, String(Math.round(num(lk.leak_score)))),
        h('p', { class: 'faint' }, 'lower is better'),
        h('div', { class: 'lk-comp' }, h('h4', {}, 'Leak minutes per day'),
          hbars(COMPS.map(([k, label]) => [label, compOf(per, k) * 60]))),
        h('div', { class: 'lk-tiles' }, PERIODS.map((p) => {
          const c = (lk.compounded || {})[p] || {};
          return h('div', { class: 'stat flat lk-tile' }, h('span', { class: 'k' }, p),
            h('span', { class: 'v num' }, `${num(c.hours).toFixed(1)} h`), h('span', { class: 's num' }, usd(c.usd)));
        })));
    };
    const renderSuggestions = (sg) => {
      const body = changesSec.querySelector('.lk-changes-body'); clear(body);
      const items = (sg && Array.isArray(sg.items) ? sg.items : []).filter(hasBoth);
      if (!items.length) { body.append(emptyState('Nothing ranked yet', 'Ranked changes arrive from the runtime stream, each with time won back and its cost to adopt.')); return; }
      body.append(h('ol', { class: 'lk-ranked' }, items.map((it, i) => h('li', {},
        h('span', { class: 'lk-rank num', 'aria-hidden': 'true' }, String(i + 1)),
        h('div', {}, h('p', {}, String(it.text || '')),
          h('div', { class: 'win num' }, `+${num(it.winback_hours_year).toFixed(1)} h/yr (≈ ${usd(it.winback_usd_year)}) won back`),
          h('div', { class: 'cost num' }, `cost: ${num(it.adopt_cost_min).toFixed(0)} min (+${usd(it.adopt_cost_usd)})`))))));
    };
    const renderProgress = (pr) => {
      const body = progSec.querySelector('.lk-prog-body'); clear(body);
      if (!pr || typeof pr.level_name !== 'string') { body.append(emptyState('No progress yet', 'Levels and XP arrive from the runtime stream as leaks shrink.')); return; }
      const into = num(pr.xp_into_level), next = Math.max(1, num(pr.xp_for_next, 1));
      const frac = Math.min(1, Math.max(0, into / next));
      const xpText = `${into} of ${next} XP`;
      const wonText = `${num(pr.won_back_min).toFixed(1)} min won back`;
      const side = h('div', {}, h('b', {}, `Level ${num(pr.level)} — ${pr.level_name}`), h('p', { class: 'faint num' }, `${xpText} · ${wonText}`));
      body.append(h('div', { class: 'row lk-level' }, ring(frac, { label: `Level ${num(pr.level)} progress` }), side));
    };
    const renderTrajectory = (tr) => {
      const body = trajSec.querySelector('.lk-traj-body'); clear(body);
      if (!tr || !Array.isArray(tr.weeks) || !tr.weeks.length || !Array.isArray(tr.current_hours) || !Array.isArray(tr.adopted_hours)) {
        body.append(emptyState('No forecast yet', 'The trajectory forecast arrives from the runtime stream.')); return;
      }
      body.append(trajChart(tr),
        h('div', { class: 'legend' }, h('span', {}, h('i', { class: 'swatch lk-sw-cur' }), 'current'), h('span', {}, h('i', { class: 'swatch lk-sw-adp' }), 'adopted')),
        h('p', { class: 'faint num' }, `${num(tr.won_back_hours).toFixed(1)} h won back (≈ ${usd(tr.won_back_usd)})`));
    };

    renderLeaks(d.seed); renderSuggestions(null); renderProgress(null); renderTrajectory(null);

    let es = null;
    try {
      es = new EventSource('/v1/events');
      es.addEventListener('leaks.computed', (e) => { try { renderLeaks(JSON.parse(e.data)); } catch { /* keep latest good frame */ } });
      es.addEventListener('suggestions.ranked', (e) => { try { renderSuggestions(JSON.parse(e.data)); } catch { /* keep latest good frame */ } });
      es.addEventListener('progress.updated', (e) => { try { renderProgress(JSON.parse(e.data)); } catch { /* keep latest good frame */ } });
      es.addEventListener('trajectory.forecast', (e) => { try { renderTrajectory(JSON.parse(e.data)); } catch { /* keep latest good frame */ } });
    } catch { /* stream unavailable; the /api/insights seed above still renders */ }

    const root = h('div', { class: 'page page-leaks quiet' }, head,
      h('div', { class: 'grid g-main' }, h('div', { class: 'col' }, scoreSec, changesSec), h('div', { class: 'col' }, progSec, trajSec)));
    const gone = new MutationObserver(() => {
      if (document.body.contains(root)) return;
      gone.disconnect(); if (es) es.close();
    });
    gone.observe(document.body, { childList: true, subtree: true });
    return root;
  },
};
