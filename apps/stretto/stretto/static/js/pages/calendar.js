// Calendar: a month of goal rings (UI-CAL-019), the selected day's schedule as a time gutter with blocks (UI-TIME-020:
// measured blocks textured by category, timer sessions outlined, planned tasks dashed), and the upcoming tasks (UI-TASK-017).
import { h, s } from '../lib/dom.js';
import { api } from '../lib/api.js';
import { dur, clock, iso, shiftDay, catVar } from '../lib/fmt.js';
import { query, patch, go } from '../lib/router.js';
import { toast } from '../ui/toast.js';
import { emptyState, pill } from '../ui/kit.js';
import { icon } from '../ui/icons.js';

const dayIso = (d) => iso(d);
const today = () => dayIso(new Date());
const monthOf = (isoDay) => isoDay.slice(0, 7);
const monthName = (ym) => new Date(ym + '-15T12:00:00').toLocaleDateString([], { month: 'long', year: 'numeric' });
const shiftMonth = (ym, n) => { const d = new Date(ym + '-15T12:00:00'); d.setMonth(d.getMonth() + n); return monthOf(dayIso(d)); };
const localDay = (ts) => dayIso(new Date(ts * 1000));
const PX_MIN = 0.8;   // UI-TIME-020: 48 px per hour

