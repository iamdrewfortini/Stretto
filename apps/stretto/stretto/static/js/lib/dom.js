// Element builders. Text is only ever inserted as text nodes: window titles are untrusted input.
const SVGNS = 'http://www.w3.org/2000/svg';
function apply(el, props) {
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.setAttribute('class', v);
    else if (k === 'style' && typeof v === 'object') { for (const [sk, sv] of Object.entries(v)) { if (sv == null) continue; if (sk.startsWith('--')) el.style.setProperty(sk, sv); else el.style[sk] = sv; } }
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else el.setAttribute(k, v === true ? '' : String(v));
  }
}
function add(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k == null || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return el;
}
export const h = (tag, props, ...kids) => { const el = document.createElement(tag); apply(el, props); return add(el, kids); };
export const s = (tag, props, ...kids) => { const el = document.createElementNS(SVGNS, tag); apply(el, props); return add(el, kids); };
export const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };