// Speech Lab front-end: sliders -> /api/generate -> /api/score -> highlights + comparison.
const TRAITS = {
  BACE: ['Belief in ability to control events', 'High: takes charge, shapes outcomes. Low: reactive, events beyond control.'],
  PWR:  ['Need for power', 'High: dominates, asserts authority. Low: collaborative, shares influence.'],
  CC:   ['Conceptual complexity', 'High: nuance, trade-offs, uncertainty. Low: absolutes, black-and-white.'],
  SC:   ['Self-confidence', 'High: self-assured, personal authority. Low: self-doubt, defers.'],
  TASK: ['Task focus', 'High: problems, goals, getting things done. Low: people, morale, unity.'],
  DIS:  ['Distrust of others', 'High: suspicion, enemies, hidden agendas. Low: trusting, partners.'],
  IGB:  ['In-group bias', 'High: us-vs-them, national pride. Low: inclusive, shared humanity.'],
};
// What each highlight label means, per mode.
const POLE_NAMES = {
  scorer: { 'CC:high': 'complex', 'CC:low': 'simple', 'SC:high': 'confident', 'SC:low': 'hedging',
            'TASK:high': 'problem-solving', 'TASK:low': 'relationship' },
  intended: {},
};
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
let cuts = { high: 84, low: 16 };
// CC, SC and TASK: two word lists compete, so 50 is the dividing line.
const TWO_LIST = { CC: ['High', 'Low', 'Moderate'], SC: ['High', 'Low', 'Moderate'],
                   TASK: ['Problem-solving', 'Relationship-building', 'Balanced'] };
const bandOf = (t, v) => {
  const two = TWO_LIST[t];
  if (two) return v > 50 ? two[0] : v < 50 ? two[1] : two[2];
  return v > cuts.high ? 'High' : v < cuts.low ? 'Low' : 'Moderate';
};

const state = {
  targets: Object.fromEntries(Object.keys(TRAITS).map((t) => [t, 50])),
  gen: null,        // last /api/generate result
  run: null,        // last /api/score result
  mode: 'scorer',
  hidden: new Set(),
  editing: false,
};

// ---------------------------------------------------------------- sliders
function buildSliders() {
  $('#sliders').innerHTML = Object.entries(TRAITS).map(([t, [name, desc]]) => `
    <div class="slider">
      <div class="slider-top">
        <span class="swatch" style="background:var(--${t})"></span>
        <b>${t}</b><span class="name">${name}</span>
        <span class="chip" id="chip-${t}"></span>
        <span class="val" id="val-${t}"></span>
      </div>
      <input type="range" min="0" max="100" step="1" id="rng-${t}" aria-label="${name}">
      <div class="desc">${desc}</div>
    </div>`).join('');
  for (const t of Object.keys(TRAITS)) {
    $(`#rng-${t}`).addEventListener('input', (e) => { state.targets[t] = +e.target.value; syncSlider(t); });
  }
  syncSliders();
}
function syncSlider(t) {
  const v = state.targets[t];
  $(`#rng-${t}`).value = v;
  $(`#val-${t}`).textContent = v;
  const chip = $(`#chip-${t}`);
  chip.textContent = bandOf(t, v);
  chip.className = `chip ${bandOf(t, v)}`;
}
const syncSliders = () => Object.keys(TRAITS).forEach(syncSlider);

// Spread random profiles over all three bands so tests cover extremes too.
function randomLevel() {
  const r = Math.random();
  if (r < 0.3) return 3 + Math.floor(Math.random() * 13);   // Low
  if (r < 0.6) return 86 + Math.floor(Math.random() * 12);  // High
  return 20 + Math.floor(Math.random() * 61);               // Moderate
}

// ---------------------------------------------------------------- API
async function api(path, body) {
  const res = await fetch(path, body ? {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  } : undefined);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : `HTTP ${res.status}`);
  return data;
}

function busy(on, msg = '') {
  for (const id of ['#btn-generate', '#btn-rescore', '#btn-random', '#btn-reset']) $(id).disabled = on;
  $('#progress').innerHTML = msg;
}

