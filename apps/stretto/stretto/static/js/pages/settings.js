// Settings: daily focus goal, appearance, and categorisation rules (which app, site or title counts as which category).
import { h } from '../lib/dom.js';
import { api } from '../lib/api.js';
import { dur, CAT, catVar } from '../lib/fmt.js';
import { state } from '../lib/state.js';
import { toast } from '../ui/toast.js';
import { noteOf, FUNCTION, DEGREE } from '../lib/harmony.js';

export default {
  id: 'settings', key: 's', dated: false, title: 'Settings', icon: 'gear',
  load: async () => { const [settings, rules] = await Promise.all([api.get('/api/settings'), api.get('/api/rules')]); return { settings, rules }; },
  view(d) {
    // goal
    const out = h('b', { class: 'num st-goal' }, dur(d.settings.goal_min * 60));
    const range = h('input', { type: 'range', min: 30, max: 600, step: 15, value: d.settings.goal_min, class: 'st-range', 'aria-label': 'Daily focus goal in minutes' });
    let t = 0; range.addEventListener('input', () => { out.textContent = dur(range.value * 60); clearTimeout(t); t = setTimeout(async () => { try { await api.post('/api/settings', { goal_min: Number(range.value) }); toast(`Daily goal: ${dur(range.value * 60)}`); } catch (e) { toast(e.message, 'bad'); } }, 500); });
    // appearance
    const theme = state.get('theme', 'system');
    const seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Theme' }, [['system', 'System'], ['light', 'Light'], ['dark', 'Dark']].map(([v, l]) => h('button', { 'aria-pressed': String(theme === v), onclick: () => { state.set('theme', v); location.reload(); } }, l)));
    // rules
    const field = h('select', { class: 'input', 'aria-label': 'Match on' }, ['app', 'domain', 'title'].map((f) => h('option', { value: f }, f)));
    const pat = h('input', { class: 'input grow mono', placeholder: 'pattern, e.g. figma|sketch', 'aria-label': 'Pattern (regular expression)', autocomplete: 'off', spellcheck: 'false', autocapitalize: 'off' });
    const cat = h('select', { class: 'input', 'aria-label': 'Category' }, CAT.filter((c) => c !== 'Idle').map((c) => h('option', { value: c }, c)));
    const rows = h('tbody', {}, d.rules.map((r) => h('tr', {}, h('td', { 'data-label': 'Match on' }, r.field), h('td', { 'data-label': 'Pattern' }, h('code', { class: 'mono' }, r.pattern)), h('td', { 'data-label': 'Category' }, h('i', { class: `swatch tx tx-${String(r.category).toLowerCase()}`, style: { '--c': catVar(r.category) } }), ' ', r.category))));
    const add = async () => {
      if (!pat.value.trim()) return; try { new RegExp(pat.value); } catch { toast('That pattern isn’t a valid regular expression', 'bad'); return; }
      try { await api.post('/api/rules', { field: field.value, pattern: pat.value.trim(), category: cat.value }); rows.append(h('tr', {}, h('td', {}, field.value), h('td', {}, h('code', { class: 'mono' }, pat.value.trim())), h('td', {}, cat.value))); pat.value = ''; toast('Rule added; it applies to new data'); }
      catch (e) { toast(e.message, 'bad'); }
    };
    pat.addEventListener('keydown', (e) => { if (e.key === 'Enter') add(); });
    // the colour system, explained once
    const key = h('div', { class: 'st-key' }, Object.keys(DEGREE).map((c) => h('span', {}, h('i', { class: `swatch tx tx-${c.toLowerCase()}`, style: { '--c': catVar(c) } }), c, h('i', { class: 'note' }, noteOf(c)), h('small', { class: 'faint' }, FUNCTION[DEGREE[c]] || ''))));
    // weekly goal, budgets, model and host storage (all served by /api/settings)
    const wk = h('input', { class: 'input', type: 'number', min: 60, max: 4800, step: 30, value: d.settings.goal_week_min || '', 'aria-label': 'Weekly focus goal in minutes' });
    const saveWk = async () => { try { await api.post('/api/settings', { goal_week_min: Number(wk.value) }); toast(`Weekly goal: ${dur(Number(wk.value) * 60)}`); } catch (e) { toast(e.message, 'bad'); } };
    const bud = h('input', { class: 'input grow mono', value: Object.entries(d.settings.budgets || {}).map(([k, v]) => `${k}=${v}`).join(', '), placeholder: 'e.g. Build=240, Distraction=30', 'aria-label': 'Budgets as Category=minutes, comma separated', autocomplete: 'off', spellcheck: 'false' });
    const saveBud = async () => { const b = {}; for (const part of bud.value.split(',').map((x) => x.trim()).filter(Boolean)) { const [k, v] = part.split('='); b[k.trim()] = Number(v); } try { await api.post('/api/settings', { budgets: b }); toast('Budgets saved'); } catch (e) { toast(e.message, 'bad'); } };
    const mdl = h('input', { class: 'input grow mono', value: d.settings.model || 'muse-spark-1.3', 'aria-label': 'Meta model name', autocomplete: 'off', spellcheck: 'false', autocapitalize: 'off' });
    const saveMdl = async () => { try { const r = await api.post('/api/settings', { model: mdl.value.trim() }); toast(`Model: ${r.model}`); } catch (e) { toast(e.message, 'bad'); } };
    const raw = h('input', { type: 'checkbox', 'aria-label': 'Save full detail on host' }); raw.checked = d.settings.save_raw_on_host !== false;
    raw.addEventListener('change', async () => { try { await api.post('/api/settings', { save_raw_on_host: raw.checked }); toast(raw.checked ? 'Full detail saved on host' : 'Distilled saving: titles and domains are dropped on the host'); } catch (e) { toast(e.message, 'bad'); raw.checked = !raw.checked; } });
    return h('div', { class: 'page' }, h('div', { class: 'page-head' }, h('div', { class: 'grow' }, h('h1', {}, 'Settings'))),
      h('div', { class: 'grid g2' },
        h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'Daily focus goal')), h('div', { class: 'row' }, out, h('small', { class: 'faint' }, 'saved as you move it')), range),
        h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'Appearance')), seg, h('p', { class: 'faint st-note' }, 'Focus and Break sessions switch the whole app into their own darker key, whatever you choose here.'))),
      h('div', { class: 'grid g2' },
        h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'Weekly goal & budgets')), h('div', { class: 'row wrap' }, wk, h('small', { class: 'faint' }, 'minutes / week'), h('button', { class: 'btn', onclick: saveWk }, 'Save weekly')),
          h('div', { class: 'row wrap st-add' }, bud, h('button', { class: 'btn', onclick: saveBud }, 'Save budgets')), h('p', { class: 'faint st-note' }, 'Budgets are Category=minutes for the week. Leave a category out to remove its budget.')),
        h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'Meta model & host storage')), h('div', { class: 'row wrap st-add' }, mdl, h('button', { class: 'btn', onclick: saveMdl }, 'Save model')),
          h('p', { class: 'faint st-note' }, 'Any Meta model (muse-, sam-, llama-…). Cost is only estimated for priced models; every call stays in the ledger under the daily cap.'),
          h('label', { class: 'row' }, raw, h('span', {}, 'Save full detail on host (window titles and domains)'), h('small', { class: 'faint' }, 'Untick for distilled saving on the host.')))),
      h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'Category rules'), h('small', {}, 'first match wins')), h('div', { class: 'row wrap st-add' }, field, pat, cat, h('button', { class: 'btn', onclick: add }, 'Add rule')),
        d.rules.length ? h('div', { class: 'tablewrap' }, h('table', { class: 't' }, h('thead', {}, h('tr', {}, h('th', {}, 'Match on'), h('th', {}, 'Pattern'), h('th', {}, 'Category'))), rows)) : h('p', { class: 'muted' }, 'No custom rules: built-in categories apply.')),
      h('section', { class: 'card' }, h('header', {}, h('h3', {}, 'Colour key'), h('small', {}, 'each category is a note above the tonic D')), key));
  },
};
