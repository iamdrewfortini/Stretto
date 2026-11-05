// Talk: realtime voice and a text fallback. The mic streams 16 kHz Int16 PCM frames
// over the voice socket; replies are spoken aloud and every tool call is shown with its cost in time.
import { h, s, clear } from '../lib/dom.js';
import { pill } from '../lib/kit.js';
import { toast } from '../ui/toast.js';

const WS_URL = 'ws://127.0.0.1:8788/';
const TURN_URL = '/v1/turn';
const HINTS = ['Log 25 minutes of focus', 'Start a focus timer', 'How’s my day?', 'What’s my leak score?'];
const WORKLET = 'class Down extends AudioWorkletProcessor{'
  + 'constructor(){super();this.rem=0;this.out=[];}'
  + 'process(inputs){var ch=inputs[0]&&inputs[0][0];if(ch){'
  + 'var ratio=sampleRate/16000,i,x;for(i=0;i<ch.length;i++){this.rem+=1;'
  + 'if(this.rem>=ratio){this.rem-=ratio;x=Math.max(-1,Math.min(1,ch[i]));'
  + 'this.out.push(Math.round(x<0?x*0x8000:x*0x7FFF));}}'
  + 'while(this.out.length>=640){'
  + 'var frame=this.out.slice(0,640);this.out=this.out.slice(640);'
  + 'var buf=new Int16Array(frame).buffer;this.port.postMessage(buf,[buf]);}}'
  + 'return true;}}registerProcessor("pcm-down",Down);';