async function generateAndScore() {
  const body = { targets: { ...state.targets }, language: $('#language').value,
                 topic: $('#topic').value, words: +$('#words').value || 600 };
  setEditing(false);
  busy(true, 'Writing the speech… (can take up to a minute if the AI is rate-limited)');
  try {
    state.gen = await api('/api/generate', body);
    state.run = null;
    renderSpeech();
    await score(state.gen.speech, body, false);
  } catch (e) {
    busy(false, `<span class="err">${esc(e.message)}</span>`);
  }
}

async function score(text, body, edited) {
  busy(true, 'Scoring with the dictionary and the AI…');
  try {
    const g = state.gen || {};
    state.run = await api('/api/score', {
      text, targets: body.targets, language: body.language, topic: body.topic, edited,
      meta: { model: g.model, title: g.title, markers_found: g.markers_found, markers_total: g.markers_total },
    });
    if (edited && state.gen) { state.gen = { ...state.gen, speech: text, intended: [] }; }
    renderSpeech();
    renderResults();
    loadRuns();
    busy(false, state.run.ai_error ? `<span class="err">AI scorer: ${esc(state.run.ai_error)}</span> Dictionary results are shown.` : '');
  } catch (e) {
    busy(false, `<span class="err">${esc(e.message)}</span>`);
  }
}

// ---------------------------------------------------------------- highlights
function spansFor(mode) {
  if (mode === 'scorer') return state.run?.scorer_spans || [];
  if (mode === 'intended') return state.gen?.intended || [];
  return [];
}

function renderLegend(spans) {
  const counts = {};
  for (const s of spans) for (const l of s.labels) counts[l] = (counts[l] || 0) + 1;
  const labels = Object.keys(counts).sort((a, b) => Object.keys(TRAITS).indexOf(a.split(':')[0]) - Object.keys(TRAITS).indexOf(b.split(':')[0]) || a.localeCompare(b));
  if (!labels.length) {
    $('#legend').innerHTML = state.mode === 'none' ? '' :
      `<span class="hint">${state.mode === 'scorer' && !state.run ? 'Scorer highlights appear after scoring.' : 'Nothing to highlight.'}</span>`;
    return;
  }
  $('#legend').innerHTML = labels.map((l) => {
    const [t, pole] = l.split(':');
    const poleName = POLE_NAMES[state.mode][l] || pole;
    return `<label title="${esc(TRAITS[t][0])}"><input type="checkbox" data-label="${l}" ${state.hidden.has(l) ? '' : 'checked'}>
      <mark class="${pole}" style="--c:var(--${t})">${t} ${poleName}</mark><span class="count">${counts[l]}</span></label>`;
  }).join('');
  $('#legend').querySelectorAll('input').forEach((cb) => cb.addEventListener('change', () => {
    cb.checked ? state.hidden.delete(cb.dataset.label) : state.hidden.add(cb.dataset.label);
    renderSpeech();
  }));
}

// Split the text at every span boundary; each piece carries all labels covering it.
function highlighted(text, spans) {
  const active = spans.map((s) => ({ ...s, labels: s.labels.filter((l) => !state.hidden.has(l)) }))
                      .filter((s) => s.labels.length);
  const cuts = new Set([0, text.length]);
  for (const s of active) { cuts.add(s.start); cuts.add(s.end); }
  const pts = [...cuts].sort((a, b) => a - b);
  let html = '';
  for (let i = 0; i < pts.length - 1; i++) {
    const [a, b] = [pts[i], pts[i + 1]];
    const labels = [...new Set(active.filter((s) => s.start <= a && s.end >= b).flatMap((s) => s.labels))];
    const piece = esc(text.slice(a, b));
    if (!labels.length) { html += piece; continue; }
    const [t, pole] = labels[0].split(':');
    const title = labels.map((l) => { const [tt, p] = l.split(':'); return `${tt} (${TRAITS[tt][0]}) — ${POLE_NAMES[state.mode][l] || p}`; }).join('\n');
    html += `<mark class="${pole}${labels.length > 1 ? ' multi' : ''}" style="--c:var(--${t})" title="${esc(title)}">${piece}</mark>`;
  }
  return html;
}

