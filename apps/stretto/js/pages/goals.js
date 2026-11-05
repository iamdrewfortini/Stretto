// Goals: the daily focus goal as a slider with today's ring (UI-SLIDER-023 + UI-GAUGE-008), the week as a progress row with a
// 7-day strip (UI-PROG-007 + UI-CAL-019), per-category budgets as progress rows, and level, XP and streak (UI-PROG-007, UI-PILL-030).
import { h, s } from '../lib/dom.js';
import { api } from '../lib/api.js';
import { dur, pct, iso, CAT, catVar } from '../lib/fmt.js';
import { toast } from '../ui/toast.js';
import { pill, deltaChip } from '../ui/kit.js';
import { noteOf } from '../lib/harmony.js';

const ring = (f, size = 120) => { const r = (size - 12) / 2, C = 2 * Math.PI * r;
  return s('svg', { class: 'goal-ring', viewBox: `0 0 ${size} ${size}`, width: size, height: size, 'aria-hidden': 'true' },
    s('circle', { cx: size / 2, cy: size / 2, r, class: 'goal-ring-bg' }), f > 0 ? s('circle', { cx: size / 2, cy: size / 2, r, class: `goal-ring-fg${f >= 1 ? ' met' : ''}`, 'stroke-dasharray': `${C * Math.min(1, f)} ${C}`, transform: `rotate(-90 ${size / 2} ${size / 2})` }) : null); };
const row = (label, done, target, note) => { const f = target ? done / target : 0;
  return h('div', { class: 'gl-row' }, h('div', { class: 'row' }, h('span', { class: 'grow' }, label), h('span', { class: 'num' }, target ? `${dur(done)} / ${dur(target)}` : dur(done))),
    h('div', { class: 'bar' }, h('i', { style: { '--f': String(Math.min(1, f)), background: f >= 1 ? 'var(--good)' : 'var(--tonic)' } }), f > 1 ? h('em', { class: 'over', style: { '--o': String(Math.min(.1, f - 1) / Math.max(f, 1)) } }) : null), note ? h('small', { class: 'faint' }, note) : null); };

