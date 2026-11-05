// Challenges: what the user sees. Grouped loss, compounded over time, one simplest fix per pattern, asked
// Socratically. The route field and every-move table are backend evidence, folded away below.
import { h, s } from '../lib/dom.js';
import { api } from '../lib/api.js';
import { dur, nice } from '../lib/fmt.js';
import { query, patch } from '../lib/router.js';
import { pill, emptyState, findingCard, route, KIND } from '../ui/kit.js';
import { toast } from '../ui/toast.js';
import { field } from '../charts/wave.js';

function cumulative(days) {
  const W = 1000, H = 150, n = days.length, cum = []; let acc = 0;
  days.forEach((d) => { acc += d.loss_min; cum.push(acc); });
  const max = Math.max(1, acc), X = (i) => (n === 1 ? W / 2 : (i / (n - 1)) * W), Y = (v) => H - (v / max) * (H - 14);
  let line = ''; cum.forEach((v, i) => { line += `${i ? 'L' : 'M'}${X(i).toFixed(1)} ${Y(v).toFixed(1)} `; });
  return h('section', { class: 'card', 'aria-labelledby': 'cum-h' }, h('header', {}, h('h3', { id: 'cum-h' }, 'Time lost, compounded'), h('small', {}, `${dur(acc * 60)} over ${n} measured day${n === 1 ? '' : 's'}`)),
    s('svg', { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', class: 'rp-trend', role: 'img', 'aria-label': `Cumulative lost time rising to ${dur(acc * 60)}` },
      s('path', { d: `${line} L${X(n - 1)} ${H} L${X(0)} ${H} Z`, fill: 'var(--signal-soft, rgba(182,48,62,.14))' }),
      s('path', { d: line, class: 'rp-line', 'vector-effect': 'non-scaling-stroke' })),
    h('p', { class: 'faint' }, 'Every day the pattern repeats, this line climbs. A challenge is priced by how much of the climb it stops.'));
}

function challengeCard(c, pins = []) {
  const pin = pins.find((p) => p.status === 'active' && p.kind === c.kind && JSON.stringify(p.places) === JSON.stringify(c.places.slice(0, 4)));
  const donePin = pins.find((p) => p.status === 'completed' && p.kind === c.kind && JSON.stringify(p.places) === JSON.stringify(c.places.slice(0, 4)));
  const accept = async (e) => { const b = e.currentTarget; b.disabled = true;
    try { await api.post('/api/challenges/pin', { kind: c.kind, places: c.places, fix: c.fix, xp_reward: c.xp_reward }); await api.post('/api/tasks', { title: c.fix, est_min: c.minutes_per_day }); toast(`Pinned. +${c.xp_reward} XP lands automatically on your first clean day`, 'good'); b.textContent = '📌 Pinned — on Tasks'; }
    catch (err) { b.disabled = false; toast(err.message, 'bad'); } };
  const unpin = async (e) => { const b = e.currentTarget; b.disabled = true;
    try { await api.post('/api/challenges/unpin', { id: pin.id }); toast('Unpinned'); b.textContent = 'Unpinned'; } catch (err) { b.disabled = false; toast(err.message, 'bad'); } };
  return h('section', { class: 'card', 'aria-labelledby': `ch-${c.kind}` },
    h('header', {}, h('h3', { id: `ch-${c.kind}` }, `${KIND[c.kind] || c.kind}: ${c.places.slice(0, 3).join(' ↔ ')}`), pill(c.tier, c.tier === 'Stretch' ? 'bad' : 'info')),
    h('p', { class: 'num' }, `${dur(c.minutes_per_day * 60)} lost a day · ${dur(c.compounded.days30 * 60)} in 30 days if nothing changes`),
    h('p', {}, h('b', {}, 'Simplest fix: '), c.fix),
    h('p', { class: 'muted' }, c.ask),
    donePin ? h('p', {}, pill(`Completed ${donePin.completed_date} · +${donePin.xp} XP awarded`, 'good')) : null,
    h('div', { class: 'row wrap' }, pin ? h('button', { class: 'btn', onclick: unpin }, '📌 Pinned — waiting for a clean day (unpin)') : h('button', { class: 'btn primary', 'data-next': '', onclick: accept }, `📌 Pin it — earn ${c.xp_reward} XP`), h('small', { class: 'faint' }, `seen on ${c.days_seen} day${c.days_seen === 1 ? '' : 's'} · reward priced in minutes reclaimed`)));
}

export default {
  id: 'paths', key: 'p', dated: true, title: 'Challenges', icon: 'route',
  load: async (ctx) => { const [ch, d] = await Promise.all([api.get('/api/challenges?days=30').catch(() => null), api.get('/api/day?date=' + ctx.date)]); return { ch, d }; },
  view({ ch, d }, ctx) {
    const head = h('div', { class: 'page-head' }, h('div', { class: 'grow' }, h('h1', {}, 'Challenges'), h('p', {}, 'Grouped loss, compounded. One simplest fix each — asked, not ordered.')), (d.simulated || (ch && ch.simulated)) ? pill('Simulated data', '') : null);
    if (!ch || !ch.challenges.length) return h('div', { class: 'page' }, head, emptyState('No challenges yet', 'Challenges are grouped from measured loss. Record a day, or load the labelled simulated day from Today.'));
    const graph = h('section', { class: 'card raised pin', 'aria-labelledby': 'flow-h' }, h('header', {}, h('h3', { id: 'flow-h' }, 'Evidence: your day as a field')), field(d.transitions, d.summary.by_app, [], d.blocks), h('p', { class: 'faint field-note' }, 'Backend routing, kept as evidence. Places radiate by time spent; line width is how often the route ran.'));
    const sel = query('f', '') === '' ? -1 : Number(query('f'));
    const picks = h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'Route evidence for today'), h('small', {}, `${d.findings.length} routes to review`)),
      d.findings.length ? h('div', { class: 'sheet-list' }, d.findings.map((f, i) => findingCard(f, { on: i === sel, onSee: () => patch({ f: String(i) }), lead: route(f.kind === 'repeated_path' ? f.where : f.where.slice(0, 4)) }))) : h('p', { class: 'muted' }, 'No repeated or wasteful routes today.'));
    const table = h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'Every move, most frequent first')),
      h('div', { class: 'tablewrap' }, h('table', { class: 't' }, h('thead', {}, h('tr', {}, h('th', {}, 'From'), h('th', {}, 'To'), h('th', { class: 'num' }, 'Times'), h('th', { class: 'num' }, 'Avg stay'))),
        h('tbody', {}, d.transitions.map((t) => h('tr', {}, h('td', { 'data-label': 'From' }, t.src), h('td', { 'data-label': 'To' }, t.dst), h('td', { class: 'num', 'data-label': 'Times' }, String(t.count)), h('td', { class: 'num', 'data-label': 'Avg stay' }, dur(t.avg_stay_s))))))));
    const evidence = h('details', { class: 'card' }, h('summary', {}, 'Evidence: routes, field and every move'), h('div', { class: 'stack' }, graph, picks, table));
    return h('div', { class: 'page' }, head, cumulative(ch.days),
      h('p', { class: 'muted' }, `Total: ${dur(ch.total.per_day * 60)} a day · ${dur(ch.total.days30 * 60)} compounded over 30 days.`),
      ...ch.challenges.map((c) => challengeCard(c, ch.pins || [])), evidence);
  },
};
