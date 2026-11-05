// Focus: an immersive session screen. Starting a session puts the whole app into Focus mode (the key modulates, the
// surfaces deepen); a break modulates to the subdominant. Timer state lives on the server (/api/timer), so it survives reloads.
import { h, s } from '../lib/dom.js';
import { api } from '../lib/api.js';
import { dur, clock } from '../lib/fmt.js';
import { toast } from '../ui/toast.js';
import { icon } from '../ui/icons.js';
import { roll, deltaChip } from '../ui/kit.js';
import { NOTES, catColor } from '../lib/harmony.js';
import { mode } from '../lib/mode.js';
import { focusField } from '../charts/wave.js';

const LENGTHS = [25, 50, 90];
const pad = (n) => String(Math.floor(n)).padStart(2, '0');
const mmss = (sec) => (sec >= 3600 ? `${Math.floor(sec / 3600)}:${pad((sec % 3600) / 60)}:${pad(sec % 60)}` : `${pad(sec / 60)}:${pad(sec % 60)}`);

function ring() {
  // 60 ticks; the 12 at each fifth minute are the chromatic notes, each a hair of its own colour
  const R = 150, C = 170, ticks = [];
  for (let i = 0; i < 60; i++) {
    const a = (i / 60) * 2 * Math.PI - Math.PI / 2, major = i % 5 === 0, r1 = major ? R - 16 : R - 9;
    ticks.push(s('line', { class: `tk${major ? ' mj' : ''}`, 'data-i': i, x1: C + Math.cos(a) * r1, y1: C + Math.sin(a) * r1, x2: C + Math.cos(a) * R, y2: C + Math.sin(a) * R,
      style: major ? { '--note': NOTES[(i / 5 + 9) % 12].dark } : {} }));
  }
  return s('svg', { class: 'fring', viewBox: '0 0 340 340', 'aria-hidden': 'true' }, ticks);
}