function renderSpeech() {
  const g = state.gen;
  const box = $('#speech');
  if (!g) return;
  const text = g.speech;
  const spans = spansFor(state.mode);
  renderLegend(spans);
  box.classList.remove('empty');
  box.dir = /[؀-ۿ]/.test(text) ? 'rtl' : 'ltr';
  box.innerHTML = highlighted(text, spans);
  $('#speech-title').textContent = g.title ? `3. ${g.title}` : '3. Speech';
  const det = state.run?.detected;
  const detTxt = det ? (det.language === 'ar' ? `detected: Arabic (${det.dialect})` : 'detected: English') : '';
  $('#speech-meta').textContent = [`${g.words ?? text.split(/\s+/).length} words`, g.model && `written by ${g.model}`,
    g.markers_total ? `AI markers located ${g.markers_found}/${g.markers_total}` : '', detTxt].filter(Boolean).join(' · ');
}

function setEditing(on) {
  state.editing = on;
  $('#speech').hidden = on;
  $('#speech-edit').hidden = !on;
  $('#btn-rescore').hidden = !on;
  $('#btn-edit').textContent = on ? 'Cancel edit' : 'Edit text';
  if (on) $('#speech-edit').value = state.gen?.speech || '';
}

// ---------------------------------------------------------------- results
const fmt = (v) => (typeof v === 'number' ? Math.round(v) : '—');
function mark(targetBand, measuredBand) {
  if (!measuredBand) return '';
  return targetBand === measuredBand ? '<span class="ok">✓</span>' : '<span class="miss">✗</span>';
}