const micIcon = (size = 40) => s('svg', { viewBox: '0 0 24 24', width: size, height: size, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' },
  s('rect', { x: 9, y: 3, width: 6, height: 10, rx: 3 }),
  s('path', { d: 'M6 11a6 6 0 0 0 12 0M12 17v3M9 20h6' }));

function speak(text) {
  if (!('speechSynthesis' in window) || !text) return;
  try {
    const u = new SpeechSynthesisUtterance(text);
    const en = speechSynthesis.getVoices().filter((v) => (v.lang || '').toLowerCase().indexOf('en') === 0);
    if (en.length) u.voice = en[0];
    speechSynthesis.speak(u);
  } catch { /* replies still render as text */ }
}

export default {
  id: 'talk', key: 'm', dated: false, title: 'Talk', icon: 'swap',
  load: async () => ({}),
  view() {
    const status = pill('Idle');
    const head = h('div', { class: 'page-head' }, h('div', { class: 'grow' }, h('h1', {}, 'Talk'), h('p', {}, 'Speak and Stretto answers, acting where it can. Type when quiet suits.')), status);
    const stateLine = h('p', { class: 'faint talk-state', role: 'status' }, 'Idle — press the mic to speak.');
    const partial = h('p', { class: 'talk-partial', 'aria-live': 'polite' });
    const micBtn = h('button', { class: 'talk-mic', 'aria-pressed': 'false', 'aria-label': 'Start or stop the microphone' }, micIcon(), h('span', { class: 'talk-mic-label' }, 'Mic'));
    const log = h('div', { class: 'talk-log' }, h('p', { class: 'muted' }, 'Nothing said yet — press the mic or send a line below.'));
    const input = h('input', { class: 'input grow', type: 'text', placeholder: 'Type instead of speaking', 'aria-label': 'Type instead of speaking' });
    const sendBtn = h('button', { class: 'btn primary' }, 'Send');

    let ws = null, stream = null, actx = null, node = null, live = false, said = false;

    const setState = (t, tone = '') => {
      status.textContent = t; status.className = `pill ${tone}`.trim();
      stateLine.textContent = t === 'Idle' ? 'Idle — press the mic to speak.' : t;
    };
    const addFinal = (text) => {
      if (!said) { said = true; clear(log); }
      log.append(h('div', { class: 'talk-you' }, h('span', { class: 'talk-who' }, 'You'), h('p', {}, text)));
      log.scrollTop = log.scrollHeight;
    };
    const addReply = (text, tools, meta) => {
      if (!said) { said = true; clear(log); }
      const toolsLine = (tools && tools.length) ? h('div', { class: 'row wrap talk-tools' }, tools.map((t) => pill(typeof t === 'string' ? t : t.name || 'tool', 'info'))) : null;
      log.append(h('div', { class: 'talk-reply' }, h('span', { class: 'talk-who' }, 'Stretto'), h('p', {}, text || '—'),
        toolsLine, meta ? h('small', { class: 'faint num' }, meta) : null));
      log.scrollTop = log.scrollHeight;
    };

    const onMsg = (ev) => {
      let m; try { m = JSON.parse(ev.data); } catch { return; }
      if (!m || typeof m.type !== 'string') return;
      if (m.type === 'ready') setState('Listening', 'good');
      else if (m.type === 'partial') partial.textContent = m.text || '';
      else if (m.type === 'final') { partial.textContent = ''; addFinal(m.text || ''); }
      else if (m.type === 'reply') { const tools = (m.tools || []).map((t) => (typeof t === 'string' ? t : t.name || 'tool')); addReply(m.text || '', tools, m.ms != null ? `${m.ms} ms` : ''); speak(m.text || ''); setState('Idle'); }
      else if (m.type === 'error') { setState(`Error: ${m.message || 'unknown'}`, 'bad'); toast(m.message || 'Voice error', 'bad'); }
    };
    const openWs = () => new Promise((resolve, reject) => {
      const sock = new WebSocket(WS_URL);
      sock.binaryType = 'arraybuffer';
      sock.onopen = () => { try { sock.send(JSON.stringify({ type: 'start', sample_rate: 16000 })); } catch { /* already closing */ } resolve(sock); };
      sock.onmessage = onMsg;
      sock.onclose = () => { if (live) setState('Disconnected — press the mic to retry', 'bad'); ws = null; };
      sock.onerror = () => { setState('Connection failed — is the voice service up?', 'bad'); reject(new Error('voice socket failed')); };
    });
    const stopTracks = () => {
      if (node) { try { node.disconnect(); } catch { /* already gone */ } node = null; }
      if (actx) { actx.close().catch(() => {}); actx = null; }
      if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
    };
    const startMic = async () => {
      if ('speechSynthesis' in window) speechSynthesis.cancel(); // barge-in: stop TTS
      setState('Connecting…');
      micBtn.classList.add('live'); micBtn.setAttribute('aria-pressed', 'true');
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
        actx = new (window.AudioContext || window.webkitAudioContext)();
        await actx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' })));
        ws = (ws && ws.readyState === 1) ? ws : await openWs();
        live = true;
        node = new AudioWorkletNode(actx, 'pcm-down');
        node.port.onmessage = (e) => { if (ws && ws.readyState === 1) ws.send(e.data); }; // ~40 ms Int16 PCM frames
        actx.createMediaStreamSource(stream).connect(node);
        setState('Listening', 'good');
      } catch (e) { stopTracks(); micBtn.classList.remove('live'); micBtn.setAttribute('aria-pressed', 'false'); setState(`Mic error: ${(e && e.message) || e}`, 'bad'); }
    };
    const stopMic = () => {
      live = false;
      micBtn.classList.remove('live'); micBtn.setAttribute('aria-pressed', 'false');
      try { if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: 'stop' })); } catch { /* socket already gone */ }
      stopTracks();
      setState('Waiting for reply');
    };
    micBtn.addEventListener('click', () => (live ? stopMic() : startMic()));
    if (!('speechSynthesis' in window)) { /* replies still render as text */ }

    const sendText = async (text) => {
      const q = (text || '').trim();
      if (!q) return;
      addFinal(q);
      setState('Thinking…');
      try {
        const res = await fetch(TURN_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: q }) });
        const m = await res.json();
        const tools = (m.tool_calls || []).map((c) => c.name || 'tool');
        const meta = [m.path ? String(m.path) : '', m.ms != null ? `${m.ms} ms` : ''].filter(Boolean).join(' · ');
        addReply(m.reply || '', tools, meta);
        speak(m.reply || '');
      } catch (e) { toast(e.message || 'Turn failed', 'bad'); }
      setState('Idle');
    };
    sendBtn.addEventListener('click', () => { const v = input.value; input.value = ''; sendText(v); });
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { const v = input.value; input.value = ''; sendText(v); } });

    const hints = h('div', { class: 'talk-hints', 'aria-label': 'Example phrases' }, h('span', { class: 'faint' }, 'Try saying'),
      HINTS.map((ph) => h('button', { class: 'chip talk-hint', onclick: () => sendText(ph) }, ph)));
    const stage = h('section', { class: 'card hero raised talk-stage' }, micBtn, stateLine, partial, hints);
    const convo = h('section', { class: 'card talk-convo' }, h('header', {}, h('h3', {}, 'Conversation')), log,
      h('div', { class: 'row talk-row' }, input, sendBtn));

    const root = h('div', { class: 'page page-talk quiet' }, head, stage, convo);
    const gone = new MutationObserver(() => {
      if (document.body.contains(root)) return;
      gone.disconnect(); live = false;
      try { if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: 'stop' })); ws && ws.close(); } catch { /* leaving */ }
      stopTracks();
      if ('speechSynthesis' in window) speechSynthesis.cancel();
    });
    gone.observe(document.body, { childList: true, subtree: true });
    return root;
  },
};
