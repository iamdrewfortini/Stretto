// Shared voice call: one module-level call for the whole app. The floating
// orb (mountCallBar) and the Talk page both render from `call.state`; the mic,
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

// Silence auto-pause: seconds of no speech before the socket sleeps.
const PAUSE_KEY = 'stretto.call.pauseAfter';
function pauseAfterS() {
  try {
    const v = parseFloat(localStorage.getItem(PAUSE_KEY));
    if (Number.isFinite(v) && v > 0) return v;
  } catch { /* storage unavailable: fall through to the default */ }
  return 20;
}
// 500 ms of 16 kHz 16-bit PCM kept so resume never clips the first word.
const RING_BYTES = 16000 * 2 * 0.5;

const state = { status: 'idle', muted: false, partial: '', turns: [], speaking: false };
const listeners = new Set();
const emit = () => { for (const fn of [...listeners]) { try { fn(state); } catch { /* a dead view must not kill the call */ } } };
const setState = (patch) => { Object.assign(state, patch); emit(); };

let ws = null, stream = null, actx = null, node = null, analyser = null, raf = 0;
let wantLive = false, retried = false, pendingYou = '', level = 0, voice = null;
// Auto-pause bookkeeping: thinking mirrors the server's turn, the noise floor
// adapts to the room, and ring holds the last 500 ms of PCM for resume.
let thinking = false, noiseFloor = 0.02, lastSpeechAt = 0, speechStartAt = 0;
let ring = [], ringBytes = 0;

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

function wakeAudio() {
  if (actx && actx.state === 'suspended') actx.resume().catch(() => {});
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
    lastSpeechAt = performance.now();
    setState({ partial: m.text || '' });
  } else if (m.type === 'final') { pendingYou = m.text || ''; lastSpeechAt = performance.now(); thinking = true; setState({ partial: '' }); }
  else if (m.type === 'thinking') { lastSpeechAt = performance.now(); thinking = true; emit(); }
  else if (m.type === 'reply') {
    const you = pendingYou; pendingYou = '';
    thinking = false;
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
  ring = []; ringBytes = 0; speechStartAt = 0;
}

// RMS of one 16-bit PCM frame; drives the orb glow and the speech detector.
function frameRms(buf) {
  const v = new Int16Array(buf);
  if (!v.length) return 0;
  let sum = 0;
  for (let i = 0; i < v.length; i++) { const x = v[i] / 32768; sum += x * x; }
  return Math.sqrt(sum / v.length);
}

// Every PCM frame (~40 ms) passes here, live or paused: the ring always holds
// the last 500 ms, speech is always measured, but nothing is sent while paused.
function onFrame(buf) {
  const bytes = buf.byteLength || 0;
  ring.push(buf); ringBytes += bytes;
  while (ring.length > 1 && ringBytes > RING_BYTES) ringBytes -= (ring.shift().byteLength || 0);

  const now = performance.now();
  if (!state.muted) {
    const rms = frameRms(buf);
    noiseFloor += (Math.min(rms, 0.3) - noiseFloor) * 0.01;   // slow room adaptation
    const speech = rms > Math.max(noiseFloor * 3, 0.015);
    if (speech) {
      lastSpeechAt = now;
      if (state.status === 'paused') {
        if (!speechStartAt) speechStartAt = now;
        else if (now - speechStartAt >= 250) { speechStartAt = 0; resume(); return; }
      }
    } else if (state.status === 'paused') speechStartAt = 0;
  }
  if (state.status === 'live' && ws && ws.readyState === 1) {
    if (state.muted) ws.send(new ArrayBuffer(bytes));   // silence keeps the session open
    else ws.send(buf);
  } else if (state.status === 'live' && !state.speaking && !thinking
    && now - lastSpeechAt > pauseAfterS() * 1000) {
    autoPause();
  }
}

function autoPause() {
  thinking = false;
  try { if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: 'stop' })); } catch { /* socket already gone */ }
  const s = ws; ws = null;   // null first so onclose treats it as ours and stays quiet
  try { if (s) s.close(); } catch { /* already gone */ }
  setState({ status: 'paused', speaking: false });
}

async function resume() {
  if (state.status !== 'paused') return;
  setState({ status: 'connecting' });
  wakeAudio();
  try {
    const s = await openSocket();
    if (state.status !== 'connecting') { try { s.close(); } catch { /* superseded */ } return; }
    ws = s;
    for (const buf of ring) { try { if (ws.readyState === 1) ws.send(buf); } catch { break; } }
    lastSpeechAt = performance.now();
    setState({ status: 'live' });
  } catch {
    if (state.status === 'connecting') setState({ status: 'paused' });
    toast('Could not resume the call', 'bad');
  }
}