function renderResults() {
  const r = state.run;
  if (!r) return;
  const card = (k, s, label) => s ? `<div class="card"><div class="k">${label}</div>
      <div class="v">${s.band_agree}/${s.n} bands</div><div class="s">mean error ${s.mae} points</div></div>` : '';
  $('#summary').innerHTML = card('d', r.dict_summary, 'Dictionary scorer') + card('a', r.ai_summary, `AI scorer (${esc(r.ai_model || '')})`) +
    (r.ai_style ? `<div class="card"><div class="k">AI's reading of the style</div><div class="s" style="font-size:14px;color:var(--ink)">${esc(r.ai_style)}</div></div>` : '');
  $('#results').innerHTML = `
    <caption class="legend-dots" style="caption-side:top;text-align:left"><span class="t">target</span><span class="d">dictionary (CC, SC, TASK: first list's share of hits; others: percentile vs. reference speeches)</span><span class="a">AI (0–100)</span></caption>
    <tr><th>Trait</th><th>Target</th><th>Dictionary</th><th>AI</th><th>Scale</th><th>AI rationale</th></tr>` +
    r.rows.map((x) => `<tr>
      <td><b style="color:var(--${x.trait})">${x.trait}</b><br><span class="hint">${TRAITS[x.trait][0]}</span></td>
      <td class="num">${x.target} <span class="chip ${x.target_band}">${x.target_band}</span></td>
      <td class="num">${fmt(x.dict_pct)} <span class="chip ${x.dict_band}">${x.dict_band}</span> ${mark(x.target_band, x.dict_band)}
        <br><span class="hint">raw ${x.dict_value.toFixed(3)}${x.dict_confidence ? ` · ${x.dict_confidence} confidence` : ''}</span></td>
      <td class="num">${fmt(x.ai_score)} ${x.ai_band ? `<span class="chip ${x.ai_band}">${x.ai_band}</span> ${mark(x.target_band, x.ai_band)}` : ''}${x.ai_label ? `<br><span class="hint">AI's own label: ${esc(x.ai_label)}</span>` : ''}</td>
      <td><div class="bar"><i class="t" style="left:${x.target}%"></i><i class="d" style="left:${x.dict_pct}%"></i>${typeof x.ai_score === 'number' ? `<i class="a" style="left:${x.ai_score}%"></i>` : ''}</div></td>
      <td class="why">${esc(x.ai_rationale || '')}</td></tr>`).join('');
}

// ---------------------------------------------------------------- run log
async function loadRuns() {
  const runs = await api('/api/runs').catch(() => []);
  const agg = (k) => {
    const s = runs.map((r) => r[k]).filter(Boolean);
    if (!s.length) return null;
    return { mae: (s.reduce((a, x) => a + x.mae, 0) / s.length).toFixed(1),
             agree: (100 * s.reduce((a, x) => a + x.band_agree, 0) / s.reduce((a, x) => a + x.n, 0)).toFixed(0) };
  };
  const d = agg('dict_summary'), a = agg('ai_summary');
  $('#log-summary').innerHTML = runs.length ? `${runs.length} runs. ` +
    (d ? `Dictionary: ${d.agree}% bands right, mean error ${d.mae}. ` : '') +
    (a ? `AI: ${a.agree}% bands right, mean error ${a.mae}.` : '') : 'No runs yet.';
  $('#runs').innerHTML = runs.length ? `<tr><th>Time</th><th>Language</th><th>Words</th><th>Targets</th>
      <th>Dict bands</th><th>Dict error</th><th>AI bands</th><th>AI error</th><th></th></tr>` +
    runs.map((r) => `<tr data-id="${r.id}">
      <td class="num">${esc(r.time)}</td>
      <td>${esc(r.language)}${r.detected?.dialect && r.language !== 'en' ? ` <span class="hint">(${esc(r.detected.dialect)})</span>` : ''}</td>
      <td class="num">${r.words}</td>
      <td class="num">${r.rows.map((x) => `${x.trait} ${x.target}`).join(' · ')}</td>
      <td class="num">${r.dict_summary ? `${r.dict_summary.band_agree}/${r.dict_summary.n}` : '—'}</td>
      <td class="num">${r.dict_summary?.mae ?? '—'}</td>
      <td class="num">${r.ai_summary ? `${r.ai_summary.band_agree}/${r.ai_summary.n}` : '—'}</td>
      <td class="num">${r.ai_summary?.mae ?? '—'}</td>
      <td>${r.edited ? '<span class="hint">edited</span>' : ''}</td></tr>`).join('') : '';
  $('#runs').querySelectorAll('tr[data-id]').forEach((tr) => tr.addEventListener('click', () => openRun(tr.dataset.id)));
}

async function openRun(id) {
  const r = await api(`/api/runs/${id}`);
  state.run = r;
  state.gen = { speech: r.text, title: '', words: r.words, model: r.gen_model, intended: [] };
  for (const x of r.rows) state.targets[x.trait] = x.target;
  syncSliders();
  setMode('scorer');
  renderResults();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function setMode(mode) {
  state.mode = mode;
  document.querySelectorAll('.seg button').forEach((b) => b.classList.toggle('on', b.dataset.mode === mode));
  renderSpeech();
}

// ---------------------------------------------------------------- init
async function init() {
  buildSliders();
  const meta = await api('/api/meta').catch(() => null);
  if (meta) {
    cuts = meta.cuts;
    $('#cut-high').textContent = cuts.high; $('#cut-low').textContent = cuts.low;
    syncSliders();
    $('#language').innerHTML = Object.entries({ en: 'English', msa: 'Arabic — Modern Standard', egyptian: 'Arabic — Egyptian colloquial' })
      .map(([k, v]) => `<option value="${k}">${v}</option>`).join('');
    const st = $('#ai-status');
    st.textContent = meta.llm_available ? `AI: ${meta.model}` : 'AI not configured — set GROQ_API_KEY';
    st.classList.toggle('bad', !meta.llm_available);
    $('#btn-generate').disabled = !meta.llm_available;
  }
  $('#btn-random').onclick = () => { for (const t of Object.keys(TRAITS)) state.targets[t] = randomLevel(); syncSliders(); };
  $('#btn-reset').onclick = () => { for (const t of Object.keys(TRAITS)) state.targets[t] = 50; syncSliders(); };
  $('#btn-generate').onclick = generateAndScore;
  $('#btn-edit').onclick = () => setEditing(!state.editing);
  $('#btn-rescore').onclick = () => {
    const text = $('#speech-edit').value.trim();
    if (!text) return;
    if (!state.gen) state.gen = { speech: text, intended: [] };
    setEditing(false);
    score(text, { targets: { ...state.targets }, language: $('#language').value, topic: $('#topic').value }, true);
  };
  document.querySelectorAll('.seg button').forEach((b) => b.addEventListener('click', () => setMode(b.dataset.mode)));
  loadRuns();
}
init();
