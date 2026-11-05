// Devices: how a computer joins (UI-STEPS-026: download → enrol → report → consent → recording, each state read from the server),
// the enrolled computers with their permission plans, and the data sources that are actually arriving.
// The agent bundle carries a single-use 15-minute enrolment code, never the master token; installing never records anything
// until a person accepts the notices in Privacy.
import { h } from '../lib/dom.js';
import { api } from '../lib/api.js';
import { toast } from '../ui/toast.js';
import { pill, emptyState } from '../ui/kit.js';
import { icon } from '../ui/icons.js';

const token = () => document.querySelector('meta[name="stretto-token"]')?.content || '';
const OSES = [['macos', 'macOS', 'sh install.sh', 'a login item (LaunchAgent com.stretto.agent)', 'sh install.sh --uninstall'], ['windows', 'Windows', '.\\install.ps1', 'a scheduled task (StrettoAgent) at sign-in', '.\\install.ps1 -Uninstall'], ['linux', 'Linux', 'sh install.sh', 'a user systemd service (stretto-agent)', 'sh install.sh --uninstall']];
const STATUS = { granted: ['Granted', 'good'], missing: ['Missing', 'bad'], unknown: ['Unknown', ''], unsupported: ['Not supported', ''], not_applicable: ['Not needed', ''] };
const ago = (ts) => { if (!ts) return 'never'; const m = Math.round((Date.now() / 1000 - ts) / 60); return m < 1 ? 'just now' : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : new Date(ts * 1000).toLocaleDateString(); };
const copyBtn = (text) => h('button', { class: 'btn sm', onclick: async () => { try { await navigator.clipboard.writeText(text); toast('Copied', 'good'); } catch { toast('Select the text and copy it', 'bad'); } } }, 'Copy');

async function download(os, btn) {
  btn.disabled = true; btn.setAttribute('aria-busy', 'true');
  try {
    const res = await fetch('/api/agent/bundle', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Stretto-Token': token() }, body: JSON.stringify({ os }) });
    if (!res.ok) { const j = await res.json().catch(() => ({})); throw new Error(j.error || `download failed (${res.status})`); }
    const blob = await res.blob(), name = (res.headers.get('Content-Disposition') || '').match(/filename="?([^";]+)/)?.[1] || `stretto-agent-${os}.zip`;
    const a = h('a', { href: URL.createObjectURL(blob), download: name }); document.body.append(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    toast(`Downloaded ${name} · the code inside works once, for 15 minutes`, 'good');
  } catch (e) { toast(e.message, 'bad'); }
  finally { btn.disabled = false; btn.removeAttribute('aria-busy'); }
}

// The five states a computer passes through, each decided from server data, never assumed
function journey(dev, env, consented, sources) {
  const local = dev && dev.id === 'local';
  const steps = [
    ['Enrolled', dev ? (dev.id === 'local' ? 'this server’s own computer, no key needed' : `key issued ${ago(dev.first_seen)}`) : 'run the installer on that computer', !!dev],
    ['Environment reported', local ? 'not needed: no agent runs here' : env ? `${env.os_label || dev.os || ''} · ${env.required_missing?.length ? env.required_missing.length + ' required permission(s) missing' : 'nothing required is missing'}` : 'the agent reports what it may read on first start', local || !!env],
    ['Notices accepted', consented ? 'in Privacy, by a person' : local && sources.every((s) => s.src === 'simulated') ? 'simulated data needs no consent; real sources will' : 'nothing is recorded until someone accepts in Privacy', consented || (local && sources.length > 0 && sources.every((s) => s.src === 'simulated'))],
    ['Data arriving', sources.length ? `${sources.length} source${sources.length > 1 ? 's' : ''} · last ${ago(Math.max(...sources.map((s) => s.last_ts || 0)))}` : 'the agent sends a batch every few seconds once allowed', sources.length > 0],
  ];
  let current = steps.findIndex(([, , done]) => !done); if (current < 0) current = steps.length;
  return h('ol', { class: 'steps', 'aria-label': 'Enrolment steps' }, steps.map(([t, sub, done], i) => h('li', { class: `step ${done ? 'done' : i === current ? 'current' : 'next'}` },
    h('i', { class: 'step-dot', 'aria-hidden': 'true' }), h('div', { class: 'step-body' }, h('div', { class: 'row wrap' }, h('b', {}, t), i === current ? pill('Next', 'info') : null), h('small', { class: 'muted' }, sub)))));
}

