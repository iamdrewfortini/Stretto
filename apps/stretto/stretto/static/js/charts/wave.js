// Wave visuals. Each one encodes measured data; none is decoration.
//   dayPacket  the day as a wave packet: envelope = focus intensity, carrier frequency = local switching rate
//   resonance  uninterrupted focus stretches as a resonance spectrum: a tall narrow peak far right = a tight day
//   field      apps as wave sources (amplitude ~ sqrt(time)); their interference field, routes as light paths, visits as Doppler rings
// Canvas is drawn at devicePixelRatio, redrawn on resize and theme change, and never animates in the background.
import { h, s } from '../lib/dom.js';
import { clock, dur } from '../lib/fmt.js';
import { catColor, consonance } from '../lib/harmony.js';

const FOCUS = new Set(['Build', 'Write', 'Learn', 'Plan', 'Design', 'Research']);
const WEIGHT = { Build: 1, Write: 1, Design: 1, Plan: .9, Learn: .9, Research: .85, Communication: .45, Browsing: .3, Other: .3, Distraction: .55, Idle: 0 };
const RM = matchMedia('(prefers-reduced-motion: reduce)');
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

// Keep a canvas sharp and current: size its backing store to the device, redraw on resize and on theme change.
function liveCanvas(draw, { height }) {
  const cv = h('canvas', { 'aria-hidden': 'true' });
  const hOf = (w) => (typeof height === 'function' ? height(w) : height);
  const wrap = h('div', { class: 'wave', style: typeof height === 'function' ? {} : { height: `${height}px` } }, cv);
  let raf = 0;
  const paint = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => {
    const r = wrap.getBoundingClientRect(); if (!r.width) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2), H = hOf(r.width);
    cv.width = Math.round(r.width * dpr); cv.height = Math.round(H * dpr); cv.style.width = `${r.width}px`; cv.style.height = `${H}px`;
    const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, r.width, H); draw(g, r.width, H);
  }); };
  new ResizeObserver(paint).observe(wrap);
  new MutationObserver(paint).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  wrap.repaint = paint;
  return wrap;
}
const rgb = (v, a) => `rgba(${v}, ${a})`;

