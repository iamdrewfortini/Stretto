import { h, clear } from './lib/dom.js';
import { state } from './lib/state.js';
import { iso, shiftDay, nice } from './lib/fmt.js';
import { route, start, page, query, go, patch, render } from './lib/router.js';
import { icon, logo } from './ui/icons.js';
import { toast } from './ui/toast.js';
import { palette } from './ui/palette.js';
import { skeleton, errorState, roll } from './ui/kit.js';
import talk from './pages/talk.js';
import today from './pages/today.js';
import paths from './pages/paths.js';
import focus from './pages/focus.js';
import tasks from './pages/tasks.js';
import reports from './pages/reports.js';
import insights from './pages/insights.js';
import leaks from './pages/leaks.js';
import privacy from './pages/privacy.js';
import devices from './pages/devices.js';
import habits from './pages/habits.js';
import calendar from './pages/calendar.js';
import goals from './pages/goals.js';
import settings from './pages/settings.js';
import { mountCallBar } from './ui/call.js';
import { guideBar, paintGuide, markSeen } from './ui/guide.js';
import { mode } from './lib/mode.js';
import { stream } from './lib/events.js';
import { dur } from './lib/fmt.js';

const PAGES = [talk, today, focus, tasks, calendar, paths, reports, goals, habits, insights, leaks, privacy, devices, settings];
const SECONDARY = new Set(['goals', 'habits', 'insights', 'leaks', 'privacy', 'devices', 'settings']);
const today_iso = () => iso(new Date());
const cache = new Map();                 // cache, then revalidate: show the last data at once, refresh behind it
let datePicker = null, liveTimer = null, lastOk = 0, online = true, seq = 0;

