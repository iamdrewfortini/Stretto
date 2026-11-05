// Shared voice call: one module-level call for the whole app. The floating
// bar (mountCallBar) and the Talk page both render from `call.state`; the mic,
// AudioWorklet and socket live here so page changes never kill the call.
import { h } from '../lib/dom.js';
import { go, render } from '../lib/router.js';
import { toast } from './toast.js';
import { icon } from './icons.js';

const WS_URL = 'ws://127.0.0.1:8788/';
const TURN_URL = '/v1/turn';
const VOICE_WANT = /(Natural|Neural|Premium|Enhanced|Siri|Samantha|Ava|Allison|Zoe|Google US English|Aria|Jenny)/i;
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

const state = { status: 'idle', muted: false, partial: '', turns: [], speaking: false };
const listeners = new Set();
const emit = () => { for (const fn of [...listeners]) { try { fn(state); } catch { /* a dead view must not kill the call */ } } };
const setState = (patch) => { Object.assign(state, patch); emit(); };

let ws = null, stream = null, actx = null, node = null, analyser = null, raf = 0;
let wantLive = false, retried = false, pendingYou = '', level = 0, voice = null;

function pickVoice() {
  if (!('speechSynthesis' in window)) return;
  const vs = speechSynthesis.getVoices();
  if (!vs.length) return;
  const primary = (navigator.language || 'en').split('-')[0].toLowerCase();
  const norm = (v) => (v.lang || '').toLowerCase().replace('_', '-');
  const inLang = vs.filter((v) => norm(v).startsWith(primary));
  const pool = inLang.length ? inLang : vs.filter((v) => norm(v).startsWith('en'));
  voice = pool.find((v) => VOICE_WANT.test(v.name || ''))
    || pool.filter((v) => v.localService !== false)[0]
    || pool[0]
    || vs.filter((v) => v.localService !== false)[0]
    || vs[0]
    || null;
}
if ('speechSynthesis' in window) { pickVoice(); speechSynthesis.onvoiceschanged = pickVoice; }

function speak(text) {
  if (!('speechSynthesis' in window) || !text || state.muted) return;
  try {
    if (!voice) pickVoice();
    const parts = String(text).match(/[^.!?]+[.!?]+["']?\s*|[^.!?]+$/g) || [text];
    for (const part of parts) {
      const p = part.trim();
      if (!p) continue;
      const u = new SpeechSynthesisUtterance(p);
      if (voice) u.voice = voice;
      u.rate = 1.03; u.pitch = 1.0;
      u.onstart = () => setState({ speaking: true });
      u.onend = u.onerror = () => { if (!speechSynthesis.speaking) setState({ speaking: false }); };
      speechSynthesis.speak(u);
    }
  } catch { /* replies still render as text */ }
}

function runAction(a) {
  if (!a) return;
  if (a.action === 'navigate' && a.page) go(a.page);
  else if (a.action === 'refresh') render();
}

function pushReply({ you, text, tools, ms, path }) {
  const names = (tools || []).map((t) => (typeof t === 'string' ? t : t.name || 'tool'));
  state.turns.push({ you: you || '', reply: text || '', tools: names, ms: ms ?? null, path: path ? String(path) : '' });
  setState({ partial: '' });
  speak(text || '');
}

function onSocketMsg(ev) {
  let m;
  try { m = JSON.parse(ev.data); } catch { return; }
  if (!m || typeof m.type !== 'string') return;
  if (m.type === 'ready') setState({ status: 'live' });
  else if (m.type === 'partial') {
    if ('speechSynthesis' in window && speechSynthesis.speaking) {
      try { speechSynthesis.cancel(); } catch { /* already stopped */ }   // barge-in
      setState({ speaking: false });
    }
    setState({ partial: m.text || '' });
  } else if (m.type === 'final') { pendingYou = m.text || ''; setState({ partial: '' }); }
  else if (m.type === 'reply') {
    const you = pendingYou; pendingYou = '';
    pushReply({ you, text: m.text, tools: m.tools, ms: m.ms, path: m.path });
    (m.actions || []).forEach(runAction);
  } else if (m.type === 'action') runAction(m);
  else if (m.type === 'error') { setState({ status: 'error' }); toast(m.message || 'Voice error', 'bad'); }
}

function openSocket() {
  return new Promise((resolve, reject) => {
    let sock;
    try { sock = new WebSocket(WS_URL); } catch (e) { reject(e); return; }
    sock.binaryType = 'arraybuffer';
    sock.onopen = () => { try { sock.send(JSON.stringify({ type: 'start', sample_rate: 16000 })); } catch { /* already closing */ } resolve(sock); };
    sock.onmessage = onSocketMsg;
    sock.onerror = () => reject(new Error('voice socket failed'));
    sock.onclose = () => {
      if (sock !== ws) return;
      ws = null;
      if (!wantLive) return;
      if (!retried) {
        retried = true;
        openSocket().then((s) => { ws = s; }).catch(() => { wantLive = false; stopAudio(); setState({ status: 'error' }); });
      } else { wantLive = false; stopAudio(); setState({ status: 'error' }); }
    };
  });
}

function stopAudio() {
  cancelAnimationFrame(raf); raf = 0; analyser = null; level = 0;
  if (node) { try { node.disconnect(); } catch { /* already gone */ } node = null; }
  if (actx) { actx.close().catch(() => {}); actx = null; }
  if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
}

let levelBar = null;
function tickLevel() {
  if (!raf || !analyser || !levelBar) return;
  const buf = new Uint8Array(analyser.fftSize);
  analyser.getByteTimeDomainData(buf);
  let sum = 0;
  for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
  const rms = Math.sqrt(sum / buf.length);
  const target = state.muted ? 0 : Math.min(1, rms * 3);
  level = level * 0.7 + target * 0.3;
  levelBar.style.setProperty('--lvl', level.toFixed(3));
  raf = requestAnimationFrame(tickLevel);
}

async function start() {
  if (state.status === 'connecting' || state.status === 'live') return;
  if ('speechSynthesis' in window) { try { speechSynthesis.cancel(); } catch { /* idle */ } }
  setState({ status: 'connecting', speaking: false });
  retried = false; wantLive = true;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    actx = new (window.AudioContext || window.webkitAudioContext)();
    await actx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' })));
    ws = await openSocket();
    const src = actx.createMediaStreamSource(stream);
    analyser = actx.createAnalyser(); analyser.fftSize = 512;
    src.connect(analyser);
    node = new AudioWorkletNode(actx, 'pcm-down');
    node.port.onmessage = (e) => {
      if (!ws || ws.readyState !== 1) return;
      if (state.muted) ws.send(new ArrayBuffer(e.data.byteLength));   // silence keeps the session open
      else ws.send(e.data);   // ~40 ms Int16 PCM frames
    };
    src.connect(node);
    if (levelBar && !raf) raf = requestAnimationFrame(tickLevel);
    setState({ status: 'live' });
  } catch (e) {
    wantLive = false;
    if (ws) { try { ws.close(); } catch { /* already gone */ } ws = null; }
    stopAudio();
    setState({ status: 'error' });
    toast((e && e.message) || 'Could not start the call', 'bad');
  }
}

function hangup() {
  wantLive = false;
  try { if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: 'stop' })); } catch { /* socket already gone */ }
  try { if (ws) ws.close(); } catch { /* already gone */ }
  ws = null;
  stopAudio();
  if ('speechSynthesis' in window) { try { speechSynthesis.cancel(); } catch { /* idle */ } }
  setState({ status: 'idle', partial: '', speaking: false });
}