function plan(dev) {
  const box = h('div', { class: 'dv-plan' }, h('p', { class: 'muted' }, 'Loading this computer’s permissions…'));
  api.get(`/api/agent/environment?device=${encodeURIComponent(dev.id)}`).then((r) => {
    const p = r.plan; if (!p) { box.replaceChildren(h('p', { class: 'muted' }, 'The agent hasn’t reported its environment yet.')); return; }
    box.replaceChildren(h('p', { class: 'faint' }, `${p.os_label} · user ${p.user}${p.admin ? ' (administrator)' : ''} · ${p.source}`),
      h('ul', { class: 'dv-items' }, p.items.map((it) => { const [w, tone] = STATUS[it.status] || [it.status, ''];
        return h('li', {}, h('div', { class: 'row wrap' }, h('b', {}, it.label), pill(it.available === false ? 'Planned' : w, it.available === false ? '' : tone), it.required ? h('small', { class: 'faint' }, 'required') : null),
          h('p', { class: 'muted' }, it.why), it.note ? h('small', { class: 'faint' }, it.note) : null,
          it.status === 'missing' && it.available !== false ? h('div', { class: 'dv-do' },
            it.panel ? h('p', {}, 'On that computer, open ', h('b', {}, it.panel.label), ' or run ', h('code', { class: 'mono' }, `stretto-agent perms open ${it.id}`)) : null,
            it.elevated ? h('div', { class: 'dv-cmd' }, h('small', { class: 'faint' }, it.elevated.description), h('pre', { class: 'mono' }, it.elevated.display), copyBtn(it.elevated.display), h('small', { class: 'faint' }, `Run it on that computer, as the person who owns it: ${it.elevated.how || `stretto-agent perms run ${it.id}`}`)) : null) : null); })));
  }).catch((e) => box.replaceChildren(h('p', { class: 'muted' }, e.message)));
  return box;
}

