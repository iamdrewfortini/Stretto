// Insights: Meta-model coaching over measured findings. Suggestions are always labelled "Inferred": the model may phrase
// and rank findings, never create them. The live panel shows every model call (for the demo: calls are visible).
import { h } from '../lib/dom.js';
import { api } from '../lib/api.js';
import { dur, nice } from '../lib/fmt.js';
import { go } from '../lib/router.js';
import { toast } from '../ui/toast.js';
import { pill, emptyState } from '../ui/kit.js';

const usd = (x) => `$${Number(x || 0).toFixed(Number(x) < 0.01 && x ? 4 : 2)}`;
const REASON = {
  consent: ['Turn on Meta insights first', 'Nothing goes to Meta until you accept the notice. Only app names, site domains and minutes are sent, never titles or addresses.'],
  no_model_access: ['No model access on this server', 'The Stretto server has no Meta API key or recording configured, so insights can’t be generated here.'],
  not_generated_yet: ['Ready to generate', 'Ask Meta to rank and phrase today’s measured findings. Each call is logged below with its cost.'],
};

export default {
  id: 'insights', key: 'i', dated: true, title: 'Insights', icon: 'spark',
  load: async (ctx) => {
    const [ins, status, calls] = await Promise.all([api.get('/api/insights?date=' + ctx.date), api.get('/api/meta/status').catch(() => null), api.get('/api/meta/calls?limit=12').catch(() => ({ calls: [] }))]);
    return { ins, status, calls: calls.calls || [], chain: calls.chain_ok };
  },
  view(d, ctx) {
    const ins = d.ins, st = d.status;
    const head = h('div', { class: 'page-head' }, h('div', { class: 'grow' }, h('h1', {}, 'Insights'), h('p', {}, `${ctx.isToday ? 'Today' : nice(ctx.date)} · suggestions are inferred by a model from measured findings`)), pill('Inferred', 'info'));
    const gen = async (btn, refresh = false) => {
      btn.disabled = true; btn.setAttribute('aria-busy', 'true'); const label = btn.textContent; btn.textContent = 'Asking Meta…';
      try { await api.post('/api/insights', { date: ctx.date, device: 'local', refresh }); toast('Insights ready'); go('insights', { d: ctx.isToday ? '' : ctx.date }, { replace: true }); }
      catch (e) { btn.disabled = false; btn.removeAttribute('aria-busy'); btn.textContent = label; toast(e.message, 'bad'); }
    };
    let main;
    if (ins.available) {
      main = h('section', { class: 'card hero raised ins' }, h('header', {}, h('h3', {}, 'What to change'), h('small', { class: 'num' }, `${ins.model || ''}${ins.cached ? ' · cached' : ''}`)),
        h('p', { class: 'ins-head' }, ins.headline),
        h('ol', { class: 'ins-list' }, (ins.actions || []).map((a, i) => h('li', {}, h('span', { class: 'ins-n num' }, String(i + 1)),
          h('div', {}, h('div', { class: 'row wrap' }, h('b', {}, a.title), pill('Inferred', 'info')), h('p', { class: 'muted' }, a.how), a.finding != null ? h('small', { class: 'faint' }, `From finding: ${typeof a.finding === 'object' ? a.finding.kind || '' : a.finding}`) : null)))),
        h('div', { class: 'row wrap ins-foot' }, h('small', { class: 'faint num' }, [ins.tokens ? `${ins.tokens} tokens` : '', ins.cost_usd != null ? usd(ins.cost_usd) : ''].filter(Boolean).join(' · ')),
          h('button', { class: 'btn sm', onclick: (e) => gen(e.currentTarget, true) }, 'Ask again')));
    } else {
      const [t, b] = REASON[ins.reason] || ['Not available', ins.reason || ''];
      const act = ins.reason === 'consent' ? h('button', { class: 'btn primary', 'data-next': '', onclick: () => go('privacy', { f: 'meta-insights' }) }, 'Review the notice')
        : ins.reason === 'not_generated_yet' ? h('button', { class: 'btn primary', 'data-next': '', onclick: (e) => gen(e.currentTarget) }, 'Generate insights') : null;
      main = emptyState(t, b, act); main.classList.add('hero', 'raised');
    }
    const meter = st ? Math.min(1, (st.spent_today_usd || 0) / Math.max(0.0001, st.budget_usd || 0)) : 0;
    const panel = h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'Meta calls'), st ? pill(st.mode ? `Live · ${st.mode}` : 'Not connected', st.mode ? 'good' : '') : null),
      st ? h('p', { class: 'faint mc-sub' }, `Model ${st.model || '—'}`) : null,
      st ? h('div', { class: 'grid g2 mc-stats' },

        h('div', { class: 'stat flat' }, h('span', { class: 'k' }, 'Calls today'), h('span', { class: 'v num' }, String(st.calls_today ?? 0))),
        h('div', { class: 'stat flat' }, h('span', { class: 'k' }, 'Spent today'), h('span', { class: 'v num' }, `${usd(st.spent_today_usd)}`), h('div', { class: 'bar' }, h('i', { style: { '--f': String(meter), background: meter > .9 ? 'var(--signal)' : 'var(--tonic)' } })), h('span', { class: 's' }, `of ${usd(st.budget_usd)} daily budget`))) : null,
      d.calls.length ? h('div', { class: 'tablewrap' }, h('table', { class: 't' }, h('thead', {}, h('tr', {}, ['When', 'Model', 'Tokens in / out', 'Cost', 'Time', 'Status'].map((x, i) => h('th', { class: i >= 2 && i <= 4 ? 'num' : '' }, x)))),
        h('tbody', {}, d.calls.map((c) => h('tr', {}, h('td', { 'data-label': 'When' }, c.ts ? new Date(c.ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—'), h('td', { 'data-label': 'Model' }, c.served || c.model || '—'),
          h('td', { class: 'num', 'data-label': 'Tokens' }, `${c.prompt_tokens ?? '—'} / ${c.completion_tokens ?? '—'}${c.reasoning_tokens ? ` (+${c.reasoning_tokens} reasoning)` : ''}`), h('td', { class: 'num', 'data-label': 'Cost' }, usd(c.cost_usd)),
          h('td', { class: 'num', 'data-label': 'Time' }, c.seconds != null ? `${Number(c.seconds).toFixed(1)}s` : '—'), h('td', { 'data-label': 'Status' }, pill(c.status || '—', c.status === 'ok' ? 'good' : c.status ? 'bad' : '')))))))
        : h('p', { class: 'muted' }, 'No calls yet. Each call to Meta appears here with tokens, cost and time.'),
      h('small', { class: 'faint' }, d.chain === false ? 'Call log integrity check failed.' : 'The call log is append-only and hash-chained.'));
    return h('div', { class: 'page' }, head, h('div', { class: 'grid g-main' }, main, panel));
  },
};