export default {
  id: 'goals', key: 'o', dated: false, title: 'Goals', icon: 'spark',
  load: async () => {
    const tod = iso(new Date());
    const [settings, week, day] = await Promise.all([api.get('/api/settings'), api.get('/api/range?days=7'), api.get(`/api/day?date=${tod}`)]);
    return { settings, week, day, tod };
  },
  view(d) {
    const sm = d.day.summary || {}, goal = (d.settings.goal_min || 240) * 60, weekGoal = (d.settings.goal_week_min ? d.settings.goal_week_min * 60 : goal * 5), budgets = d.settings.budgets || null;
    const weekFocus = d.week.days.reduce((a, x) => a + x.focus_s, 0), weekPrev = d.week.prev_total_focus_s;
    // daily goal: slider saves as you move (R16 optimistic), ring shows today
    const out = h('b', { class: 'num gl-val' }, dur(goal));
    const range = h('input', { type: 'range', min: 30, max: 600, step: 15, value: d.settings.goal_min || 240, class: 'st-range', 'aria-label': 'Daily focus goal in minutes' });
    let t = 0; range.addEventListener('input', () => { out.textContent = dur(range.value * 60); clearTimeout(t); t = setTimeout(async () => { try { await api.post('/api/settings', { goal_min: Number(range.value) }); toast(`Daily goal: ${dur(range.value * 60)}`, 'good'); } catch (e) { toast(e.message, 'bad'); } }, 500); });
    const todayF = goal ? (sm.focus_s || 0) / goal : 0;
    const daily = h('section', { class: 'card hero raised', 'aria-labelledby': 'gl-h' }, h('header', {}, h('h3', { id: 'gl-h' }, 'Daily focus goal'), h('small', {}, 'saved as you move it')),
      h('div', { class: 'gl-daily' }, h('div', { class: 'gl-ringwrap' }, ring(todayF, 132), h('div', { class: 'gl-ringtxt' }, h('b', { class: 'num' }, `${Math.round(todayF * 100)}%`), h('small', {}, 'today'))),
        h('div', { class: 'stack grow' }, h('div', { class: 'row wrap' }, out, sm.focus_s ? deltaChip(sm.delta?.focus_s, sm.delta_pct?.focus_s, 1) : null, h('small', { class: 'faint' }, `${dur(sm.focus_s || 0)} so far · ${todayF >= 1 ? 'goal met' : dur(Math.max(0, goal - (sm.focus_s || 0))) + ' to go'}`)), range,
          h('div', { class: 'row gl-marks faint num' }, h('span', {}, '30m'), h('span', {}, 'saved'), h('span', {}, '10h')))));
    // week: progress row + 7 small rings
    const week = h('section', { class: 'card', 'aria-labelledby': 'wk-h' }, h('header', {}, h('h3', { id: 'wk-h' }, 'This week'), weekPrev ? deltaChip(weekFocus - weekPrev, (weekFocus - weekPrev) / weekPrev, 1) : null, d.settings.goal_week_min ? null : pill('5 × daily until a weekly goal is set', '')),
      row('Focus', weekFocus, weekGoal, `${d.week.days.filter((x) => x.focus_s >= goal).length} of ${d.week.days.length} days met the daily goal`),
      h('div', { class: 'cal-week' }, d.week.days.map((x) => h('div', { class: `cal-wd${x.focus_s >= goal ? ' met' : ''}${x.date === d.tod ? ' today' : ''}`, title: `${x.date}: ${dur(x.focus_s)}` }, ring(goal ? x.focus_s / goal : 0, 40), h('small', { class: 'num' }, new Date(x.date + 'T12:00:00').toLocaleDateString([], { weekday: 'narrow' }))))));
    // budgets per category: this week's measured minutes against a budget when one exists
    const byCat = {}; d.week.days.forEach((x) => { Object.entries(x.by_category || {}).forEach(([k, v]) => { byCat[k] = (byCat[k] || 0) + v; }); });
    const haveWeekCats = Object.keys(byCat).length > 0; if (!haveWeekCats) Object.entries(sm.by_category || {}).forEach(([k, v]) => { byCat[k] = v; });
    const cats = CAT.filter((c) => c !== 'Idle' && (byCat[c] || (budgets && budgets[c])));
    const budget = h('section', { class: 'card', 'aria-labelledby': 'bg-h' }, h('header', {}, h('h3', { id: 'bg-h' }, 'Budgets by category'), h('small', {}, haveWeekCats ? 'this week' : 'today'), budgets ? null : pill('Budgets arrive with the next server update', '')),
      cats.length ? h('div', { class: 'stack' }, cats.map((c) => h('div', { class: 'gl-cat', style: { '--c': catVar(c) } }, h('i', { class: `swatch tx tx-${c.toLowerCase()}` }), row(`${c} · ${noteOf(c)}`, byCat[c] || 0, budgets && budgets[c] ? budgets[c] * 60 : 0, budgets && budgets[c] ? null : 'no budget set'))))
        : h('p', { class: 'muted' }, 'Categories fill in as days are measured.'));
    // level, XP, streak, badges
    const xp = d.day.xp || { level: 1, xp: 0, floor: 0, next: 100 }, span = Math.max(1, xp.next - xp.floor);
    const level = h('section', { class: 'card', 'aria-labelledby': 'lv-h' }, h('header', {}, h('h3', { id: 'lv-h' }, 'Level and streak'), pill(d.day.streak ? `${d.day.streak}-day streak` : 'no streak yet', d.day.streak ? 'good' : '')),
      h('div', { class: 'row wrap' }, h('b', { class: 'big num' }, `Level ${xp.level}`), h('small', { class: 'faint num' }, `${xp.xp} / ${xp.next} XP`)),
      h('div', { class: 'bar' }, h('i', { style: { '--f': String(Math.min(1, (xp.xp - xp.floor) / span)) } })),
      (d.day.badges || []).length ? h('div', { class: 'row wrap gl-badges' }, d.day.badges.map((b) => pill(b, 'info'))) : h('p', { class: 'faint' }, 'Badges come from met goals and streaks; none yet.'));
    return h('div', { class: 'page' }, h('div', { class: 'page-head' }, h('div', { class: 'grow' }, h('h1', {}, 'Goals'), h('p', {}, 'What you are aiming for, and how this week is going against it.'))),
      daily, h('div', { class: 'grid g-main' }, h('div', { class: 'stack' }, week, budget), level));
  },
};
