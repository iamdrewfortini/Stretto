import { h } from '../lib/dom.js';
import { okDraw } from './kit.js';
let box;
export function toast(msg, kind = '') {
  if (!box) { box = h('div', { class: 'toasts', role: 'status', 'aria-live': 'polite' }); document.body.append(box); }
  const t = h('div', { class: `toast ${kind}` }, kind === 'good' ? okDraw() : null, msg);
  box.append(t);
  setTimeout(() => { t.classList.add('out'); setTimeout(() => t.remove(), 190); }, 4200);
}