/* ---------- focus stream: capsule waveform (Voice Memos style), live ---------- */
const seenEnd = new Map();   // per day: the last time already drawn, so only new bars grow in on a live refresh
export function dayPacket(blocks, { t0, t1, height = 132, live = false, day = '' }) {
  const minutes = Math.max(1, Math.round((t1 - t0) / 60));
  const cat = new Array(minutes).fill(null), app = new Array(minutes).fill(''), runLen = new Array(minutes).fill(0);
  for (const b of blocks) for (let m = Math.max(0, Math.floor((b.start - t0) / 60)); m < Math.min(minutes, Math.ceil((b.end - t0) / 60)); m++) { cat[m] = b.category; app[m] = b.domain || b.app; }
  // length of the uninterrupted focus run each minute belongs to: long runs are drawn a register lower (deeper colour)
  for (let i = 0; i < minutes;) { let j = i; const f = cat[i] && WEIGHT[cat[i]] >= .85; while (j < minutes && (cat[j] && WEIGHT[cat[j]] >= .85) === f && (f || j === i)) j++; for (let k = i; k < j; k++) runLen[k] = f ? j - i : 0; i = Math.max(j, i + 1); }
  const switches = []; for (let i = 1; i < minutes; i++) if (app[i] && app[i - 1] && app[i] !== app[i - 1]) switches.push(i);
  const sw = new Array(minutes).fill(0); for (const m of switches) for (let k = Math.max(0, m - 5); k < Math.min(minutes, m + 6); k++) sw[k] += 1;
  // height = focus weight, lowered where switching was dense (fragmentation shows as a dip), lifted a little by run depth
  const raw = cat.map((c, i) => (c ? (WEIGHT[c] ?? .3) * (1 - Math.min(.55, sw[i] * .14)) * (.72 + .28 * Math.min(1, runLen[i] / 40)) : 0));
  const lastData = blocks.length ? Math.min(t1, blocks[blocks.length - 1].end) : t0, prevEnd = seenEnd.get(day) ?? (live ? lastData : t1);
  const growFrom = live && lastData > prevEnd && !RM.matches ? prevEnd : null; seenEnd.set(day, lastData);
  let grow = 1, t0anim = 0;
  const readout = h('div', { class: 'wave-read', 'aria-live': 'polite' });
  const el = liveCanvas((g, W, H) => {
    const ink = css('--field-ink'), step = 4, bw = 2, n = Math.floor(W / step), mid = H / 2 + 6, maxH = H - 26;
    // switch ticks: one dot per app change, above the wave (the day's "beats")
    g.fillStyle = rgb(ink, .32);
    for (const m of switches) { const x = (m / minutes) * W; g.beginPath(); g.arc(x, 6, 1.4, 0, Math.PI * 2); g.fill(); }
    g.lineCap = 'round';
    for (let i = 0; i < n; i++) {
      const a = Math.floor(i / n * minutes), z = Math.max(a + 1, Math.floor((i + 1) / n * minutes));
      let sum = 0, best = null, bestW = 0, deep = false; const tally = {};
      for (let m = a; m < z; m++) { sum += raw[m]; if (cat[m]) { tally[cat[m]] = (tally[cat[m]] || 0) + 1; if (tally[cat[m]] > bestW) { bestW = tally[cat[m]]; best = cat[m]; } } if (runLen[m] >= 40) deep = true; }
      const x = i * step + step / 2, v = sum / (z - a), tMin = t0 + a * 60;
      let k = 1; if (growFrom !== null && tMin >= growFrom) k = Math.max(0, Math.min(1, grow));
      if (!best) { g.fillStyle = rgb(ink, .12); g.beginPath(); g.arc(x, mid, 1, 0, Math.PI * 2); g.fill(); continue; }
      const hh = Math.max(bw, v * maxH * k);
      g.strokeStyle = catColor(best, { deep }); g.lineWidth = bw; g.globalAlpha = deep ? 1 : .78;
      g.beginPath(); g.moveTo(x, mid - hh / 2 + bw / 2); g.lineTo(x, mid + hh / 2 - bw / 2); g.stroke(); g.globalAlpha = 1;
    }
    if (live) {   // playhead at the newest data
      const x = Math.min(W - 2, (lastData - t0) / (t1 - t0) * W);
      g.strokeStyle = rgb(ink, .5); g.lineWidth = 1; g.setLineDash([2, 3]); g.beginPath(); g.moveTo(x, 12); g.lineTo(x, H - 4); g.stroke(); g.setLineDash([]);
    }
  }, { height });
  if (growFrom !== null) { const tick = (ts) => { if (!t0anim) t0anim = ts; grow = Math.min(1, (ts - t0anim) / 520); grow = 1 - Math.pow(1 - grow, 3); el.repaint(); if (grow < 1) requestAnimationFrame(tick); }; grow = 0; requestAnimationFrame(tick); }
  if (live) el.append(h('i', { class: 'wave-now', style: { left: `${Math.min(100, (lastData - t0) / (t1 - t0) * 100)}%` }, 'aria-hidden': 'true' }));
  const cursor = h('i', { class: 'wave-cursor', hidden: true });
  el.append(cursor, readout);
  const at = (clientX) => { const r = el.getBoundingClientRect(), f = Math.min(1, Math.max(0, (clientX - r.left) / r.width)), m = Math.min(minutes - 1, Math.floor(f * minutes));
    cursor.hidden = false; cursor.style.transform = `translateX(${f * r.width}px)`;
    readout.textContent = `${clock(t0 + m * 60)} · ${app[m] || 'idle'}${cat[m] ? ' · ' + cat[m] : ''}${runLen[m] >= 20 ? ' · deep stretch' : ''}`; };
  el.addEventListener('pointermove', (e) => at(e.clientX)); el.addEventListener('pointerleave', () => { cursor.hidden = true; readout.textContent = ''; });
  el.setAttribute('role', 'img');
  el.setAttribute('aria-label', `Focus stream: ${minutes} minutes, ${switches.length} switches; bar height is focus, colour is the category.`);
  return el;
}

