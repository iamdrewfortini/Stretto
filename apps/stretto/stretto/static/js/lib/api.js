const token = () => document.querySelector('meta[name="stretto-token"]')?.content || '';
async function call(method, path, body) {
  const res = await fetch(path, { method, headers: { 'Content-Type': 'application/json', 'X-Stretto-Token': token() }, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `request failed (${res.status})`);
  return data;
}
export const api = { get: (p) => call('GET', p), post: (p, b = {}) => call('POST', p, b) };