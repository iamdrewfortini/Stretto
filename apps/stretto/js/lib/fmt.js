export const dur = (sec) => {
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  if (h) return `${h}h ${String(m).padStart(2, '0')}m`;
  return m ? `${m}m` : `${sec}s`;
};
export const clock = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
export const pct = (a, b) => (b > 0 ? Math.round((a / b) * 100) : 0);
export const iso = (d) => { const z = new Date(d.getTime() - d.getTimezoneOffset() * 60000); return z.toISOString().slice(0, 10); };
export const shiftDay = (isoDay, n) => { const d = new Date(isoDay + 'T12:00:00'); d.setDate(d.getDate() + n); return iso(d); };
export const nice = (isoDay) => new Date(isoDay + 'T12:00:00').toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' });
export const CAT = ['Build', 'Write', 'Learn', 'Plan', 'Design', 'Research', 'Communication', 'Distraction', 'Browsing', 'Other', 'Idle'];
export const catVar = (c) => `var(--c-${String(c).toLowerCase()})`;