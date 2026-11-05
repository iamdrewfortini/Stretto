const token = () => document.querySelector('meta[name="stretto-token"]')?.content || '';
async function call(method, path, body) {
  const res = await fetch(path, { method, headers: { 'Content-Type': 'application/json', 'X-Stretto-Token': token() }, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `request failed (${res.status})`);
  return data;
}
const inflight = new Map();   // identical GETs in the same tick share one request: pages asking together never pay twice
function get(p) { const hit = inflight.get(p); if (hit) return hit; const q = call('GET', p).finally(() => { if (inflight.get(p) === q) inflight.delete(p); }); inflight.set(p, q); return q; }
export const api = { get, post: (p, b = {}) => call('POST', p, b) };
