import { h } from '../lib/dom.js';
let tip;
export function tooltip(el, content) {
  const show = (e) => {
    if (!tip) { tip = h('div', { class: 'tip', role: 'tooltip' }); document.body.append(tip); }
    tip.replaceChildren(...(typeof content === 'function' ? content() : [content]));
    tip.style.display = 'block'; move(e);
  };
  const move = (e) => {
    if (!tip) return;
    const r = tip.getBoundingClientRect();
    tip.style.left = Math.min(e.clientX + 14, innerWidth - r.width - 8) + 'px';
    tip.style.top = Math.min(e.clientY + 14, innerHeight - r.height - 8) + 'px';
  };
  el.addEventListener('mouseenter', show); el.addEventListener('mousemove', move);
  el.addEventListener('mouseleave', () => { if (tip) tip.style.display = 'none'; });
  el.addEventListener('focus', (e) => { const r = el.getBoundingClientRect(); show({ clientX: r.left, clientY: r.bottom }); });
  el.addEventListener('blur', () => { if (tip) tip.style.display = 'none'; });
}