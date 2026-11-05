// Habits: small daily practices with an 8-week grid. Tapping a day toggles it on the server (/api/habits/:id/log).
import { h } from '../lib/dom.js';
import { api } from '../lib/api.js';
import { iso } from '../lib/fmt.js';
import { toast } from '../ui/toast.js';
import { emptyState } from '../ui/kit.js';

const dayIso = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return iso(d); };
function streak(days) { const set = new Set(days); let n = 0, i = set.has(dayIso(0)) ? 0 : 1; while (set.has(dayIso(i))) { n++; i++; } return n; }

export default {
  id: 'habits', key: 'h', dated: false, title: 'Habits', icon: 'habit',
  load: () => api.get('/api/habits'),
  view(list) {
    const body = h('div', { class: 'stack' });
    const toggle = async (hb, day, cell) => {
      const set = new Set(hb.days), had = set.has(day); had ? set.delete(day) : set.add(day); hb.days = [...set]; draw();
      try { await api.post(`/api/habits/${hb.id}/log`, { day }); if (!had && day === dayIso(0)) toast(`${hb.name}: done today`, 'good'); } catch (e) { had ? set.add(day) : set.delete(day); hb.days = [...set]; draw(); toast(e.message, 'bad'); }
    };
    function row(hb) {
      const set = new Set(hb.days), n = streak(hb.days), today = dayIso(0);
      const grid = h('div', { class: 'hb-grid', role: 'group', 'aria-label': `${hb.name}, last 8 weeks` }, Array.from({ length: 56 }, (_, k) => { const day = dayIso(55 - k), on = set.has(day);
        return h('button', { class: `hb-d${on ? ' on' : ''}${day === today ? ' today' : ''}`, title: `${day}${on ? ' · done' : ''}`, 'aria-label': `${day} ${on ? 'done' : 'not done'}`, 'aria-pressed': String(on), onclick: () => toggle(hb, day) }); }));
      return h('section', { class: 'card hb' }, h('header', {}, h('h3', {}, hb.name), h('small', { class: 'num' }, n ? `${n}-day streak` : 'no streak yet')),
        hb.why ? h('p', { class: 'muted' }, hb.why) : null, grid,
        h('button', { class: `btn ${set.has(today) ? '' : 'primary'}`, onclick: () => toggle(hb, today) }, set.has(today) ? 'Done today · undo' : 'Mark done today'));
    }
    function draw() { body.replaceChildren(...(list.length ? list.map(row) : [emptyState('No habits yet', 'Add one small daily practice above, like a morning plan or a walk at lunch.')])); }
    draw();
    const name = h('input', { class: 'input grow', placeholder: 'New habit, then Enter', 'aria-label': 'New habit', enterkeyhint: 'done' });
    const why = h('input', { class: 'input grow', placeholder: 'Why it matters (optional)', 'aria-label': 'Why it matters' });
    const add = async () => { if (!name.value.trim()) return; try { const r = await api.post('/api/habits', { name: name.value.trim(), why: why.value.trim() }); list.push({ id: r.id, name: name.value.trim(), why: why.value.trim(), days: [] }); name.value = ''; why.value = ''; draw(); } catch (e) { toast(e.message, 'bad'); } };
    name.addEventListener('keydown', (e) => { if (e.key === 'Enter') add(); });
    return h('div', { class: 'page' }, h('div', { class: 'page-head' }, h('div', { class: 'grow' }, h('h1', {}, 'Habits'), h('p', {}, 'Small things done most days. Tap any day to mark it.'))),
      h('div', { class: 'card row wrap tk-add' }, name, why, h('button', { class: 'btn', onclick: add }, 'Add')), body);
  },
};