export default {
  id: 'focus', key: 'f', dated: false, title: 'Focus', icon: 'timer',
  load: async (ctx) => {
    const [timer, tasks, day] = await Promise.all([api.get('/api/timer'), api.get('/api/tasks'), api.get('/api/day?date=' + ctx.date).catch(() => null)]);
    return { timer, tasks, day };
  },
  view(d, ctx) {
    let len = Number(localStorage.getItem('stretto.len') || 25), taskId = d.timer?.task_id ?? null;
    const open = d.tasks.filter((t) => t.status !== 'done');
    const svg = ring(), time = h('div', { class: 'ftime num', role: 'timer', 'aria-live': 'off' }), sub = h('div', { class: 'fsub' });
    const field = h('div', { class: 'ffield' }, focusField());
    const pick = h('select', { class: 'input fpick', 'aria-label': 'Task for this session' }, h('option', { value: '' }, open.length ? 'No task: free focus' : 'No open tasks yet'),
      open.map((t) => h('option', { value: t.id, selected: t.id === taskId ? true : null }, t.title)));
    pick.addEventListener('change', () => { taskId = pick.value ? Number(pick.value) : null; });
    const seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Session length' }, LENGTHS.map((m) => h('button', { 'aria-pressed': String(m === len), onclick: (e) => { len = m; localStorage.setItem('stretto.len', m); seg.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b === e.currentTarget))); paint(); } }, `${m} min`)));
    const startBtn = h('button', { class: 'btn primary fbtn', onclick: () => start('focus') }, icon('play', 16), 'Start focus');
    const breakBtn = h('button', { class: 'btn fbtn', onclick: () => start('break') }, 'Break');
    const stopBtn = h('button', { class: 'btn fbtn', onclick: stop }, icon('stop', 16), 'Stop');
    const controls = h('div', { class: 'fctl' });
    async function start(kind) {
      const t = open.find((x) => x.id === taskId);
      try { await api.post('/api/timer/start', { kind, task_id: taskId, label: kind === 'break' ? 'Break' : t ? t.title : 'Focus' }); toast(kind === 'break' ? 'Break started' : 'Focus started'); await mode.refresh(); paint(); }
      catch (e) { toast(e.message, 'bad'); }
    }
    async function stop() { try { await api.post('/api/timer/stop'); toast(`Session saved · ${dur(elapsed())}`); await mode.refresh(); paint(); } catch (e) { toast(e.message, 'bad'); } }
    const elapsed = () => (mode.timer ? Math.max(0, Date.now() / 1000 - mode.timer.start) : 0);
    function paint() {
      const t = mode.timer, run = !!t, el = elapsed(), total = len * 60, left = Math.max(0, total - el), over = run && el > total;
      roll(time, run ? (over ? `+${mmss(el - total)}` : mmss(left)) : mmss(total));
      sub.textContent = run ? `${t.kind === 'break' ? 'Break' : 'Focusing'}${t.label && t.kind !== 'break' ? ' · ' + t.label : ''} · started ${clock(t.start)}` : 'Ready when you are';
      const lit = run ? Math.round(Math.min(1, el / total) * 60) : 0;
      svg.querySelectorAll('.tk').forEach((l) => l.classList.toggle('on', Number(l.dataset.i) < lit));
      controls.replaceChildren(...(run ? [stopBtn, t.kind === 'break' ? h('button', { class: 'btn primary fbtn', onclick: () => start('focus') }, 'Back to focus') : breakBtn] : [startBtn, breakBtn]));
      pick.disabled = run; seg.querySelectorAll('button').forEach((b) => (b.disabled = run));
    }
    paint();
    const tickId = setInterval(() => { if (!document.body.contains(time)) { clearInterval(tickId); return; } paint(); }, 1000);
    const off = mode.on(paint); const gone = new MutationObserver(() => { if (!document.body.contains(time)) { off(); gone.disconnect(); } }); gone.observe(document.body, { childList: true, subtree: true });

    // right rail: today's focus, tasks, records
    const sm = d.day?.summary, blocks = d.day?.blocks || [];
    const records = h('ol', { class: 'frec' }, blocks.filter((b) => b.category !== 'Idle').slice(-14).reverse().map((b) =>
      h('li', { style: { '--c': catColor(b.category) } }, h('span', { class: 'num' }, clock(b.start)), h('b', { class: 'trunc' }, b.domain || b.app), h('small', { class: 'num' }, dur(b.end - b.start)))));
    const rail = h('aside', { class: 'frail' },
      h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'Focus today')), h('div', { class: 'big num' }, sm ? dur(sm.focus_s) : '—'), sm ? deltaChip(sm.delta?.focus_s, sm.delta_pct?.focus_s, 1) : null, h('small', { class: 'faint' }, sm ? `${d.day.blocks.length} blocks measured` : 'No data for today yet')),
      h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'Tasks'), h('a', { href: '#/tasks', class: 'faint' }, 'All tasks')),
        open.length ? h('ul', { class: 'ftasks' }, open.slice(0, 5).map((t) => h('li', {}, h('span', { class: 'trunc' }, t.title), h('small', { class: 'faint num' }, t.tracked_s ? dur(t.tracked_s) : ''),
          h('button', { class: 'icon-btn', 'aria-label': `Focus on ${t.title}`, onclick: () => { taskId = t.id; pick.value = String(t.id); start('focus'); } }, icon('play', 16)))))
          : h('p', { class: 'muted' }, 'Add tasks to focus on them. ', h('a', { href: '#/tasks' }, 'Open Tasks'))),
      h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'Today’s records')), blocks.length ? records : h('p', { class: 'muted' }, 'Records appear as the collector reports.')));
    return h('div', { class: 'page focus-page quiet' },
      h('div', { class: 'fstage' }, field, h('div', { class: 'fdial' }, svg, h('div', { class: 'fcenter' }, time, sub)),
        h('div', { class: 'fopts' }, pick, seg), controls), rail);
  },
};
