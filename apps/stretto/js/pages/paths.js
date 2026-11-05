import { h } from '../lib/dom.js';
import { api } from '../lib/api.js';
import { dur, nice } from '../lib/fmt.js';
import { query, patch } from '../lib/router.js';
import { pill, emptyState, findingCard, route, KIND } from '../ui/kit.js';
import { field } from '../charts/wave.js';

export default {
  id: 'paths', key: 'p', dated: true, title: 'Paths', icon: 'route',
  load: (ctx) => api.get('/api/day?date=' + ctx.date),
  view(d, ctx) {
    const head = h('div', { class: 'page-head' }, h('div', { class: 'grow' }, h('h1', {}, 'Paths'), h('p', {}, 'The routes you took, and where a shorter one exists.')), d.simulated ? pill('Simulated data', '') : null);
    if (!d.transitions.length) return h('div', { class: 'page' }, head, emptyState('No paths for this day', 'A path needs at least two places visited in a row. Pick another day or load the simulated one from Today.'));
    const sel = query('f', '') === '' ? -1 : Number(query('f'));
    const f0 = sel >= 0 ? d.findings[sel] : null;
    const hot = !f0 ? [] : f0.kind === 'ping_pong' ? [f0.where[0], f0.where[1], f0.where[0]] : f0.where;
    const graph = h('section', { class: 'card raised pin', 'aria-labelledby': 'flow-h' }, h('header', {}, h('h3', { id: 'flow-h' }, 'Your day as a field')), field(d.transitions, d.summary.by_app, hot, d.blocks), h('p', { class: 'faint field-note' }, 'Each place radiates by time spent, coloured by its category’s note; rings count visits and lean toward the usual next stop. Line width is how often; line style is the interval: solid consonant, dotted dissonant.'));
    const picks = h('section', { class: 'card', 'aria-labelledby': 'taken-h' }, h('header', {}, h('h3', { id: 'taken-h' }, 'Taken vs faster'), h('small', {}, `${d.findings.length} routes to review`)),
      d.findings.length ? h('div', { class: 'sheet-list' }, d.findings.map((f, i) => findingCard(f, { on: i === sel, onSee: () => patch({ f: String(i) }),
        lead: route(f.kind === 'repeated_path' ? f.where : f.where.slice(0, 4)),
        note: f.kind === 'repeated_path' ? `Upper bound: all ${dur(f.seconds)} could go if this route became one step. A ceiling, not a promise.` : null })))
        : h('p', { class: 'muted' }, 'No repeated or wasteful routes today.'));
    const table = h('section', { class: 'card', 'aria-labelledby': 'moves-h' }, h('header', {}, h('h3', { id: 'moves-h' }, 'Every move, most frequent first')),
      h('div', { class: 'tablewrap' }, h('table', { class: 't' }, h('thead', {}, h('tr', {}, h('th', {}, 'From'), h('th', {}, 'To'), h('th', { class: 'num' }, 'Times'), h('th', { class: 'num' }, 'Avg stay'))),
        h('tbody', {}, d.transitions.map((t) => h('tr', {}, h('td', { 'data-label': 'From' }, t.src), h('td', { 'data-label': 'To' }, t.dst), h('td', { class: 'num', 'data-label': 'Times' }, String(t.count)), h('td', { class: 'num', 'data-label': 'Avg stay' }, dur(t.avg_stay_s))))))));
    return h('div', { class: 'page' }, head, h('div', { class: 'grid g-main' }, graph, picks), table);
  },
};