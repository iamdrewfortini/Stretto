// Talk: the full conversation view of the shared call in js/ui/call.js. This
// page never opens its own socket or mic: the mic streams 16 kHz Int16 PCM
// frames over ws://127.0.0.1:8788/ and text goes to /v1/turn in js/ui/call.js,
// which owns getUserMedia, the AudioWorklet downsampler and speechSynthesis.
// Talk only renders the shared states 'ready' 'partial' 'final' 'reply' and
// 'error', so leaving this page never kills the call.
import { h, s, clear } from '../lib/dom.js';
import { api } from '../lib/api.js';
import { pill } from '../ui/kit.js';
import { call } from '../ui/call.js';
import { toast } from '../ui/toast.js';

const HINTS = ['Log 25 minutes of focus', 'Start a focus timer', 'How’s my day?', 'What’s my leak score?'];

const micIcon = (size = 40) => s('svg', { viewBox: '0 0 24 24', width: size, height: size, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' },
  s('rect', { x: 9, y: 3, width: 6, height: 10, rx: 3 }),
  s('path', { d: 'M6 11a6 6 0 0 0 12 0M12 17v3M9 20h6' }));

export default {
  id: 'talk', key: 'm', dated: false, title: 'Talk', icon: 'swap',
  load: async () => { try { return { vt: await api.get('/api/voice/tree') }; } catch { return { vt: null }; } },
  view(d) {
    const status = pill('Idle');
    const head = h('div', { class: 'page-head' }, h('div', { class: 'grow' }, h('h1', {}, 'Talk'), h('p', {}, 'Speak and Stretto answers, acting where it can. Type when quiet suits.')), status);
    const stateLine = h('p', { class: 'faint talk-state', role: 'status' }, 'Idle — press the mic to speak.');
    const partial = h('p', { class: 'talk-partial', 'aria-live': 'polite' });
    const micBtn = h('button', { class: 'talk-mic', 'aria-pressed': 'false', 'aria-label': 'Start or stop the microphone' }, micIcon(), h('span', { class: 'talk-mic-label' }, 'Mic'));
    const log = h('div', { class: 'talk-log', 'aria-live': 'polite' });
    const input = h('input', { class: 'input grow', type: 'text', placeholder: 'Type instead of speaking', 'aria-label': 'Type instead of speaking' });
    const sendBtn = h('button', { class: 'btn primary' }, 'Send');

    let postedTurns = 0;   // persist finished turns server-side so conversations bucket, embed and recall like everything else
    const persist = (turns) => { for (let i = postedTurns; i < turns.length; i++) { const t = turns[i]; if (t.reply) { postedTurns = i + 1; api.post('/api/turns', { you: t.you || '', reply: t.reply, tools: t.tools || [] }).catch(() => {}); } } };
    const metaLine = (t) => [t.path ? String(t.path) : '', t.ms != null ? `${t.ms} ms` : ''].filter(Boolean).join(' · ');
    const paint = (s) => {
      persist(s.turns || []);
      const live = s.status === 'live' || s.status === 'connecting';
      const label = s.status === 'live' ? (s.muted ? 'Live · muted' : 'Listening') : s.status === 'connecting' ? 'Connecting…' : s.status === 'error' ? 'Error — press the mic to retry' : 'Idle';
      status.textContent = label;
      status.className = `pill${s.status === 'live' ? ' good' : s.status === 'connecting' ? ' warn' : s.status === 'error' ? ' bad' : ''}`.trim();
      stateLine.textContent = label === 'Idle' ? 'Idle — press the mic to speak.' : label;
      partial.textContent = s.partial || '';
      micBtn.classList.toggle('live', live);
      micBtn.setAttribute('aria-pressed', String(live));
      clear(log);
      if (!s.turns.length) log.append(h('p', { class: 'muted' }, 'Nothing said yet — press the mic or send a line below.'));
      for (const t of s.turns) {
        if (t.you) log.append(h('div', { class: 'talk-you' }, h('span', { class: 'talk-who' }, 'You'), h('p', {}, t.you)));
        const toolsLine = (t.tools && t.tools.length) ? h('div', { class: 'row wrap talk-tools' }, t.tools.map((n) => pill(n, 'info'))) : null;
        const meta = metaLine(t);
        log.append(h('div', { class: 'talk-reply' }, h('span', { class: 'talk-who' }, 'Stretto'), h('p', {}, t.reply || '—'),
          toolsLine, meta ? h('small', { class: 'faint num' }, meta) : null));
      }
      log.scrollTop = log.scrollHeight;
    };

    micBtn.addEventListener('click', () => {
      if (call.state.status === 'live' || call.state.status === 'connecting') call.hangup(); else call.start();
    });
    const sendText = (v) => { const q = (v || '').trim(); if (!q) return; input.value = ''; call.send(q); };
    sendBtn.addEventListener('click', () => sendText(input.value));
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendText(input.value); });

    const hints = h('div', { class: 'talk-hints', 'aria-label': 'Example phrases' }, h('span', { class: 'faint' }, 'Try saying'),
      HINTS.map((ph) => h('button', { class: 'chip talk-hint', onclick: () => call.send(ph) }, ph)));
    // Derivable decision tree for today, preloaded with its graph + honeycomb route in one /api/voice/tree call.
    // Walking it is local and instant; a grounded cached reply (preload.grounded_cached) answers with no model call.
    let treeCard = null;
    if (d && d.vt && d.vt.tree) {
      const box = h('div', { class: 'stack' });
      let cur = d.vt.tree.root;
      const walk = () => { const n = d.vt.tree.nodes[cur]; clear(box);
        box.append(h('p', {}, n.say), n.minutes ? pill(`${n.minutes} min · measured`, 'info') : null,
          h('div', { class: 'row wrap' }, n.options.map((o) => h('button', { class: 'btn sm', onclick: () => { if (o.action && o.action.startsWith('act:')) toast(`Act on it: ${o.action.slice(4)} — confirm in Today or Paths`); cur = o.next; walk(); } }, o.label))));
        if (d.vt.preload && d.vt.preload.grounded_cached) box.append(h('small', { class: 'faint' }, 'Grounded cached reply ready — no model call needed.')); };
      walk();
      treeCard = h('section', { class: 'card', 'aria-labelledby': 'vt-h' }, h('header', {}, h('h3', { id: 'vt-h' }, 'Today, as questions'), pill('derived from measured findings', 'info')), box);
    }
    const stage = h('section', { class: 'card hero raised talk-stage' }, micBtn, stateLine, partial, hints);
    const convo = h('section', { class: 'card talk-convo' }, h('header', {}, h('h3', {}, 'Conversation')), log,
      h('div', { class: 'row talk-row' }, input, sendBtn));

    const root = h('div', { class: 'page page-talk quiet' }, head, stage, treeCard, convo);
    paint(call.state);
    const unsub = call.on(paint);
    const gone = new MutationObserver(() => {
      if (document.body.contains(root)) return;
      gone.disconnect(); unsub();   // leaving Talk never kills the shared call
    });
    gone.observe(document.body, { childList: true, subtree: true });
    return root;
  },
};
