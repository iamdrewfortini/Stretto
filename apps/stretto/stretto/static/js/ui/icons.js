import { s } from '../lib/dom.js';
const P = {
  sun: 'M12 4V2m0 20v-2m8-8h2M2 12h2m13.7-5.7 1.4-1.4M4.9 19.1l1.4-1.4m0-11.4L4.9 4.9m14.2 14.2-1.4-1.4M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z',
  route: 'M6 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM6 15V9a4 4 0 0 1 4-4h4m-4 14h4a4 4 0 0 0 4-4V9',
  board: 'M4 4h5v16H4zM10 4h5v10h-5zM16 4h4v13h-4z',
  timer: 'M12 8v5l3 2M9 2h6M12 21a8 8 0 1 0 0-16 8 8 0 0 0 0 16z',
  habit: 'M5 12l4 4L19 6M4 20h16',
  chart: 'M4 20V10m6 10V4m6 16v-7m4 7H2',
  spark: 'M12 2l2.2 6.3L21 10l-6.3 2.2L12 19l-2.2-6.8L3 10l6.8-1.7z',
  calendar: 'M5 5h14v15H5zM5 10h14M9 3v4m6-4v4',
  gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4-2.3.9a7 7 0 0 0-2-1.2L14.2 3h-4l-.4 2.6a7 7 0 0 0-2 1.2l-2.3-.9-2 3.4 2 1.5A7 7 0 0 0 5 12c0 .4 0 .8.1 1.2l-2 1.5 2 3.4 2.3-.9a7 7 0 0 0 2 1.2l.4 2.6h4l.4-2.6a7 7 0 0 0 2-1.2l2.3.9 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zm9 16-4-4',
  shield: 'M12 3l7 3v6c0 4.5-3 7.6-7 9-4-1.4-7-4.5-7-9V6z', devices: 'M3 5h13v9H3zM7 18h5M18 9h3v10h-3z',
  play: 'M8 5.5v13l10.5-6.5z', stop: 'M7 7h10v10H7z',
  left: 'M15 5l-7 7 7 7', right: 'M9 5l7 7-7 7', flame: 'M12 3c1 4 5 5 5 10a5 5 0 0 1-10 0c0-2 1-3 2-4 0 2 1 3 2 3 0-3-1-6 1-9z',
  moon: 'M20 14A8 8 0 0 1 10 4a8 8 0 1 0 10 10z', alert: 'M12 4l9 16H3zM12 10v4m0 3v.01', repeat: 'M4 9h13l-3-3m3 3-3 3M20 15H7l3 3m-3-3 3-3',
  swap: 'M7 8h12l-3-3m3 3-3 3M17 16H5l3 3m-3-3 3-3', plus: 'M12 5v14M5 12h14', check: 'M5 12l5 5 9-10', x: 'M6 6l12 12M18 6 6 18',
};
export const icon = (name, size = 18) => s('svg', { viewBox: '0 0 24 24', width: size, height: size, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' }, s('path', { d: P[name] || P.spark }));
export const logo = (size = 30) => s('svg', { viewBox: '0 0 32 32', width: size, height: size, role: 'img', 'aria-label': 'Stretto' },
  s('rect', { width: 32, height: 32, rx: 9, style: { fill: 'var(--accent)' } }),
  s('path', { d: 'M4 16 C6 16 6.6 12.6 8 12.6 S10 19.4 11.6 19.4 13.4 9 15.6 9 17.8 23 20 23 22 11.4 23.8 11.4 25.6 17.2 27 17.2 28 16 28 16', fill: 'none', 'stroke-width': 1.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', style: { stroke: 'var(--on-accent)' } }),
  s('path', { d: 'M4 16 C8 16 10 13 16 13 S24 16 28 16', fill: 'none', 'stroke-width': 1, opacity: .35, style: { stroke: 'var(--on-accent)' } }));
