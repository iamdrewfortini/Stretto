// Tasks: list (grouped by project) and board (To do / Next / Doing / Done). Server-backed (/api/tasks, /api/projects).
// Status changes apply at once and roll back if the server refuses. A task's play button starts a focus session on it.
import { h } from '../lib/dom.js';
import { api } from '../lib/api.js';
import { dur } from '../lib/fmt.js';
import { query, patch, go } from '../lib/router.js';
import { toast } from '../ui/toast.js';
import { icon } from '../ui/icons.js';
import { emptyState } from '../ui/kit.js';
import { mode } from '../lib/mode.js';

const COLS = [['todo', 'To do'], ['next', 'Next'], ['doing', 'Doing'], ['done', 'Done']];

export default {
  id: 'tasks', key: 'k', dated: false, title: 'Tasks', icon: 'board',
  load: async () => { const [tasks, projects, topicsR] = await Promise.all([api.get('/api/tasks'), api.get('/api/projects'), api.get('/api/topics').catch(() => null)]); return { tasks, projects, topicsR }; },
  view(d) {
    const view = query('v', 'list'), proj = Object.fromEntries(d.projects.map((p) => [p.id, p]));
    const body = h('div', { class: 'tk-body' });
    const setStatus = async (t, st) => {
      const prev = t.status; t.status = st; draw();
      try { await api.post(`/api/tasks/${t.id}`, { status: st }); if (st === 'done') toast(`Done: ${t.title}`, 'good'); }
      catch (e) { t.status = prev; draw(); toast(`Couldn’t update: ${e.message}`, 'bad'); }
    };
    const focusOn = async (t) => {
      try { await api.post('/api/timer/start', { kind: 'focus', task_id: t.id, label: t.title }); await mode.refresh(); go('focus', {}); }
      catch (e) { toast(e.message, 'bad'); }
    };
    // quick add: title + Enter; optional project and estimate
    const title = h('input', { class: 'input grow', placeholder: 'Add a task and press Enter', 'aria-label': 'New task', enterkeyhint: 'done', autocomplete: 'off' });
    const pSel = h('select', { class: 'input', 'aria-label': 'Project' }, h('option', { value: '' }, 'No project'), d.projects.map((p) => h('option', { value: p.id }, p.name)), h('option', { value: '__new' }, 'New project…'));
    const est = h('input', { class: 'input est', type: 'number', min: 5, step: 5, placeholder: 'min', inputmode: 'numeric', 'aria-label': 'Estimate in minutes' });
    pSel.addEventListener('change', async () => {
      if (pSel.value !== '__new') return;
      const inp = h('input', { class: 'input', placeholder: 'Project name, then Enter', 'aria-label': 'New project name', enterkeyhint: 'done' });
      const done = () => { inp.replaceWith(pSel); pSel.focus(); };
      inp.addEventListener('keydown', async (e) => {
        if (e.key === 'Escape') { pSel.value = ''; done(); return; }
        if (e.key !== 'Enter' || !inp.value.trim()) return; const name = inp.value.trim();
        try { const r = await api.post('/api/projects', { name }); d.projects.push({ id: r.id, name }); proj[r.id] = { id: r.id, name }; pSel.insertBefore(h('option', { value: r.id }, name), pSel.lastChild); pSel.value = String(r.id); }
        catch (er) { toast(er.message, 'bad'); pSel.value = ''; }
        done();
      });
      inp.addEventListener('blur', () => { if (inp.isConnected) { pSel.value = ''; done(); } });
      pSel.replaceWith(inp); inp.focus();
    });
    title.addEventListener('keydown', async (e) => {
      if (e.key !== 'Enter' || !title.value.trim()) return;
      const t = { title: title.value.trim(), project_id: pSel.value ? Number(pSel.value) : null, est_min: est.value ? Number(est.value) : null, status: 'todo', tracked_s: 0, id: -Date.now() };
      d.tasks.push(t); title.value = ''; est.value = ''; draw();
      try { const r = await api.post('/api/tasks', { title: t.title, project_id: t.project_id, est_min: t.est_min }); t.id = r.id; draw(); }
      catch (er) { d.tasks.splice(d.tasks.indexOf(t), 1); draw(); toast(`Couldn’t add: ${er.message}`, 'bad'); }
    });
    const row = (t) => h('li', { class: `tk-row${t.status === 'done' ? ' done' : ''}`, 'data-id': t.id },
      h('input', { type: 'checkbox', class: 'tk-check', checked: t.status === 'done' ? true : null, 'aria-label': `Mark ${t.title} done`, onchange: (e) => setStatus(t, e.target.checked ? 'done' : 'todo') }),
      h('span', { class: 'tk-title' }, t.title, t.status === 'doing' || t.status === 'next' ? h('span', { class: `pill ${t.status === 'doing' ? 'accent' : ''}` }, t.status === 'doing' ? 'Doing' : 'Next') : null),
      h('small', { class: 'faint num nowrap' }, [t.tracked_s ? dur(t.tracked_s) : '', t.est_min ? ` / ${t.est_min}m` : ''].join('')),
      t.status !== 'done' ? h('button', { class: 'icon-btn', 'aria-label': `Focus on ${t.title}`, title: 'Start a focus session', onclick: () => focusOn(t) }, icon('play', 16)) : h('span'));
    function list() {
      const open = d.tasks.filter((t) => t.status !== 'done'), done = d.tasks.filter((t) => t.status === 'done');
      const groups = {}; open.forEach((t) => (groups[t.project_id ?? 0] = groups[t.project_id ?? 0] || []).push(t));
      return h('div', { class: 'stack' }, Object.entries(groups).map(([pid, ts]) => h('section', { class: 'card tk-group' },
        h('header', {}, h('h3', {}, proj[pid]?.name || 'No project'), h('small', { class: 'num' }, `${ts.length} · ${dur(ts.reduce((a, t) => a + (t.tracked_s || 0), 0))} tracked`)),
        h('ul', { class: 'tk-list' }, ts.map(row)))),
        done.length ? h('details', { class: 'card tk-done' }, h('summary', {}, `Completed · ${done.length}`), h('ul', { class: 'tk-list' }, done.map(row))) : null);
    }
    function board() {
      let drag = null;
      return h('div', { class: 'kb' }, COLS.map(([st, label]) => {
        const items = d.tasks.filter((t) => (t.status || 'todo') === st);
        const col = h('section', { class: 'kb-col', 'data-st': st, 'aria-label': label },
          h('header', {}, h('h3', {}, label), h('span', { class: 'badge-n num' }, String(items.length))),
          h('ul', {}, items.map((t) => { const i = COLS.findIndex((c) => c[0] === st);
            return h('li', { class: 'kb-card', draggable: 'true', 'data-id': t.id, ondragstart: (e) => { drag = t; e.dataTransfer.effectAllowed = 'move'; e.currentTarget.classList.add('lift'); }, ondragend: (e) => e.currentTarget.classList.remove('lift') },
              h('b', {}, t.title), t.project_id && proj[t.project_id] ? h('small', { class: 'faint' }, proj[t.project_id].name) : null,
              h('div', { class: 'kb-act' }, i > 0 ? h('button', { class: 'icon-btn', 'aria-label': `Move ${t.title} to ${COLS[i - 1][1]}`, onclick: () => setStatus(t, COLS[i - 1][0]) }, icon('left', 16)) : h('span'),
                st !== 'done' ? h('button', { class: 'icon-btn', 'aria-label': `Focus on ${t.title}`, onclick: () => focusOn(t) }, icon('play', 16)) : h('span'),
                i < COLS.length - 1 ? h('button', { class: 'icon-btn', 'aria-label': `Move ${t.title} to ${COLS[i + 1][1]}`, onclick: () => setStatus(t, COLS[i + 1][0]) }, icon('right', 16)) : h('span'))); })));
        col.addEventListener('dragover', (e) => { e.preventDefault(); col.classList.add('over'); });
        col.addEventListener('dragleave', () => col.classList.remove('over'));
        col.addEventListener('drop', (e) => { e.preventDefault(); col.classList.remove('over'); if (drag && drag.status !== st) setStatus(drag, st); });
        return col;
      }));
    }
    function draw() { body.replaceChildren(d.tasks.length ? (view === 'board' ? board() : list()) : emptyState('No tasks yet', 'Type a task above and press Enter. Press play on any task to start a focus session on it.')); }
    draw();
    const open = d.tasks.filter((t) => t.status !== 'done').length;
    const recallBox = h('div', { class: 'stack' });
    const qIn = h('input', { class: 'input grow', placeholder: 'Recall anything: try “focus leak” or “slack”…', 'aria-label': 'Recall across tasks, challenges, insights and conversations', autocomplete: 'off' });
    const doRecall = async () => { const q = qIn.value.trim(); if (!q) return; try { const r = await api.get('/api/recall?q=' + encodeURIComponent(q)); recallBox.replaceChildren(...(r.results.length ? r.results.map((x) => h('p', {}, h('b', {}, `${x.kind} · `), x.text, h('small', { class: 'faint num' }, ` ${Math.round(x.score * 100)}%`))) : [h('p', { class: 'muted' }, 'Nothing recalled for that yet.')])); } catch (e) { toast(e.message, 'bad'); } };
    qIn.addEventListener('keydown', (e) => { if (e.key === 'Enter') doRecall(); });
    const topicsCard = h('section', { class: 'card', 'aria-labelledby': 'tp-h' }, h('header', {}, h('h3', { id: 'tp-h' }, 'Topics & recall'), h('small', {}, 'local vectors · honeycomb stored')),
      d.topicsR ? h('div', { class: 'row wrap' }, d.topicsR.buckets.map((b) => h('span', { class: 'pill' }, `${b.label} (${b.items.length})${b.folded ? ' folded' : ''}`))) : h('p', { class: 'faint' }, 'Buckets form as tasks, challenges and conversations arrive.'),
      h('div', { class: 'row wrap' }, qIn, h('button', { class: 'btn', onclick: doRecall }, 'Recall')), recallBox);
    return h('div', { class: 'page' }, topicsCard,
      h('div', { class: 'page-head' }, h('div', { class: 'grow' }, h('h1', {}, 'Tasks'), h('p', {}, `${open} open · ${d.tasks.length - open} done`)),
        h('div', { class: 'seg', role: 'group', 'aria-label': 'View' }, [['list', 'List'], ['board', 'Board']].map(([v, l]) => h('button', { 'aria-pressed': String(view === v), onclick: () => patch({ v: v === 'list' ? '' : v }) }, l)))),
      h('div', { class: 'card tk-add row' }, title, pSel, est), body);
  },
};
