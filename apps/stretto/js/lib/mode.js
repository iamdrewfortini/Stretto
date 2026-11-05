// App mode follows the server's running timer: calm (none), focus, or break. The whole interface restyles from html[data-mode].
import { api } from './api.js';
const subs = new Set();
export const mode = {
  timer: null, name: 'calm',
  async refresh() { try { this.timer = await api.get('/api/timer'); } catch { /* keep last known */ } this.apply(); },
  apply() {
    const n = this.timer ? (this.timer.kind === 'break' ? 'break' : 'focus') : 'calm';
    this.name = n; document.documentElement.dataset.mode = n; subs.forEach((f) => f(n));
  },
  on(f) { subs.add(f); return () => subs.delete(f); },
};
setInterval(() => { if (!document.hidden && !document.documentElement.dataset.streamLive) mode.refresh(); }, 5000);
addEventListener('visibilitychange', () => { if (!document.hidden) mode.refresh(); });
