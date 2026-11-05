// Hash router with query state: #/today?d=2026-11-03&f=2. Every view is a URL; Back works.
const routes = new Map();
const parse = () => { const [p, q = ''] = location.hash.replace(/^#\//, '').split('?'); return { page: p, q: new URLSearchParams(q) }; };
export const route = (id, fn) => routes.set(id, fn);
export const page = () => { const { page: p } = parse(); return routes.has(p) ? p : [...routes.keys()][0]; };
export const query = (k, d = '') => parse().q.get(k) ?? d;
export function go(id, params = {}, { replace = false } = {}) {
  const q = new URLSearchParams(); for (const [k, v] of Object.entries(params)) if (v !== '' && v != null) q.set(k, v);
  const hash = `#/${id}${q.toString() ? '?' + q : ''}`;
  if (replace) history.replaceState(null, '', hash); else if (location.hash !== hash) location.hash = hash;
  if (replace || location.hash === hash) render();
}
export const patch = (params, opts) => { const { q } = parse(); const cur = Object.fromEntries(q); go(page(), { ...cur, ...params }, opts); };
export function render() { return routes.get(page())(); }
export const start = () => { addEventListener('hashchange', render); render(); };