function monthGrid(ym, byDay, goal, sel) {
  const first = new Date(ym + '-01T12:00:00'), lead = (first.getDay() + 6) % 7, n = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
  const C = 2 * Math.PI * 15, tod = today();
  return h('div', { class: 'cal-month', role: 'grid', 'aria-label': monthName(ym) }, ['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((x) => h('b', {}, x)), Array.from({ length: lead }, () => h('span')),
    Array.from({ length: n }, (_, i) => { const d = `${ym}-${String(i + 1).padStart(2, '0')}`, r = byDay.get(d), f = r ? Math.min(1, r.focus_s / goal) : 0, met = f >= 1, fut = d > tod;
      return h('button', { class: `cal-d${met ? ' met' : ''}${d === sel ? ' sel' : ''}${d === tod ? ' today' : ''}${fut ? ' fut' : ''}`, 'aria-pressed': String(d === sel), disabled: fut ? true : null,
        title: r ? `${d}: ${dur(r.focus_s)} of ${dur(goal)}${met ? ' · goal met' : ''}` : d, onclick: () => patch({ d: d === tod ? '' : d }) },
        s('svg', { viewBox: '0 0 36 36', 'aria-hidden': 'true' }, s('circle', { cx: 18, cy: 18, r: 15, class: 'cal-ring-bg' }), f > 0 ? s('circle', { cx: 18, cy: 18, r: 15, class: 'cal-ring', 'stroke-dasharray': `${C * f} ${C}`, transform: 'rotate(-90 18 18)' }) : null),
        h('i', { class: 'num' }, String(i + 1))); }));
}

function timeline(day, blocks, sessions, planned, isToday) {
  const starts = [...blocks.map((b) => b.start), ...sessions.map((x) => x.start), ...planned.map((t) => t.planned_start)];
  const ends = [...blocks.map((b) => b.end), ...sessions.map((x) => x.end || Date.now() / 1000), ...planned.map((t) => t.planned_start + (t.est_min || 25) * 60)];
  const base = new Date(day + 'T00:00:00').getTime() / 1000;
  const h0 = Math.min(8, ...starts.map((t) => Math.floor((t - base) / 3600))), h1 = Math.max(18, ...ends.map((t) => Math.ceil((t - base) / 3600)));
  const t0 = base + Math.max(0, h0) * 3600, hours = Math.min(24, Math.max(1, h1 - Math.max(0, h0)));
  const y = (t) => Math.round(((t - t0) / 60) * PX_MIN), hgt = (a, b) => Math.max(16, Math.round(((b - a) / 60) * PX_MIN));
  const lane = h('div', { class: 'cal-lane', style: { height: `${hours * 60 * PX_MIN}px` } });
  for (let i = 0; i <= hours; i++) lane.append(h('div', { class: 'cal-hour', style: { top: `${i * 60 * PX_MIN}px` } }, h('span', { class: 'num' }, clock(t0 + i * 3600))));
  // measured blocks come from the resolved timeline, so they never overlap in time: draw them at true height (min 3 px), labels only where they fit (UI-TIME-020)
  blocks.forEach((b) => { const hh = Math.max(3, Math.round(((b.end - b.start) / 60) * PX_MIN));
    lane.append(h('div', { class: `cal-blk tx tx-${String(b.category || '').toLowerCase()}`, 'data-sm': hh < 18 ? '' : null, style: { top: `${y(b.start) + 1}px`, height: `${Math.max(2, hh - 2)}px`, '--c': catVar(b.category) }, title: `${clock(b.start)}–${clock(b.end)} ${b.domain || b.app || ''} · ${b.category} · ${dur(b.end - b.start)}` },
      h('b', { class: 'trunc' }, b.domain || b.app || b.category), h('small', { class: 'num' }, dur(b.end - b.start)))); });
  sessions.forEach((x) => lane.append(h('div', { class: `cal-ses${x.kind === 'break' ? ' brk' : ''}${x.end ? '' : ' live'}`, style: { top: `${y(x.start)}px`, height: `${hgt(x.start, x.end || Date.now() / 1000)}px` }, title: `${x.kind} session ${clock(x.start)}${x.end ? '–' + clock(x.end) : ' · running'}` },
    h('b', { class: 'trunc' }, x.task_title || x.label || (x.kind === 'break' ? 'Break' : 'Focus')), h('small', { class: 'num' }, x.end ? dur(x.end - x.start) : 'running'))));
  planned.forEach((t) => lane.append(h('a', { class: 'cal-plan', href: '#/tasks', style: { top: `${y(t.planned_start)}px`, height: `${hgt(t.planned_start, t.planned_start + (t.est_min || 25) * 60)}px` }, title: `planned: ${t.title}` },
    h('b', { class: 'trunc' }, t.title), h('small', { class: 'num' }, `${t.est_min || 25} min planned`))));
  if (isToday) { const now = Date.now() / 1000; if (now > t0 && now < t0 + hours * 3600) lane.append(h('div', { class: 'cal-now', style: { top: `${y(now)}px` } })); }
  return h('div', { class: 'cal-day' }, lane);
}

export default {
  id: 'calendar', key: 'c', dated: true, title: 'Calendar', icon: 'calendar',
  load: async (ctx) => {
    const ym = monthOf(ctx.date), tod = today();
    const span = Math.min(62, Math.max(7, Math.round((new Date(tod + 'T12:00:00') - new Date(ym + '-01T12:00:00')) / 86400000) + 2));
    const [range, day, tasks, ses] = await Promise.all([api.get(`/api/range?days=${span}`), api.get(`/api/day?date=${ctx.date}`), api.get('/api/tasks').catch(() => []),
      api.get(`/api/sessions?from=${ctx.date}&to=${ctx.date}`).catch(() => null)]);
    return { ym, range, day, tasks: Array.isArray(tasks) ? tasks : tasks.tasks || [], sessions: ses ? ses.sessions || [] : null };
  },
  view(d, ctx) {
    const goal = d.range.goal_s || 14400, byDay = new Map(d.range.days.map((x) => [x.date, x]));
    const inMonth = d.range.days.filter((x) => monthOf(x.date) === d.ym && x.total_s > 0), met = inMonth.filter((x) => x.focus_s >= goal).length;
    const head = h('div', { class: 'page-head' }, h('div', { class: 'grow' }, h('h1', {}, 'Calendar'), h('p', {}, `${monthName(d.ym)} · ${inMonth.length} measured day${inMonth.length === 1 ? '' : 's'} · goal met on ${met}`)),
      h('div', { class: 'seg', role: 'group', 'aria-label': 'Month' }, h('button', { 'aria-label': 'Previous month', onclick: () => patch({ d: shiftMonth(d.ym, -1) + '-01' }) }, icon('left', 16)),
        h('button', { 'aria-pressed': 'true', onclick: () => patch({ d: '' }) }, 'This month'), h('button', { 'aria-label': 'Next month', disabled: d.ym >= monthOf(today()) ? true : null, onclick: () => patch({ d: shiftMonth(d.ym, 1) + '-01' }) }, icon('right', 16))));
    const month = h('section', { class: 'card', 'aria-labelledby': 'cal-h' }, h('header', {}, h('h3', { id: 'cal-h' }, monthName(d.ym)), h('small', {}, `ring = focus of ${dur(goal)} goal`)), monthGrid(d.ym, byDay, goal, ctx.date));
    const blocks = d.day.blocks || [], planned = d.tasks.filter((t) => t.planned_start && localDay(t.planned_start) === ctx.date && t.status !== 'done');
    const sessions = d.sessions || [];
    const dayCard = h('section', { class: 'card', 'aria-labelledby': 'day-h' }, h('header', {}, h('h3', { id: 'day-h' }, ctx.isToday ? 'Today' : new Date(ctx.date + 'T12:00:00').toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })),
        h('small', {}, blocks.length ? `${blocks.length} blocks · ${dur(d.day.summary?.focus_s || 0)} focus` : 'nothing measured'), d.sessions === null ? pill('Sessions: soon', '') : null),
      blocks.length || sessions.length || planned.length ? timeline(ctx.date, blocks, sessions, planned, ctx.isToday) : emptyState(ctx.date > today() ? 'A day that hasn’t happened yet' : 'Nothing on this day', 'Measured blocks, timer sessions and planned tasks appear here.'),
      h('p', { class: 'faint cal-key' }, h('span', { class: 'cal-k blk' }, 'measured'), h('span', { class: 'cal-k ses' }, 'session'), h('span', { class: 'cal-k pln' }, 'planned')));
    // Upcoming: tasks due or planned in the next 7 days, grouped by day; "Plan here" writes planned_start on the selected day at 09:00
    const until = shiftDay(today(), 7), up = d.tasks.filter((t) => t.status !== 'done' && ((t.due && t.due >= today() && t.due <= until) || (t.planned_start && localDay(t.planned_start) >= today() && localDay(t.planned_start) <= until)));
    const groups = new Map(); up.forEach((t) => { const k = t.planned_start ? localDay(t.planned_start) : t.due; groups.set(k, [...(groups.get(k) || []), t]); });
    const plan = async (t, btn) => { btn.disabled = true; try { const at = new Date(ctx.date + 'T09:00:00').getTime() / 1000; await api.post(`/api/tasks/${t.id}`, { planned_start: at }); toast(`Planned: ${t.title}`, 'good'); go('calendar', { d: ctx.isToday ? '' : ctx.date }, { replace: true }); }
      catch (e) { btn.disabled = false; toast(e.message.includes('planned') || e.message.includes('400') ? 'Planning needs the next server update' : e.message, 'bad'); } };
    const upcoming = h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'Upcoming'), h('small', {}, 'due or planned in the next 7 days')),
      up.length ? h('div', { class: 'stack' }, [...groups.keys()].sort().map((k) => h('div', { class: 'cal-grp' }, h('p', { class: 'faint cal-grp-h' }, k === today() ? 'Today' : new Date(k + 'T12:00:00').toLocaleDateString([], { weekday: 'long', day: 'numeric' })),
        groups.get(k).map((t) => h('div', { class: 'tk-row cal-up' }, h('span', { class: `tk-dot ${t.status}` }), h('span', { class: 'trunc grow' }, t.title), t.est_min ? h('small', { class: 'faint num' }, `${t.est_min} min`) : null,
          t.planned_start ? pill(clock(t.planned_start), 'info') : h('button', { class: 'btn sm', onclick: (e) => plan(t, e.currentTarget) }, 'Plan here'))))))
        : emptyState('Nothing due this week', 'Give tasks a due date or plan them onto a day and they show up here.', h('a', { class: 'btn', href: '#/tasks' }, 'Open tasks')));
    return h('div', { class: 'page' }, head, h('div', { class: 'grid g-main cal-grid' }, dayCard, h('div', { class: 'stack' }, month, upcoming)));
  },
};
