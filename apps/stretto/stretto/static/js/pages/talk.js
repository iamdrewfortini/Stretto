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

    // Offline state: the voice runtime (socket + /v1/turn) is external. When it does not
    // answer, say exactly what still works, what does not, and the one next step.
    const checkBtn = h('button', { class: 'btn primary', type: 'button', onclick: () => call.probe() }, 'Check again');
    const offlineWhy = h('p', {});
    const offline = h('section', { class: 'card err talk-offline', role: 'alert', 'aria-labelledby': 'talk-off-h', hidden: true },
      h('header', {}, h('h3', { id: 'talk-off-h' }, 'Voice runtime offline'), pill('ws://127.0.0.1:8788/', 'bad')),
      offlineWhy,
      h('ul', {},
        h('li', {}, h('strong', {}, 'Still works: '), d && d.vt && d.vt.tree
          ? '“Today, as questions” below — the decision tree runs locally in this page, no runtime needed. Saved turns stay in Topics & Recall.'
          : 'Saved turns stay in Topics & Recall. (Today’s decision tree did not load either — reload the page once Stretto is up.)'),
        h('li', {}, h('strong', {}, 'Not possible now: '), 'speaking, and typed conversation — typed lines go to the same runtime (/v1/turn), so Send is off. The mic is not opened.'),
        h('li', {}, h('strong', {}, 'Next step: '), 'start the Humanflow voice runtime on this machine so it listens on 127.0.0.1:8788, then press Check again.')),
      h('div', { class: 'row' }, checkBtn));

    let hints = null;   // built below; paint runs only after it exists
    let postedTurns = 0;   // persist finished turns server-side so conversations bucket, embed and recall like everything else
    const persist = (turns) => { for (let i = postedTurns; i < turns.length; i++) { const t = turns[i]; if (t.reply) { postedTurns = i + 1; api.post('/api/turns', { you: t.you || '', reply: t.reply, tools: t.tools || [] }).catch(() => {}); } } };
    const metaLine = (t) => [t.path ? String(t.path) : '', t.ms != null ? `${t.ms} ms` : ''].filter(Boolean).join(' · ');
    const paint = (s) => {
      persist(s.turns || []);
      const live = s.status === 'live' || s.status === 'connecting';
      const down = s.runtime === 'down' && !live;
      const checking = s.runtime === 'checking' && !live;
      const label = down ? 'Voice offline' : checking ? 'Checking voice…'
        : s.status === 'live' ? (s.muted ? 'Live · muted' : 'Listening') : s.status === 'connecting' ? 'Connecting…' : s.status === 'error' ? 'Error — press the mic to retry' : 'Idle';
      status.textContent = label;
      status.className = `pill${s.status === 'live' ? ' good' : (s.status === 'connecting' || checking) ? ' warn' : (s.status === 'error' || down) ? ' bad' : ''}`.trim();
      stateLine.textContent = down ? 'Voice runtime unreachable — the mic stays off. See below.'
        : checking ? 'Checking the voice runtime…' : label === 'Idle' ? 'Idle — press the mic to speak.' : label;
      offline.hidden = !down;
      offlineWhy.textContent = s.status === 'offline' && s.turns.length
        ? 'The call ended because the voice runtime stopped answering. Nothing is listening.'
        : 'Stretto cannot reach the voice runtime, so nothing is listening.';
      checkBtn.disabled = checking;
      checkBtn.textContent = checking ? 'Checking…' : 'Check again';
      micBtn.disabled = down || checking;
      micBtn.setAttribute('aria-label', down ? 'Microphone unavailable — voice runtime offline' : 'Start or stop the microphone');
      micBtn.style.opacity = down ? '0.45' : '';
      micBtn.style.cursor = down ? 'not-allowed' : '';
      input.disabled = sendBtn.disabled = down;
      input.placeholder = down ? 'Typing needs the voice runtime too — offline' : 'Type instead of speaking';
      if (hints) for (const b of hints.querySelectorAll('button')) b.disabled = down;
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
    const sendText = async (v) => { const q = (v || '').trim(); if (!q || call.state.runtime === 'down') return; input.value = ''; if (!(await call.send(q)) && !input.value) input.value = q; };
    sendBtn.addEventListener('click', () => sendText(input.value));
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendText(input.value); });

    hints = h('div', { class: 'talk-hints', 'aria-label': 'Example phrases' }, h('span', { class: 'faint' }, 'Try saying'),
      HINTS.map((ph) => h('button', { class: 'chip talk-hint', onclick: () => call.send(ph) }, ph)));
    // Derivable decision tree for today, preloaded with its graph + honeycomb route in one /api/voice/tree call.
    // Walking it is local and instant; a grounded cached reply (preload.grounded_cached) answers with no model call.
    let treeCard = null;
    if (d && d.vt && d.vt.tree) {
      const box = h('div', { class: 'stack' });
      let cur = d.vt.tree.root;
      const walk = () => { const n = d.vt.tree.nodes[cur]; clear(box);
        box.append(h('p', {}, n.say), ...(n.minutes ? [pill(`${n.minutes} min · measured`, 'info')] : []),
          h('div', { class: 'row wrap' }, n.options.map((o) => h('button', { class: 'btn sm', onclick: () => { if (o.action && o.action.startsWith('act:')) toast(`Act on it: ${o.action.slice(4)} — confirm in Today or Challenges`); cur = o.next; walk(); } }, o.label))));
        if (d.vt.preload && d.vt.preload.grounded_cached) box.append(h('small', { class: 'faint' }, 'Grounded cached reply ready — no model call needed.')); };
      walk();
      treeCard = h('section', { class: 'card', 'aria-labelledby': 'vt-h' }, h('header', {}, h('h3', { id: 'vt-h' }, 'Today, as questions'), pill('derived from measured findings', 'info')), box);
    }
    const stage = h('section', { class: 'card hero raised talk-stage' }, micBtn, stateLine, partial, hints);
    const convo = h('section', { class: 'card talk-convo' }, h('header', {}, h('h3', {}, 'Conversation')), log,
      h('div', { class: 'row talk-row' }, input, sendBtn));

    const root = h('div', { class: 'page page-talk quiet' }, head, offline, stage, treeCard, convo);
    paint(call.state);
    // Know before the first press whether anyone is listening; a live or paused call already answered.
    if (call.state.runtime !== 'up' && !['live', 'connecting', 'paused'].includes(call.state.status)) call.probe();
    const unsub = call.on(paint);
    const gone = new MutationObserver(() => {
      if (document.body.contains(root)) return;
      gone.disconnect(); unsub();   // leaving Talk never kills the shared call
    });
    gone.observe(document.body, { childList: true, subtree: true });
    return root;
  },
};
