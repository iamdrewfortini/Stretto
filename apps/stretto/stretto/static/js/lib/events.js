// Live stream from the server (GET /api/events, server-sent events): the running timer, closing blocks and today's summary
// arrive as they happen. When the stream is closed the callers keep their polling, so nothing depends on it being up.
import { mode } from './mode.js';
const token = () => document.querySelector('meta[name="stretto-token"]')?.content || '';
const subs = new Set();
export const stream = {
  live: false, es: null,
  open() {
    if (this.es || typeof EventSource === 'undefined') return;
    const es = (this.es = new EventSource(`/api/events?token=${encodeURIComponent(token())}`));
    const parse = (e) => { try { return JSON.parse(e.data); } catch { return null; } };
    es.addEventListener('hello', (e) => { this.live = true; document.documentElement.dataset.streamLive = '1'; const d = parse(e); if (d && 'timer' in d) { mode.timer = d.timer; mode.apply(); } subs.forEach((f) => f('hello', d)); });
    es.addEventListener('timer', (e) => { mode.timer = parse(e); mode.apply(); subs.forEach((f) => f('timer', mode.timer)); });
    es.addEventListener('block', (e) => subs.forEach((f) => f('block', parse(e))));
    es.addEventListener('day', (e) => subs.forEach((f) => f('day', parse(e))));
    es.onerror = () => { this.live = false; delete document.documentElement.dataset.streamLive; };   // the browser reconnects on its own (retry 3000 from the server); polling covers the gap
  },
  on(f) { subs.add(f); return () => subs.delete(f); },
};
