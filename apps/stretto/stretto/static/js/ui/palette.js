import { h } from '../lib/dom.js';
export function palette(commands) {
  const prev = document.activeElement;
  let sel = 0, shown = commands;
  const input = h('input', { placeholder: 'Type a command or page…', 'aria-label': 'Command', autocomplete: 'off' });
  const list = h('ul', { role: 'listbox' });
  const scrim = h('div', { class: 'scrim' }, h('div', { class: 'palette', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Command palette' }, input, list));
  const close = () => { document.documentElement.classList.remove('modal'); scrim.classList.add('out'); setTimeout(() => scrim.remove(), 170); prev?.focus?.(); };
  // matched letters are emphasised; results stay grouped; the first row is always selected (R23)
  const mark = (label, q) => { if (!q) return [label]; const i = label.toLowerCase().indexOf(q); return i < 0 ? [label] : [label.slice(0, i), h('mark', {}, label.slice(i, i + q.length)), label.slice(i + q.length)]; };
  const draw = () => {
    const q = input.value.trim().toLowerCase(), out = []; let g = null;
    shown.forEach((c, i) => { if (c.group && c.group !== g) { g = c.group; out.push(h('li', { class: 'grp', role: 'presentation' }, g)); }
      out.push(h('li', { role: 'option', 'aria-selected': i === sel ? 'true' : 'false', onclick: () => { close(); c.run(); } }, h('span', { class: 'lbl' }, ...mark(c.label, q)), c.detail ? h('span', { class: 'det' }, c.detail) : null, h('span', { class: 'keys' }, ...(c.keys || (c.hint ? [c.hint] : [])).map((k) => h('kbd', {}, k))))); });
    list.replaceChildren(...out);
    list.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
  };
  input.addEventListener('input', () => { const q = input.value.trim().toLowerCase(); shown = commands.filter((c) => (c.label + ' ' + (c.detail || '')).toLowerCase().includes(q)); sel = 0; draw(); });
  scrim.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') close();
    else if (e.key === 'ArrowDown') { sel = Math.min(sel + 1, shown.length - 1); draw(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { sel = Math.max(sel - 1, 0); draw(); e.preventDefault(); }
    else if (e.key === 'Enter' && shown[sel]) { close(); shown[sel].run(); }
  });
  scrim.addEventListener('mousedown', (e) => { if (e.target === scrim) close(); });
  document.body.append(scrim); document.documentElement.classList.add('modal'); draw(); input.focus();
}