/* ---------- focus resonance spectrum ---------- */
export function focusRuns(blocks) {
  const runs = []; let cur = null;
  for (const b of blocks) {
    if (FOCUS.has(b.category)) { if (cur && b.start - cur.end <= 60) cur.end = b.end; else { if (cur) runs.push(cur); cur = { start: b.start, end: b.end }; } }
    else if (b.category !== 'Idle' || (cur && b.end - b.start > 300)) { if (cur) runs.push(cur); cur = null; }
  }
  if (cur) runs.push(cur);
  return runs.map((r) => (r.end - r.start) / 60).filter((m) => m >= 1);
}
export function resonance(blocks, { height = 150 } = {}) {
  const runs = focusRuns(blocks);
  if (!runs.length) return h('p', { class: 'muted' }, 'No uninterrupted focus stretch yet today.');
  const maxX = Math.max(90, Math.ceil(Math.max(...runs) * 1.25 / 15) * 15), W = 600, H = height, N = 240;
  const S = []; for (let i = 0; i <= N; i++) { const x = i / N * maxX; let v = 0; for (const L of runs) { const g = 3 + .12 * L; v += L * g * g / ((x - L) ** 2 + g * g); } S.push(v); }
  const top = Math.max(...S), peakI = S.indexOf(top), peakX = peakI / N * maxX;
  let lo = peakI, hi = peakI; while (lo > 0 && S[lo] > top / 2) lo--; while (hi < N && S[hi] > top / 2) hi++;
  const fwhm = Math.max(1, (hi - lo) / N * maxX), Q = peakX / fwhm;
  const sorted = [...runs].sort((a, b) => a - b), total = runs.reduce((a, b) => a + b, 0); let acc = 0, typical = sorted[0];
  for (const L of sorted) { acc += L; if (acc >= total / 2) { typical = L; break; } }
  const X = (x) => x / maxX * W, Y = (v) => H - 18 - v / top * (H - 40);
  const line = S.map((v, i) => `${i ? 'L' : 'M'}${X(i / N * maxX).toFixed(1)} ${Y(v).toFixed(1)}`).join(' ');
  const ticks = []; for (let t = 0; t <= maxX; t += maxX > 120 ? 30 : 15) ticks.push(t);
  const svg = s('svg', { class: 'reso', viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', role: 'img', 'aria-label': `Focus spectrum: ${runs.length} uninterrupted stretches; typical stretch ${Math.round(typical)} minutes; longest ${Math.round(Math.max(...runs))} minutes.` },
    s('defs', {}, s('pattern', { id: 'reso-hatch', width: 4, height: 4, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' }, s('line', { x1: 0, y1: 0, x2: 0, y2: 4, stroke: 'currentColor', 'stroke-width': 1, opacity: .22 }))),
    ticks.map((t) => s('line', { x1: X(t), x2: X(t), y1: 8, y2: H - 18, class: 'reso-grid' })),
    s('path', { d: `${line} L${W} ${H - 18} L0 ${H - 18} Z`, fill: 'url(#reso-hatch)' }),
    s('path', { d: line, class: 'reso-line', 'vector-effect': 'non-scaling-stroke' }),
    runs.map((L) => s('line', { x1: X(L), x2: X(L), y1: H - 18, y2: H - 24, class: 'reso-run', 'vector-effect': 'non-scaling-stroke' })),
    s('line', { x1: X(peakX), x2: X(peakX), y1: Y(top), y2: H - 18, class: 'reso-peak', 'vector-effect': 'non-scaling-stroke' }));
  const axis = h('div', { class: 'reso-axis' }, ticks.map((t) => h('span', { style: { left: `${t / maxX * 100}%` } }, `${t}m`)));
  return h('div', { class: 'reso-wrap' },
    h('div', { class: 'reso-head' }, h('div', {}, h('b', { class: 'num' }, `${Math.round(typical)} min`), h('span', {}, 'typical uninterrupted stretch')),
      h('div', {}, h('b', { class: 'num' }, `Q ${Q.toFixed(1)}`), h('span', {}, Q >= 2 ? 'sharp: stretches are consistent' : Q >= 1 ? 'moderate spread' : 'broad: focus comes in scraps'))),
    h('div', { class: 'reso-plot' }, svg, axis),
    h('p', { class: 'faint reso-note' }, `${runs.length} stretches, longest ${dur(Math.max(...runs) * 60)}. Each stretch adds a peak at its length; a tall, narrow peak far right is a tight day.`));
}

/* ---------- paths: interference field ---------- */
function layout(names, edges, W, H) {
  const n = names.length, P = names.map((_, i) => { const a = i / n * 2 * Math.PI - Math.PI / 2; return { x: W / 2 + Math.cos(a) * W * .3, y: H / 2 + Math.sin(a) * H * .3, vx: 0, vy: 0 }; });
  const idx = Object.fromEntries(names.map((nm, i) => [nm, i])), maxC = Math.max(1, ...edges.map((e) => e.count));
  for (let it = 0; it < 420; it++) {
    const cool = 1 - it / 420;
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) { const a = P[i], b = P[j]; let dx = b.x - a.x, dy = b.y - a.y; const d2 = Math.max(400, dx * dx + dy * dy), f = 9000 / d2; const d = Math.sqrt(d2); dx /= d; dy /= d; a.vx -= dx * f; a.vy -= dy * f; b.vx += dx * f; b.vy += dy * f; }
    for (const e of edges) { const a = P[idx[e.src]], b = P[idx[e.dst]]; if (!a || !b) continue; const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1, k = .004 * (.5 + e.count / maxC) * (d - Math.min(W, H) * .32); a.vx += dx / d * k * d * .1; a.vy += dy / d * k * d * .1; b.vx -= dx / d * k * d * .1; b.vy -= dy / d * k * d * .1; }
    for (const p of P) { p.vx += (W / 2 - p.x) * .002; p.vy += (H / 2 - p.y) * .002; p.x += p.vx * cool * .5; p.y += p.vy * cool * .5; p.vx *= .6; p.vy *= .6; }
  }
  const xs = P.map((p) => p.x), ys = P.map((p) => p.y), pad = 70, mnx = Math.min(...xs), mxx = Math.max(...xs), mny = Math.min(...ys), mxy = Math.max(...ys);
  return P.map((p) => ({ x: pad + (p.x - mnx) / Math.max(1, mxx - mnx) * (W - 2 * pad), y: pad * .8 + (p.y - mny) / Math.max(1, mxy - mny) * (H - 1.6 * pad) }));
}
export function field(trans, byApp, hot = [], blocks = []) {
  const catTime = {}; for (const b of blocks) { const k = String(b.domain || b.app).toLowerCase(); (catTime[k] = catTime[k] || {})[b.category] = (catTime[k][b.category] || 0) + (b.end - b.start); }
  const catOf = (n) => { const t = catTime[String(n).toLowerCase()]; return t ? Object.entries(t).sort((a, b) => b[1] - a[1])[0][0] : null; };
  const names = [...new Set([...byApp.map((a) => a[0]), ...trans.flatMap((t) => [t.src, t.dst])])].slice(0, 12);
  const secs = Object.fromEntries(byApp), maxS = Math.max(1, ...Object.values(secs)), maxC = Math.max(1, ...trans.map((t) => t.count));
  const W = 720, H = 440, pos = layout(names, trans, W, H), at = Object.fromEntries(names.map((n, i) => [n, pos[i]]));
  const visits = Object.fromEntries(names.map((n) => [n, trans.filter((t) => t.src === n || t.dst === n).reduce((a, t) => a + t.count, 0)]));
  const nextOf = Object.fromEntries(names.map((n) => { const out = trans.filter((t) => t.src === n).sort((a, b) => b.count - a.count)[0]; return [n, out ? out.dst : null]; }));
  const hotSet = new Set(hot.slice(0, -1).map((n, i) => `${n}>${hot[i + 1]}`));
  const amp = names.map((n) => Math.sqrt((secs[n] || 0) / maxS) + .15);
  const canvas = liveCanvas((g, cw, ch) => {
    const sx = cw / W, sy = ch / H, ink = css('--field-ink'), step = 3, lam = 26, k = 2 * Math.PI / lam;
    const img = g.createImageData(Math.ceil(cw / step), Math.ceil(ch / step)), d = img.data;
    let max = 0; const vals = new Float32Array(img.width * img.height), ph = new Float32Array(img.width * img.height);
    for (let yy = 0; yy < img.height; yy++) for (let xx = 0; xx < img.width; xx++) {
      const x = xx * step / sx, y = yy * step / sy; let re = 0, im = 0;
      for (let i = 0; i < names.length; i++) { const r = Math.hypot(x - pos[i].x, y - pos[i].y), a = amp[i] / Math.sqrt(1 + r / 40); re += a * Math.cos(k * r); im += a * Math.sin(k * r); }
      const v = re * re + im * im, o = yy * img.width + xx; vals[o] = v; ph[o] = Math.atan2(im, re); if (v > max) max = v;
    }
    for (let o = 0; o < vals.length; o++) { const I = Math.pow(vals[o] / max, .55), band = .5 + .5 * Math.cos(ph[o] * 2), a = I * (.25 + .75 * band) * .26;
      d[o * 4] = +ink.split(',')[0]; d[o * 4 + 1] = +ink.split(',')[1]; d[o * 4 + 2] = +ink.split(',')[2]; d[o * 4 + 3] = Math.round(a * 255); }
    const tmp = document.createElement('canvas'); tmp.width = img.width; tmp.height = img.height; tmp.getContext('2d').putImageData(img, 0, 0);
    g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high'; g.drawImage(tmp, 0, 0, cw, ch);
  }, { height: (w) => w * H / W });
  canvas.classList.add('field-bg');
  const svg = s('svg', { class: 'field', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': `Paths between ${names.length} places. The table below lists every move.` },
    s('defs', {}, s('marker', { id: 'fh', viewBox: '0 0 6 6', refX: 5, refY: 3, markerWidth: 6, markerHeight: 6, orient: 'auto' }, s('path', { d: 'M0 0 6 3 0 6z', class: 'field-arrow' }))));
  for (const t of trans) {
    const a = at[t.src], b = at[t.dst]; if (!a || !b) continue;
    const mx = (a.x + b.x) / 2 + (b.y - a.y) * .18, my = (a.y + b.y) / 2 - (b.x - a.x) * .18, isHot = hotSet.has(`${t.src}>${t.dst}`);
    const q = consonance(catOf(t.src), catOf(t.dst));
    svg.append(s('path', { class: `fpath iv-${q}${isHot ? ' hot' : hot.length ? ' dim' : ''}`, d: `M${a.x},${a.y} Q${mx},${my} ${b.x},${b.y}`, 'stroke-width': .6 + t.count / maxC * 2.6, 'marker-end': 'url(#fh)', style: { '--len': '1' }, pathLength: 1 },
      s('title', {}, `${t.src} to ${t.dst}: ${t.count} times, average stay ${t.avg_stay_s}s · interval ${q}`)));
  }
  names.forEach((n, i) => {
    const p = pos[i], r = 5 + Math.sqrt((secs[n] || 0) / maxS) * 15, nx = nextOf[n] && at[nextOf[n]], dirx = nx ? (nx.x - p.x) / (Math.hypot(nx.x - p.x, nx.y - p.y) || 1) : 0, diry = nx ? (nx.y - p.y) / (Math.hypot(nx.x - p.x, nx.y - p.y) || 1) : 0;
    const cat = catOf(n), tint = cat ? catColor(cat) : 'var(--text)', deep = cat ? catColor(cat, { deep: true }) : 'var(--text)';
    const rings = Math.min(6, visits[n]), grp = s('g', { class: `fnode${hot.includes(n) ? ' hot' : ''}`, tabindex: 0, role: 'img', 'aria-label': `${n}: ${cat || 'uncategorised'}, ${dur(secs[n] || 0)}, ${visits[n]} moves in or out`, style: { '--tint': tint, '--deep': deep } });
    for (let k = rings; k >= 1; k--) { const rr = r + k * 7, shift = k * 1.8; grp.append(s('circle', { class: 'ring', cx: p.x + dirx * shift, cy: p.y + diry * shift, r: rr, style: { animationDelay: `${(rings - k) * 60}ms`, opacity: String(.5 - k * .06) } })); }
    grp.append(s('circle', { class: 'core', cx: p.x, cy: p.y, r }), s('circle', { class: 'spec', cx: p.x - r * .3, cy: p.y - r * .35, r: r * .35 }),
      s('text', { x: p.x, y: p.y + r + rings * 7 + 16 > H - 6 ? p.y - r - rings * 7 - 8 : p.y + r + rings * 7 + 16, 'text-anchor': 'middle' }, n.length > 18 ? n.slice(0, 17) + '…' : n), s('title', {}, `${n}: ${dur(secs[n] || 0)}`));
    svg.append(grp);
  });
  const wrap = h('div', { class: 'field-wrap' }, canvas, svg);
  return wrap;
}

/* ---------- focus field: three slow sources interfering in the mode's colour (the focus screen's backdrop) ---------- */
export function focusField() {
  const cv = h('canvas', { class: 'ffield-cv', 'aria-hidden': 'true' }); let raf = 0, last = 0, W = 0, H = 0;
  const draw = (ts) => {
    if (!cv.isConnected) return;
    if (document.hidden || ts - last < 50) { raf = requestAnimationFrame(draw); return; }   // ~20 fps is plenty for a slow field
    last = ts; const g = cv.getContext('2d'), step = 6, w = Math.ceil(W / step), hh = Math.ceil(H / step);
    if (!w || !hh) { raf = requestAnimationFrame(draw); return; }
    const img = g.createImageData(w, hh), d = img.data, t = RM.matches ? 0 : ts / 1000, tone = css('--tonic') || '#07d0d8';
    const tr = parseInt(tone.slice(1, 3), 16), tg = parseInt(tone.slice(3, 5), 16), tb = parseInt(tone.slice(5, 7), 16);
    const src = [[.3 + .08 * Math.sin(t * .11), .42 + .06 * Math.cos(t * .09)], [.7 + .07 * Math.cos(t * .07), .55 + .08 * Math.sin(t * .1)], [.5 + .1 * Math.sin(t * .05), .2 + .05 * Math.cos(t * .13)]];
    const k = 2 * Math.PI / 34;
    for (let y = 0; y < hh; y++) for (let x = 0; x < w; x++) {
      let re = 0, im = 0; for (const [sx, sy] of src) { const r = Math.hypot(x * step - sx * W, y * step - sy * H), a = 1 / Math.sqrt(1 + r / 90); re += a * Math.cos(k * r - t * 1.4); im += a * Math.sin(k * r - t * 1.4); }
      const I = Math.min(1, (re * re + im * im) / 6), o = (y * w + x) * 4; d[o] = tr; d[o + 1] = tg; d[o + 2] = tb; d[o + 3] = Math.round(I * 70);
    }
    const tmp = document.createElement('canvas'); tmp.width = w; tmp.height = hh; tmp.getContext('2d').putImageData(img, 0, 0);
    g.clearRect(0, 0, W, H); g.imageSmoothingQuality = 'high'; g.drawImage(tmp, 0, 0, W, H);
    if (!RM.matches) raf = requestAnimationFrame(draw);
  };
  new ResizeObserver(() => { const r = cv.getBoundingClientRect(); W = Math.round(r.width); H = Math.round(r.height); cv.width = W; cv.height = H; cancelAnimationFrame(raf); raf = requestAnimationFrame(draw); }).observe(cv);
  return cv;
}
