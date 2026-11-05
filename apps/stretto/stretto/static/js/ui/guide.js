// Guiding light: one persistent walk through the platform, always visible, always pointing at the exact next step.
// Steps complete from real state (consent, measured day, sessions, insights) plus pages the person has visited.
// The current step's light stays lit; its page's primary action gets .guide-target until used. Dismiss is per-day.
import { h, clear } from '../lib/dom.js';
import { api } from '../lib/api.js';
import { go } from '../lib/router.js';

const seenKey = (id) => `stretto.guide.seen.${id}`;
export const markSeen = (id) => { try { localStorage.setItem(seenKey(id), '1'); } catch {} };
const seen = (id) => { try { return !!localStorage.getItem(seenKey(id)); } catch { return false; } };

const STEPS = [
  { id: 'privacy', label: 'Accept consent', hint: 'Read a notice and accept it — nothing is collected before this.' },
  { id: 'today', label: 'Measure a day', hint: 'Let the agent record, or load the labelled simulated day.' },
  { id: 'paths', label: 'Face the biggest challenge', hint: 'One grouped pattern, compounded. Read its simplest fix.' },
  { id: 'focus', label: 'Run one focus block', hint: 'Start a 25-minute block on a task, or on none.' },
  { id: 'insights', label: 'Get coaching', hint: 'Generate Insights: measured findings, phrased by the model.' },
];

let state = null, stateAt = 0;
async function probe() {
  if (state && Date.now() - stateAt < 30000) return state;
  const [consent, day, insights, sessions] = await Promise.all([
    api.get('/api/consent').catch(() => null),
    api.get('/api/day').catch(() => null),
    api.get('/api/insights').catch(() => null),
    api.get(`/api/sessions?from=${new Date().toISOString().slice(0, 10)}&to=${new Date().toISOString().slice(0, 10)}`).catch(() => null),
  ]);
  const anyConsent = consent && Object.values(consent.families || {}).some((f) => f.active);
  state = {
    privacy: !!anyConsent,
    today: !!((day && day.summary && day.summary.total_s) || seen('today-data')),
    paths: seen('paths') && !!day && (day.findings || []).length >= 0,
    focus: !!((sessions && (sessions.sessions || []).length) || seen('focus-started')),
    insights: !!(insights && insights.available && insights.headline),
  };
  stateAt = Date.now();
  return state;
}

const bar = h('div', { class: 'guide', role: 'navigation', 'aria-label': 'Your next step' });
let dismissedDay = '';
try { dismissedDay = localStorage.getItem('stretto.guide.dismissed') || ''; } catch {}

let lastSpot = '';
function spotlight(stepId) {
  document.querySelectorAll('.guide-target').forEach((e) => e.classList.remove('guide-target'));
  const t = document.querySelector('[data-next]') || document.querySelector('.nextstep .btn.primary') || document.querySelector('main .btn.primary');
  if (t) { t.classList.add('guide-target'); if (lastSpot !== stepId) { lastSpot = stepId; t.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); } }
}

export async function paintGuide(currentPage) {
  if (dismissedDay === new Date().toISOString().slice(0, 10)) { bar.hidden = true; return; }
  const done = await probe().catch(() => ({}));
  const idx = STEPS.findIndex((s) => !done[s.id]);
  clear(bar); bar.hidden = false;
  const dots = h('div', { class: 'guide-track', 'aria-hidden': 'true' },
    STEPS.map((s, i) => h('span', { class: `guide-dot${done[s.id] ? ' done' : i === idx ? ' now' : ''}` }, done[s.id] ? '✓' : String(i + 1))));
  if (idx === -1) {
    bar.append(dots, h('b', {}, 'Walk complete'), h('span', { class: 'grow guide-hint' }, 'Today is home. The light restarts with tomorrow’s day.'),
      h('button', { class: 'btn sm primary', onclick: () => go('today') }, 'Go to Today →'), closeBtn());
    return;
  }
  const step = STEPS[idx];
  bar.append(dots,
    h('div', { class: 'guide-txt' }, h('b', {}, `Next: ${step.label}`), h('span', { class: 'guide-hint' }, step.hint)),
    h('button', { class: 'btn sm primary', onclick: () => { go(step.id); setTimeout(() => spotlight(step.id), 450); } }, currentPage === step.id ? 'Do it here ↓' : `Take me there →`),
    closeBtn());
  if (currentPage === step.id) setTimeout(() => spotlight(step.id), 350);
}
function closeBtn() {
  return h('button', { class: 'icon-btn guide-x', 'aria-label': 'Hide the guide for today', onclick: () => { dismissedDay = new Date().toISOString().slice(0, 10); try { localStorage.setItem('stretto.guide.dismissed', dismissedDay); } catch {} bar.hidden = true; } }, '×');
}
export const guideBar = bar;