export default {
  id: 'devices', key: 'd', dated: false, title: 'Devices', icon: 'devices',
  load: async () => {
    const [devs, src, consent] = await Promise.all([api.get('/api/agent/devices').catch(() => ({ devices: [] })), api.get('/api/sources').catch(() => null), api.get('/api/consent').catch(() => null)]);
    const devices = devs.devices || [];
    const envs = await Promise.all(devices.map((d) => api.get(`/api/agent/environment?device=${encodeURIComponent(d.id)}`).then((r) => r.plan).catch(() => null)));
    return { devices, envs, sources: src, consent };
  },
  view(d) {
    const fams = d.consent?.families || d.consent || [];
    const consented = Array.isArray(fams) ? fams.some((f) => f.active || f.granted) : Object.values(fams).some((f) => f && (f.active || f.granted));
    const srcs = d.sources?.sources || [];
    const install = h('section', { class: 'card hero raised', 'aria-labelledby': 'dv-h' }, h('header', {}, h('h3', { id: 'dv-h' }, 'Add a computer'), h('small', {}, 'the code inside works once, for 15 minutes')),
      h('div', { class: 'dv-os' }, OSES.map(([os, label]) => h('button', { class: 'btn dv-osb', onclick: (e) => download(os, e.currentTarget) }, icon('devices', 18), `${label} agent`))),
      h('ol', { class: 'dv-steps' }, h('li', {}, 'Download the agent for that computer and unzip it there. The zip holds the agent’s source, an installer you can read, and ', h('code', { class: 'mono' }, 'agent.json'), ' with this server’s address and the one-time code. It never holds the master token.'),
        h('li', {}, 'Run the installer in that folder: ', OSES.map(([, l, cmd], i) => [i ? ' · ' : '', `${l}: `, h('code', { class: 'mono' }, cmd)]), '. It needs Python 3.8+, no administrator rights, and network access only to this server. It trades the code for a key that belongs to that computer alone and registers ', OSES.map(([, l, , how], i) => [i ? '; ' : '', `${l}: ${how}`]), '.'),
        h('li', {}, 'Accept the notices for what it may collect, in ', h('a', { href: '#/privacy' }, 'Privacy'), '. Until then the server refuses every batch. The agent captures the front app, its window title, idle time and pointer position; never keystrokes, screen contents or the clipboard.')),
      h('p', { class: 'faint' }, 'Remove it later with ', OSES.map(([, l, , , un], i) => [i ? ' · ' : '', `${l}: `, h('code', { class: 'mono' }, un)]), '. Your data on this server stays until you purge it in Privacy.'));
    const list = d.devices.length ? h('div', { class: 'stack' }, d.devices.map((dev, i) => {
      const revoked = dev.revoked > 0, more = h('div'); let shown = false, armed = false;
      const mine = srcs.filter((s) => s.device === dev.id || s.device === dev.name);
      const revokeBtn = h('button', { class: 'btn sm', disabled: revoked ? true : null, onclick: async () => {
        if (!armed) { armed = true; revokeBtn.textContent = 'Confirm revoke'; revokeBtn.classList.add('danger'); setTimeout(() => { armed = false; revokeBtn.textContent = 'Revoke'; revokeBtn.classList.remove('danger'); }, 4000); return; }
        try { await api.post('/api/agent/revoke', { device: dev.id }); toast(`${dev.name || dev.id} can no longer send data`, 'good'); location.reload(); } catch (e) { toast(e.message, 'bad'); } } }, revoked ? 'Revoked' : 'Revoke');
      return h('section', { class: 'card' }, h('header', {}, h('h3', {}, dev.id === 'local' ? 'This computer' : dev.name || dev.id), pill(revoked ? 'Revoked' : dev.id === 'local' ? 'Server' : 'Enrolled', revoked ? '' : 'good')),
        h('p', { class: 'faint' }, `${dev.os || d.envs[i]?.os_label || 'unknown OS'} · id ${dev.id} · last report ${ago(dev.last_seen)} · first seen ${ago(dev.first_seen)}`),
        revoked ? null : journey(dev, d.envs[i], consented, mine),
        dev.id === 'local' ? null : h('div', { class: 'row wrap' }, h('button', { class: 'btn sm', 'aria-expanded': 'false', onclick: (e) => { shown = !shown; e.currentTarget.setAttribute('aria-expanded', String(shown)); more.replaceChildren(shown ? plan(dev) : ''); } }, 'Permissions'), revokeBtn), more);
    })) : h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'No computers yet')), journey(null, null, consented, []), h('p', { class: 'muted' }, 'Download an agent above and run it on the computer you want measured. This page updates as each step completes.'));
    return h('div', { class: 'page' }, h('div', { class: 'page-head' }, h('div', { class: 'grow' }, h('h1', {}, 'Devices'), h('p', {}, 'Computers that report to this Stretto, how far each one is, and what it is allowed to read.'))),
      install, list,
      srcs.length ? h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'Data sources'), h('small', {}, 'what is actually arriving')), h('div', { class: 'tablewrap' }, h('table', { class: 't' },
        h('thead', {}, h('tr', {}, ['Device', 'Source', 'Events', 'Last data'].map((x, i) => h('th', { class: i === 2 ? 'num' : '' }, x)))),
        h('tbody', {}, srcs.map((r) => h('tr', {}, h('td', { 'data-label': 'Device' }, r.device), h('td', { 'data-label': 'Source' }, r.src, r.estimated ? ' ' : '', r.estimated ? pill('Estimated', 'info') : null), h('td', { class: 'num', 'data-label': 'Events' }, String(r.events)), h('td', { 'data-label': 'Last data' }, ago(r.last_ts)))))))) : null);
  },
};