let orbEl = null;
function tickLevel() {
  if (!raf || !analyser || !orbEl) return;
  const buf = new Uint8Array(analyser.fftSize);
  analyser.getByteTimeDomainData(buf);
  let sum = 0;
  for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
  const rms = Math.sqrt(sum / buf.length);
  const target = state.muted ? 0 : Math.min(1, rms * 3);
  level = level * 0.7 + target * 0.3;
  orbEl.style.setProperty('--lvl', level.toFixed(3));
  raf = requestAnimationFrame(tickLevel);
}

async function start() {
  if (state.status === 'connecting' || state.status === 'live') return;
  if (state.status === 'paused') { resume(); return; }
  if ('speechSynthesis' in window) { try { speechSynthesis.cancel(); } catch { /* idle */ } }
  setState({ status: 'connecting', speaking: false });
  retried = false; wantLive = true; thinking = false;
  noiseFloor = 0.02; lastSpeechAt = performance.now(); speechStartAt = 0; ring = []; ringBytes = 0;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    actx = new (window.AudioContext || window.webkitAudioContext)();
    await actx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' })));
    ws = await openSocket();
    const src = actx.createMediaStreamSource(stream);
    analyser = actx.createAnalyser(); analyser.fftSize = 512;
    src.connect(analyser);
    node = new AudioWorkletNode(actx, 'pcm-down');
    node.port.onmessage = (e) => { if (e && e.data) onFrame(e.data); };
    src.connect(node);
    if (orbEl && !raf) raf = requestAnimationFrame(tickLevel);
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
  wantLive = false; thinking = false;
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
  if (v) { ring = []; ringBytes = 0; }
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

// The orb's visual state: the socket status plus thinking/speaking overlays.
function orbState(s) {
  if (s.status === 'error') return 'error';
  if (s.status === 'paused') return 'paused';
  if (s.status === 'connecting') return 'connecting';
  if (s.status === 'idle') return 'idle';
  if (s.speaking) return 'speaking';
  if (thinking) return 'thinking';
  return 'listening';
}

const ORB_LABEL = {
  idle: 'Call Stretto', connecting: 'Connecting…', listening: 'Hang up',
  thinking: 'Hang up', speaking: 'Hang up', paused: 'Resume call', error: 'Call failed — try again',
};

export function mountCallBar(parent) {
  const host = parent || document.body;
  const glyph = h('span', { class: 'call-glyph', 'aria-hidden': 'true' });
  const pauseBars = h('span', { class: 'call-pause', 'aria-hidden': 'true' }, h('i'), h('i'));
  const orb = h('button', { class: 'call-orb', type: 'button', 'aria-label': 'Call Stretto' }, glyph, pauseBars);
  const tip = h('div', { class: 'call-tip', role: 'status', hidden: true });
  const expand = h('button', { class: 'call-expand', type: 'button', 'aria-label': 'Open the Talk page' }, icon('swap', 14), h('span', {}, 'Talk'));
  const bar = h('div', { class: 'call-bar', role: 'region', 'aria-label': 'Stretto call', 'data-state': 'idle' }, tip, orb, expand);
  orbEl = orb;

  let tipFor = '', tipTimer = 0;
  const paint = (s) => {
    const st = orbState(s);
    bar.dataset.state = st;
    orb.setAttribute('aria-label', ORB_LABEL[st] || 'Call Stretto');
    orb.setAttribute('aria-pressed', String(st === 'listening' || st === 'thinking' || st === 'speaking'));
    if (glyph.childNodes.length) glyph.replaceChildren();
    glyph.append(icon(st === 'idle' || st === 'error' ? 'play' : 'stop', 20));
    const last = s.turns.length ? s.turns[s.turns.length - 1].reply : '';
    if (last && last !== tipFor) {
      tipFor = last;
      tip.textContent = last;
      tip.hidden = false;
      clearTimeout(tipTimer);
      tipTimer = setTimeout(() => { tip.hidden = true; }, 6000);
    } else if (!last) { tip.hidden = true; tipFor = ''; }
  };
  const toggle = () => {
    wakeAudio();
    if (state.status === 'live' || state.status === 'connecting') hangup();
    else start();   // idle and error dial; paused resumes via start()
  };
  orb.addEventListener('click', toggle);
  expand.addEventListener('click', () => go('talk'));
  addEventListener('keydown', (e) => {
    if (e.key !== 'c' || e.metaKey || e.ctrlKey || e.altKey) return;
    const t = e.target && e.target.tagName;
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(t) || (e.target && e.target.isContentEditable)) return;
    toggle();
  });
  // Background tabs never stop the call; just revive a suspended AudioContext.
  document.addEventListener('visibilitychange', () => { if (!document.hidden) wakeAudio(); });
  document.addEventListener('click', () => wakeAudio(), true);
  paint(state);
  call.on(paint);
  host.append(bar);
  return bar;
}
