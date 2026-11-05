// Harmonic colour system (see golden-ui-specs/research/chromatic/HARMONIC-COLOR-MODEL.md).
// Each pitch class is its frequency transposed ~40 octaves into visible light (A = 620 nm anchor), spaced 30 degrees of hue per semitone,
// normalised for contrast (>= 5.2:1 on white, >= 8.3:1 on the dark surface). Octaves keep the hue and change lightness.
// Stretto's categories are scale degrees above one tonic (focus). Change TONIC and every colour follows by interval.
export const NOTES = [{"note":"C","nm":521,"light":"#267e01","dark":"#81ce6f","oct":["#165002","#2a7d0d","#57a943","#83d66f"]},{"note":"C♯","nm":492,"light":"#057b60","dark":"#20d5a8","oct":["#034f3c","#057b60","#07ab85","#08deae"]},{"note":"D","nm":464,"light":"#02787d","dark":"#07d0d8","oct":["#024c50","#02787d","#02a6ad","#00d7e0"]},{"note":"D♯","nm":438,"light":"#057398","dark":"#39c7ff","oct":["#034962","#057398","#07a0d2","#58ccff"]},{"note":"E","nm":414,"light":"#2564c9","dark":"#8db8ff","oct":["#013b91","#2a65c3","#5490f3","#98bffe"]},{"note":"F","nm":390,"light":"#6b50c2","dark":"#b6aaff","oct":["#45288f","#6a53bd","#927eec","#bcb2ff"]},{"note":"F♯","nm":737,"light":"#9240a4","dark":"#e196f3","oct":["#651676","#8f43a1","#bc6ecf","#ea9afe"]},{"note":"G","nm":696,"light":"#ab3277","dark":"#fd8dc5","oct":["#79014e","#a83876","#d764a0","#ff98ca"]},{"note":"G♯","nm":657,"light":"#b6303e","dark":"#ff9496","oct":["#80011e","#b23641","#e36369","#ff9fa0"]},{"note":"A","nm":620,"light":"#a44c05","dark":"#fe9b61","oct":["#6b2e01","#a44c05","#dd6f24","#ffa572"]},{"note":"A♯","nm":585,"light":"#896105","dark":"#e9ab2c","oct":["#583d01","#896105","#bd8704","#f3b01e"]},{"note":"B","nm":552,"light":"#6e6e04","dark":"#bebf3a","oct":["#464601","#6e6e04","#999909","#c5c631"]}];
export const TONIC = 2;   // D: teal focus; the tritone (lost time) lands on G-sharp red
// Semitones above the tonic, chosen among consonances whose colours stay out of the orange-yellow band (owner: no orange).
// The 5th (A) is unused for that reason; the major/minor 3rds and the 4th carry the related work.
export const DEGREE = { Build: 0, Write: 4, Design: 4, Plan: 5, Learn: 5, Research: 3, Communication: 2, Browsing: 11, Other: 11, Distraction: 1 };   // Idle is a rest
export const LOST = 6;     // tritone
export const FUNCTION = { 0: 'tonic', 1: 'minor 2nd', 2: 'major 2nd', 3: 'minor 3rd', 4: 'major 3rd', 5: 'perfect 4th', 6: 'tritone', 11: 'major 7th' };
export const pcOf = (cat) => (cat in DEGREE ? (TONIC + DEGREE[cat]) % 12 : null);
export const noteOf = (cat) => { const p = pcOf(cat); return p === null ? '' : NOTES[p].note; };
const dark = () => document.documentElement.dataset.theme === 'dark' || (document.documentElement.dataset.mode || 'calm') !== 'calm';
// colour of a pitch class; deep = a lower octave (used for long uninterrupted stretches)
export const pcColor = (p, { deep = false } = {}) => { const n = NOTES[((p % 12) + 12) % 12]; return dark() ? (deep ? n.oct[2] : n.dark) : (deep ? n.oct[0] : n.light); };
export const catColor = (cat, opts) => { const p = pcOf(cat); return p === null ? 'var(--c-idle)' : pcColor(p, opts); };
export const lostColor = (opts) => pcColor(TONIC + LOST, opts);
// interval quality between two categories: what line style a move between them gets
export function consonance(a, b) {
  const pa = pcOf(a), pb = pcOf(b); if (pa === null || pb === null) return 'rest';
  const iv = Math.min((pb - pa + 12) % 12, (pa - pb + 12) % 12);
  return iv === 0 ? 'unison' : iv === 5 ? 'perfect' : iv === 3 || iv === 4 ? 'imperfect' : iv === 6 ? 'tritone' : 'dissonant';
}
// A chord = time-weighted pitch-class vector. DFT coefficient 5: phase = place on the circle of fifths, magnitude = clarity (Quinn; Amiot).
export function chord(vec) {
  const tot = vec.reduce((s, v) => s + v, 0); if (!tot) return null;
  const F = (k) => { let re = 0, im = 0; vec.forEach((v, p) => { re += v * Math.cos(-2 * Math.PI * k * p / 12); im += v * Math.sin(-2 * Math.PI * k * p / 12); }); return { mag: Math.hypot(re, im) / tot, ph: Math.atan2(im, re) }; };
  const f5 = F(5), q = (((-f5.ph / (2 * Math.PI)) * 12) % 12 + 12) % 12, centre = (5 * Math.round(q)) % 12, home = (5 * TONIC) % 12;
  const dist = Math.min(Math.abs(q - home), 12 - Math.abs(q - home));   // steps round the circle of fifths from the tonic, 0..6
  return { centre, clarity: f5.mag, dist, spread: 1 - f5.mag, tot };
}
// mix a hex colour toward neutral grey by (1 - t): unclear chords lose their colour
export function fade(hex, t) { const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)), g = dark() ? 120 : 158; return '#' + c.map((v) => Math.round(g + (v - g) * Math.max(0, Math.min(1, t))).toString(16).padStart(2, '0')).join(''); }

// Colour of a chord: the time-weighted blend of the colours of the notes that sounded (so it never leaves the palette),
// faded toward grey by (1 - clarity). The centre on the circle of fifths is shown as text, not as a new hue.
export function chordColor(vec, clarity) {
  let r = 0, g = 0, b = 0, t = 0;
  vec.forEach((v, p) => { if (!v) return; const c = pcColor(p); r += parseInt(c.slice(1, 3), 16) * v; g += parseInt(c.slice(3, 5), 16) * v; b += parseInt(c.slice(5, 7), 16) * v; t += v; });
  const hex = '#' + [r, g, b].map((x) => Math.round(x / t).toString(16).padStart(2, '0')).join('');
  return fade(hex, Math.min(1, clarity * 1.2));
}