function applyTheme() {
  const t = state.get('theme', 'system');
  document.documentElement.dataset.theme = t === 'system' ? (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark') : t;
}
applyTheme(); matchMedia('(prefers-color-scheme: light)').addEventListener?.('change', applyTheme);

const ctx = () => { const d = query('d', today_iso()); return { date: d, isToday: d === today_iso() }; };
const live = h('span', { class: 'live', role: 'status', 'aria-live': 'polite' });
const main = h('main', { id: 'main', class: 'main', tabindex: '-1' });
const dateLabel = h('span', { class: 'nowrap', style: { minWidth: '9ch', textAlign: 'center' } });

function setLive() {
  const age = lastOk ? Math.max(0, Math.round((Date.now() - lastOk) / 1000)) : 0;
  live.className = `live${online ? '' : ' off'}`;
  live.textContent = !online ? 'Offline — showing saved data' : !lastOk ? 'Connecting…' : ctx().isToday ? `Live · updated ${age < 5 ? 'just now' : age + ' s ago'}` : `Updated ${age < 5 ? 'just now' : age + ' s ago'}`;
}
setInterval(setLive, 1000);

// Swap the page with a cross-fade (View Transitions where available); the old view is never torn down mid-frame.
const RM = matchMedia('(prefers-reduced-motion: reduce)');
function swap(build) {
  const put = () => { const v = build(); clear(main).append(v); };
  if (document.startViewTransition && !RM.matches && main.firstChild) { const vt = document.startViewTransition(put); [vt.ready, vt.finished, vt.updateCallbackDone].forEach((p) => p.catch(() => {})); }   // a newer swap aborts the older transition; that is not an error
  else put();
}

// Ramped load bar: eased 0→85% while data is in flight, 100% on arrival, then out. One signal, always in the same place.
const loadbar = h('div', { class: 'loadbar', role: 'progressbar', 'aria-label': 'Loading', 'aria-valuemin': '0', 'aria-valuemax': '100', hidden: true }, h('i', {}), h('span', { class: 'num' }, '0%'));
let rampT = 0, rampV = 0;
function loadStart() { if (RM.matches) return; clearInterval(rampT); rampV = 0; loadbar.hidden = false; loadbar.setAttribute('aria-valuenow', '0');
  const t0 = Date.now(); rampT = setInterval(() => { const k = Math.min(1, (Date.now() - t0) / 900); rampV = Math.round(85 * (1 - Math.pow(1 - k, 3))); paintRamp(); if (k >= 1) clearInterval(rampT); }, 50); }
function paintRamp() { loadbar.firstChild.style.setProperty('--f', String(rampV / 100)); loadbar.lastChild.textContent = `${rampV}%`; loadbar.setAttribute('aria-valuenow', String(rampV)); }
function loadDone(ms) { clearInterval(rampT); rampV = 100; paintRamp(); live.title = `Last load ${ms} ms`; setTimeout(() => { loadbar.hidden = true; }, 220); }

async function show(silent = false) {
  const my = ++seq, p = PAGES.find((x) => x.id === page()), c = ctx(), key = `${p.id}|${c.date}`;
  const tLoad = performance.now(); if (!silent && !cache.has(key)) loadStart();
  document.title = `${p.title} · Stretto`;
  document.querySelectorAll('.nav a').forEach((a) => (a.getAttribute('href') === `#/${p.id}${location.hash.includes('?') ? '' : ''}` || a.dataset.id === p.id ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current')));
  dateLabel.textContent = c.isToday ? 'Today' : nice(c.date).split(',').slice(-1)[0].trim();
  datePicker.hidden = !p.dated;
  if (cache.has(key) && !silent) swap(() => p.view(cache.get(key).data, c)); else if (!silent) clear(main).append(skeleton());
  try {
    const data = await p.load(c);
    if (my !== seq) return;
    loadDone(Math.round(performance.now() - tLoad));
    online = true; lastOk = Date.now(); setLive();
    const prev = cache.get(key);
    cache.set(key, { data });
    markSeen(p.id); if (mode.timer) markSeen('focus-started');
    paintGuide(p.id).catch(() => {});
    if (!prev || JSON.stringify(prev.data) !== JSON.stringify(data)) {   // update in place only when something changed
      const y = scrollY; swap(() => { const v = p.view(data, c); if (silent || prev) v.classList.add('quiet'); return v; }); if (silent) scrollTo(0, y);
    }
  } catch (e) {
    if (my !== seq) return;
    loadDone(Math.round(performance.now() - tLoad));
    online = !(e instanceof TypeError); setLive();
    if (!cache.has(key)) clear(main).append(errorState(online ? e.message : 'Stretto can’t reach its local service. Is it still running?', () => show()));
  }
}
PAGES.forEach((p) => route(p.id, () => show()));
addEventListener('hashchange', () => { clearInterval(liveTimer); liveTimer = setInterval(() => { if (ctx().isToday && !document.hidden && !stream.live) show(true); }, 15000); });
// Live: the server pushes closing blocks and the day summary; polling above only runs while the stream is down.
stream.open(); let streamT = 0; stream.on((ev) => { if (ev === 'hello') return; if (ctx().isToday && !document.hidden) { clearTimeout(streamT); streamT = setTimeout(() => show(true), 400); } });
addEventListener('online', () => { online = true; show(true); }); addEventListener('offline', () => { online = false; setLive(); });

const step = (n) => { const d = shiftDay(ctx().date, n); if (d > today_iso()) return; patch({ d: d === today_iso() ? '' : d }); };
// Start early: hovering a destination fetches its data before the click (R16)
const prefetch = (p) => { const c = ctx(), key = `${p.id}|${c.date}`; if (cache.has(key)) return; p.load(c).then((data) => { if (!cache.has(key)) cache.set(key, { data }); }).catch(() => {}); };
const navLink = (p) => h('a', { href: `#/${p.id}`, 'data-id': p.id, class: SECONDARY.has(p.id) ? 'sec' : null, onpointerenter: () => prefetch(p) }, icon(p.icon), h('span', {}, p.title), h('kbd', {}, `g ${p.key}`));
const nav = h('nav', { class: 'nav', 'aria-label': 'Main' }, PAGES.filter((p) => !SECONDARY.has(p.id)).map(navLink), h('div', { class: 'nav-sep', role: 'presentation' }), PAGES.filter((p) => SECONDARY.has(p.id)).map(navLink));
const themeBtn = h('button', { class: 'icon-btn', 'aria-label': 'Toggle light and dark theme', onclick: () => { const cur = document.documentElement.dataset.theme; state.set('theme', cur === 'dark' ? 'light' : 'dark'); applyTheme(); } }, icon('moon'));
const DETAIL = { calendar: 'month of goal rings, the day’s schedule', goals: 'daily and weekly goals, budgets, level', today: 'tightness, attention, the day’s wave', focus: 'timer, ring, up next', tasks: 'list and board', paths: 'routes between apps', reports: 'trend, heat, goal calendar', habits: 'small daily practices', insights: 'inferred suggestions', leaks: 'leak score, compounding, ranked changes', talk: 'realtime voice', privacy: 'notices and consent', devices: 'computers that report here', settings: 'goal, theme, rules' };
const cmds = () => [...PAGES.map((p) => ({ group: 'Pages', label: p.title, detail: DETAIL[p.id] || '', keys: ['G', p.key.toUpperCase()], run: () => go(p.id, { d: query('d', '') }) })),
  { group: 'Day', label: 'Previous day', keys: ['['], run: () => step(-1) }, { group: 'Day', label: 'Next day', keys: [']'], run: () => step(1) }, { group: 'Day', label: 'Jump to today', run: () => patch({ d: '' }) },
  { group: 'Actions', label: 'Start focus · 25 min', detail: 'a block on the current task', run: () => go('focus', { d: '' }) }, { group: 'Actions', label: 'Toggle theme', run: () => themeBtn.click() },
  { group: 'Actions', label: 'Load a simulated day', detail: 'demo data', run: async () => { const { api } = await import('./lib/api.js'); const r = await api.post('/api/demo/seed'); toast('Loaded a simulated day', 'good'); patch({ d: r.date }); } }];

// Predictive preload: on idle, warm the likely-next pages in nav order, then the adjacent days of dated pages.
// Prediction is nav order + yesterday/tomorrow — the two moves the date picker makes cheapest to want next.
const idle = window.requestIdleCallback || ((f) => setTimeout(f, 600));
idle(() => { const cur = page(); const ordered = [...PAGES.slice(PAGES.findIndex((p) => p.id === cur) + 1), ...PAGES.slice(0, PAGES.findIndex((p) => p.id === cur))];
  ordered.forEach((p, i) => setTimeout(() => prefetch(p), i * 250));
  const c = ctx(); PAGES.filter((p) => p.dated).forEach((p, i) => [-1, 1].forEach((n, j) => setTimeout(() => { const d2 = shiftDay(c.date, n); if (d2 > today_iso()) return; const k2 = `${p.id}|${d2}`; if (cache.has(k2)) return; p.load({ date: d2, isToday: d2 === today_iso() }).then((data) => { if (!cache.has(k2)) cache.set(k2, { data }); }).catch(() => {}); }, 1200 + (i * 2 + j) * 250))); });

// Running session: a pill on every page while a timer runs (the live state of the whole app)
const session = h('a', { class: 'session', href: '#/focus', hidden: true });
function paintSession() {
  const t = mode.timer; session.hidden = !t; if (!t) return;
  const el = Math.max(0, Date.now() / 1000 - t.start);
  const txt = `${Math.floor(el / 60)}:${String(Math.floor(el % 60)).padStart(2, '0')}`;
  if (session.dataset.k !== t.kind + t.start) { session.dataset.k = t.kind + t.start; session.replaceChildren(h('i', { class: 'session-dot' }), h('b', {}, t.kind === 'break' ? 'Break' : 'Focus'), h('span', { class: 'num session-time' }), t.label && t.kind !== 'break' && t.label.toLowerCase() !== 'focus' ? h('span', { class: 'trunc session-label' }, t.label) : null); }
  roll(session.querySelector('.session-time'), txt);
}
mode.on(paintSession); setInterval(paintSession, 1000); mode.refresh();

const shell = h('div', { class: 'shell' },
  h('a', { class: 'skip', href: '#main', onclick: (e) => { e.preventDefault(); main.focus(); } }, 'Skip to content'),
  h('aside', { class: 'side' }, h('div', { class: 'brand' }, logo(32), h('div', {}, h('b', {}, 'Stretto'), h('small', {}, 'time, tightened'))), nav,
    h('div', { class: 'side-foot' }, h('button', { class: 'btn', onclick: () => palette(cmds()) }, icon('search', 16), 'Command', h('kbd', {}, '⌘K')))),
  h('header', { class: 'top' }, session, datePicker = h('div', { class: 'row' }, h('button', { class: 'icon-btn', 'aria-label': 'Previous day', onclick: () => step(-1) }, icon('left')), dateLabel,
    h('button', { class: 'icon-btn', 'aria-label': 'Next day', onclick: () => step(1) }, icon('right'))), h('div', { class: 'grow' }), live, themeBtn),
  main);
clear(document.getElementById('app')).append(loadbar, shell, guideBar); document.getElementById('app').classList.remove('boot');
mountCallBar(shell);   // the floating call pill lives in the shell, outside the page container

let g = 0;
addEventListener('keydown', (e) => {
  const t = e.target.tagName; if (['INPUT', 'TEXTAREA', 'SELECT'].includes(t) || e.altKey) return;
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); palette(cmds()); return; }
  if (e.metaKey || e.ctrlKey) return;
  if (g && Date.now() - g < 900) { const p = PAGES.find((x) => x.key === e.key); g = 0; if (p) go(p.id, { d: query('d', '') }); return; }
  if (e.key === 'g') g = Date.now(); else if (e.key === '[') step(-1); else if (e.key === ']') step(1); else if (e.key === '?') toast('g then m t f k c p r · o h i l v d s: go to a page · [ and ]: change day · ⌘K: commands');
});
// Touch response: pressed on touch-down, released with a spring; a drag past the slop cancels the press (it was a scroll).
const PRESS = '.btn, .icon-btn, .nav a, .finding, .palette li';
let pressed = null, px = 0, py = 0;
addEventListener('pointerdown', (e) => { const t = e.target.closest(PRESS); if (!t || t.disabled) return; pressed = t; px = e.clientX; py = e.clientY;
  const r = t.getBoundingClientRect(), ds = Math.min(.07, Math.max(.015, .05 * Math.sqrt(44 / Math.max(1, Math.sqrt(r.width * r.height)))));   // small targets squish more (R07)
  t.style.setProperty('--press', (1 - ds).toFixed(3)); t.setAttribute('data-pressed', ''); }, { passive: true });
const release = () => { if (pressed) { pressed.removeAttribute('data-pressed'); pressed = null; } };
addEventListener('pointermove', (e) => { if (pressed && Math.hypot(e.clientX - px, e.clientY - py) > 10) release(); }, { passive: true });
['pointerup', 'pointercancel', 'blur'].forEach((ev) => addEventListener(ev, release, { passive: true }));

// Hero glare follows the pointer while it is over the card, then resumes its slow pass (R06).
addEventListener('pointermove', (e) => { const c = e.target.closest?.('.card.hero'); if (!c) return; const r = c.getBoundingClientRect(); c.dataset.glare = ''; c.style.setProperty('--gx', `${Math.round((1 - (e.clientX - r.left) / r.width) * 200 - 50)}%`); }, { passive: true });
addEventListener('pointerout', (e) => { const c = e.target.closest?.('.card.hero'); if (c && !c.contains(e.relatedTarget)) { delete c.dataset.glare; c.style.removeProperty('--gx'); } }, { passive: true });
// Swipe between days on touch screens: the page follows the finger 1:1, rubber-bands past today, and commits past 25% of the width or on a fast flick.
const band = (x, d) => (1 - 1 / ((Math.abs(x) * 0.55) / d + 1)) * d * Math.sign(x);
let sw = null;
main.style.touchAction = 'pan-y';
main.addEventListener('pointerdown', (e) => { if (e.pointerType !== 'touch' || e.target.closest('input, textarea, .flow, canvas, table')) return; sw = { x: e.clientX, y: e.clientY, t: e.timeStamp, dx: 0, lock: null, hist: [] }; }, { passive: true });
main.addEventListener('pointermove', (e) => {
  if (!sw) return; const dx = e.clientX - sw.x, dy = e.clientY - sw.y;
  if (!sw.lock && Math.hypot(dx, dy) > 10) sw.lock = Math.abs(dx) > Math.abs(dy) * 1.2 ? 'x' : 'y';
  if (sw.lock !== 'x') return;
  const atToday = ctx().isToday && dx < 0, w = main.clientWidth;
  sw.dx = atToday ? band(dx, w) : dx; sw.hist.push([e.timeStamp, e.clientX]); if (sw.hist.length > 6) sw.hist.shift();
  main.style.transition = 'none'; main.style.transform = `translateX(${sw.dx}px)`; main.style.opacity = String(1 - Math.min(0.35, Math.abs(sw.dx) / w));
}, { passive: true });
const endSwipe = () => {
  if (!sw) return; const s0 = sw; sw = null; if (s0.lock !== 'x') return;
  const h = s0.hist, v = h.length > 1 ? (h[h.length - 1][1] - h[0][1]) / Math.max(1, h[h.length - 1][0] - h[0][0]) : 0;   // px per ms over the last few samples
  const w = main.clientWidth, go = !(ctx().isToday && s0.dx < 0) && (Math.abs(s0.dx) > w * 0.25 || Math.abs(v) > 0.6);
  main.style.transition = 'transform var(--d-spring) var(--spring), opacity 200ms linear'; main.style.transform = ''; main.style.opacity = '';
  if (go) step(s0.dx > 0 ? -1 : 1);
};
main.addEventListener('pointerup', endSwipe); main.addEventListener('pointercancel', endSwipe);

if (!location.hash) history.replaceState(null, '', '#/today');
start();