const KEY = 'stretto.prefs';
const load = () => { try { return JSON.parse(localStorage.getItem(KEY) || '{}'); } catch { return {}; } };
const prefs = load();
const subs = new Set();
export const state = {
  get: (k, d) => (k in prefs ? prefs[k] : d),
  set(k, v) { prefs[k] = v; try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { /* private mode */ } subs.forEach((f) => f(k, v)); },
  on(f) { subs.add(f); return () => subs.delete(f); },
};