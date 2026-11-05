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
      const purgeIn = h('input', { class: 'input', placeholder: `DELETE ${n.family}`, autocomplete: 'off', spellcheck: 'false', autocapitalize: 'off', 'aria-label': `Type exactly: DELETE ${n.family} to purge` });
      const purge = async () => { try { const r = await api.post('/api/purge', { device: 'local', family: n.family, confirm: purgeIn.value.trim() }); toast(`Purged ${r.deleted} record(s) for ${n.title}`); location.reload(); } catch (e) { toast(e.message, 'bad'); } };
      const form = on
        ? h('div', { class: 'pv-form row wrap' }, name, h('button', { class: 'btn', onclick: () => send('revoke') }, 'Turn off'), purgeIn, h('button', { class: 'btn danger', onclick: purge }, 'Purge kept data'), h('small', { class: 'faint' }, 'Turning off stops collection at once. Purge deletes what was already kept; type the DELETE phrase to confirm.'))
        : h('div', { class: 'pv-form' }, h('p', { class: 'muted' }, 'To accept, type your name and exactly: ', h('b', { class: 'mono' }, n.phrase)), h('div', { class: 'row wrap' }, name, typed, accept));
      return h('section', { class: `card pv${on ? ' on' : ''}`, id: `pv-${n.family}`, 'aria-labelledby': `pvh-${n.family}` },
        h('header', {}, h('h3', { id: `pvh-${n.family}` }, n.title), status),
        h('div', { class: 'pv-grid' }, SECTIONS.filter(([k]) => n[k] && n[k].length).map(([k, label]) => h('div', { class: `pv-sec pv-${k}` }, h('h4', {}, label), h('ul', {}, n[k].map((x) => h('li', {}, x)))))),
        form);
    });
    // Single consent form: one name, tick the families, one typed phrase. Each tick still becomes its own hash-chained grant.
    const BULK = 'I AGREE: ALL';
    const bName = h('input', { class: 'input', value: name0, placeholder: 'Your name', autocomplete: 'name', 'aria-label': 'Your name (single form)' });
    const bTyped = h('input', { class: 'input', placeholder: BULK, autocomplete: 'off', spellcheck: 'false', autocapitalize: 'off', 'aria-label': `Type exactly: ${BULK}`, onpaste: (e) => { e.preventDefault(); toast('Please type the phrase yourself'); } });
    const pending = d.notices.filter((n) => !d.st.families[n.family].active);
    const boxes = pending.map((n) => { const c = h('input', { type: 'checkbox', 'aria-label': n.title }); return { fam: n.family, box: c, row: h('label', { class: 'row' }, c, h('span', {}, n.title)) }; });
    const bBtn = h('button', { class: 'btn primary', 'data-next': '' }, 'Accept selected');
    bBtn.addEventListener('click', async () => { const fams = boxes.filter((b) => b.box.checked).map((b) => b.fam); if (!bName.value.trim()) { bName.focus(); toast('Add your name first'); return; } if (!fams.length) { toast('Tick at least one family'); return; }
      try { await api.post('/api/consent/bulk', { device: 'local', families: fams, granted_by: bName.value.trim(), typed: bTyped.value.trim() }); localStorage.setItem('stretto.name', bName.value.trim()); toast(`Accepted ${fams.length} ${fams.length === 1 ? 'notice' : 'notices'}`); location.reload(); } catch (e) { toast(e.message, 'bad'); } });
    const bulk = h('section', { class: 'card', 'aria-labelledby': 'pv-bulk-h' }, h('header', {}, h('h3', { id: 'pv-bulk-h' }, 'Consent — one form'), pill('single form', 'info')),
      h('p', { class: 'muted' }, 'Read the notices below, tick the families you accept, then type your name and exactly ', h('b', { class: 'mono' }, BULK), '. Each family is still logged separately, and you can turn any one off below.'),
      boxes.length ? h('div', { class: 'stack' }, boxes.map((b) => b.row), h('div', { class: 'row wrap' }, bName, bTyped, bBtn)) : h('p', { class: 'faint' }, 'Every notice is already accepted. Turn one off in its card below.'));
    const page = h('div', { class: 'page' },
      h('div', { class: 'page-head' }, h('div', { class: 'grow' }, h('h1', {}, 'Privacy'), h('p', {}, 'Nothing is collected or sent for a family until a person accepts its notice.')),
        pill(d.st.chain_ok ? 'Consent log intact' : 'Consent log check failed', d.st.chain_ok ? 'good' : 'bad')), bulk, cards);
    if (focusFam) requestAnimationFrame(() => document.getElementById(`pv-${focusFam}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
    return page;
  },
};