function mute(on) {
  const v = on === undefined ? !state.muted : !!on;
  if (v && 'speechSynthesis' in window) { try { speechSynthesis.cancel(); } catch { /* idle */ } }
  setState({ muted: v, speaking: v ? false : state.speaking });
}

async function send(text) {
  const q = (text || '').trim();
  if (!q) return;
  try {
    const res = await fetch(TURN_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: q }) });
    const m = await res.json();
    pushReply({ you: q, text: m.reply, tools: (m.tool_calls || []).map((c) => c.name || 'tool'), ms: m.ms, path: m.path });
    (m.actions || []).forEach(runAction);
  } catch (e) { toast((e && e.message) || 'Turn failed', 'bad'); }
}

export const call = {
  state,
  start,
  hangup,
  mute,
  send,
  on(fn) { listeners.add(fn); return () => { listeners.delete(fn); }; },
};

export function mountCallBar(parent) {
  const host = parent || document.body;
  const dot = h('i', { class: 'call-dot', 'aria-hidden': 'true' });
  const linePartial = h('div', { class: 'call-line trunc' });
  const lineReply = h('div', { class: 'call-reply trunc', 'aria-live': 'polite' });
  const fab = h('button', { class: 'call-fab', 'aria-label': 'Call Stretto' }, icon('play', 18), h('span', {}, 'Call Stretto'));
  const muteBtn = h('button', { class: 'btn sm call-mute', 'aria-pressed': 'false' }, 'Mute');
  const hangBtn = h('button', { class: 'icon-btn call-hang', 'aria-label': 'Hang up' }, icon('x'));
  const expandBtn = h('button', { class: 'icon-btn', 'aria-label': 'Open the Talk page' }, icon('swap'));
  const liveWrap = h('div', { class: 'call-live', hidden: true }, dot,
    h('div', { class: 'call-text' }, linePartial, lineReply),
    muteBtn, hangBtn, expandBtn);
  const bar = h('div', { class: 'call-bar', role: 'region', 'aria-label': 'Stretto call', 'data-status': 'idle' }, fab, liveWrap);
  levelBar = bar;

  const paint = (s) => {
    const live = s.status === 'live' || s.status === 'connecting';
    bar.dataset.status = s.status;
    fab.hidden = live; liveWrap.hidden = !live;
    muteBtn.textContent = s.muted ? 'Unmute' : 'Mute';
    muteBtn.setAttribute('aria-pressed', String(s.muted));
    linePartial.textContent = s.status === 'connecting' ? 'Connecting…'
      : s.muted ? 'Muted — tap Unmute to speak'
      : s.partial || (s.status === 'live' ? 'Listening…' : '');
    const last = s.turns.length ? s.turns[s.turns.length - 1].reply : '';
    lineReply.textContent = last || (s.status === 'error' ? 'Call failed — tap the mic in Talk to retry' : '');
  };
  fab.addEventListener('click', () => start());
  muteBtn.addEventListener('click', () => mute());
  hangBtn.addEventListener('click', () => hangup());
  expandBtn.addEventListener('click', () => go('talk'));
  addEventListener('keydown', (e) => {
    if (e.key !== 'c' || e.metaKey || e.ctrlKey || e.altKey) return;
    const t = e.target && e.target.tagName;
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(t) || (e.target && e.target.isContentEditable)) return;
    if (state.status === 'live' || state.status === 'connecting') hangup(); else start();
  });
  paint(state);
  call.on(paint);
  host.append(bar);
  return bar;
}
