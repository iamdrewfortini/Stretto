// Privacy: every data family Stretto can collect or send, each with its notice from the server. Nothing is collected
// or sent for a family until a person accepts its notice by typing their name and the exact phrase (no pasting).
import { h } from '../lib/dom.js';
import { api } from '../lib/api.js';
import { query } from '../lib/router.js';
import { toast } from '../ui/toast.js';
import { pill } from '../ui/kit.js';

const SECTIONS = [['reads', 'Reads'], ['stores', 'Keeps'], ['never', 'Never'], ['goes', 'Goes to'], ['warn', 'Worth knowing']];
const when = (ts) => new Date(ts * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

export default {
  id: 'privacy', key: 'v', dated: false, title: 'Privacy', icon: 'shield',
  load: async () => {
    const st = await api.get('/api/consent'), fams = Object.keys(st.families);
    const notices = await Promise.all(fams.map((f) => api.get(`/api/consent/notice?family=${encodeURIComponent(f)}`)));
    return { st, notices };
  },
  view(d) {
    const focusFam = query('f', '');
    const name0 = localStorage.getItem('stretto.name') || '';
    const cards = d.notices.map((n) => {
      const s = d.st.families[n.family], on = !!s.active;
      const status = h('div', { class: 'pv-status' }, pill(on ? 'On' : 'Off', on ? 'good' : ''), s.by ? h('small', { class: 'faint' }, `${s.action === 'grant' ? 'Accepted' : 'Revoked'} by ${s.by} · ${when(s.ts)}`) : h('small', { class: 'faint' }, 'Never accepted'));
      const name = h('input', { class: 'input', value: name0, placeholder: 'Your name', autocomplete: 'name', 'aria-label': 'Your name' });
      const typed = h('input', { class: 'input', placeholder: n.phrase, autocomplete: 'off', spellcheck: 'false', autocapitalize: 'off', 'aria-label': `Type exactly: ${n.phrase}`, onpaste: (e) => { e.preventDefault(); toast('Please type the phrase yourself'); } });
      const accept = h('button', { class: 'btn primary', disabled: true }, 'Accept');
      const check = () => { accept.disabled = !(name.value.trim() && typed.value.trim() === n.phrase); };
      name.addEventListener('input', check); typed.addEventListener('input', check);
      const send = async (action) => {
        const who = name.value.trim(); if (!who) { name.focus(); toast('Add your name first'); return; }
        try { const r = await api.post('/api/consent', { device: 'local', family: n.family, action, granted_by: who, typed: typed.value.trim() });
          localStorage.setItem('stretto.name', who); Object.assign(s, r); toast(action === 'grant' ? `${n.title}: accepted` : `${n.title}: turned off`); location.reload(); }
        catch (e) { toast(e.message, 'bad'); }
      };
      accept.addEventListener('click', () => send('grant'));
      const form = on
        ? h('div', { class: 'pv-form row wrap' }, name, h('button', { class: 'btn', onclick: () => send('revoke') }, 'Turn off'), h('small', { class: 'faint' }, 'Turning off stops collection at once. Data already kept stays until you purge it.'))
        : h('div', { class: 'pv-form' }, h('p', { class: 'muted' }, 'To accept, type your name and exactly: ', h('b', { class: 'mono' }, n.phrase)), h('div', { class: 'row wrap' }, name, typed, accept));
      return h('section', { class: `card pv${on ? ' on' : ''}`, id: `pv-${n.family}`, 'aria-labelledby': `pvh-${n.family}` },
        h('header', {}, h('h3', { id: `pvh-${n.family}` }, n.title), status),
        h('div', { class: 'pv-grid' }, SECTIONS.filter(([k]) => n[k] && n[k].length).map(([k, label]) => h('div', { class: `pv-sec pv-${k}` }, h('h4', {}, label), h('ul', {}, n[k].map((x) => h('li', {}, x)))))),
        form);
    });
    const page = h('div', { class: 'page' },
      h('div', { class: 'page-head' }, h('div', { class: 'grow' }, h('h1', {}, 'Privacy'), h('p', {}, 'Nothing is collected or sent for a family until a person accepts its notice.')),
        pill(d.st.chain_ok ? 'Consent log intact' : 'Consent log check failed', d.st.chain_ok ? 'good' : 'bad')), cards);
    if (focusFam) requestAnimationFrame(() => document.getElementById(`pv-${focusFam}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
    return page;
  },
};
