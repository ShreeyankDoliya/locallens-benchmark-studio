const $ = (selector) => document.querySelector(selector);
const colors = ['#4e7961', '#be9768', '#528b9e', '#9a769d', '#788e47', '#b77275'];
const labels = { instruction_following: 'Instruction following', structured_output: 'Structured output', reasoning: 'Reasoning', grounding: 'Context grounding', code: 'Code tracing' };
const state = { index: [], primary: null, comparison: null, rows: [], filtered: [], series: [], request: 0 };
const cache = new Map();
const pct = value => value == null ? '—' : `${(value * 100).toFixed(1)}%`;
const ms = value => value == null ? '—' : value < 1000 ? `${value.toFixed(1)} ms` : `${(value / 1000).toFixed(2)} s`;
const el = (tag, text, cls) => { const node = document.createElement(tag); if (text != null) node.textContent = text; if (cls) node.className = cls; return node; };
const option = (value, text) => { const node = el('option', text); node.value = value; return node; };
function dot(color) { const node = el('span', null, 'model-dot'); node.style.background = color; return node; }
function validateReport(data) {
  if (data.schema_version !== 1 || !data.run?.snapshot?.tasks || !Array.isArray(data.results) || !Array.isArray(data.summary?.models)) throw new Error('Unsupported report format');
  return data;
}
async function json(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Could not load ${path} (HTTP ${response.status})`);
  return response.json();
}
function safeFile(file) {
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]*\.(json|md)$/.test(file)) throw new Error('Invalid report filename');
  return `data/${file}`;
}
async function load(id) {
  if (!cache.has(id)) {
    const entry = state.index.find(r => r.id === id);
    if (!entry) throw new Error('Run not found');
    cache.set(id, validateReport(await json(safeFile(entry.file))));
  }
  return cache.get(id);
}
function legend(series) {
  const container = el('div', null, 'legend');
  for (const s of series) { const label = el('span'); label.append(dot(s.color), document.createTextNode(s.label)); container.append(label); }
  return container;
}
async function selectRuns() {
  const request = ++state.request;
  try {
    const primary = await load($('#run-select').value);
    const comparison = $('#compare-select').value ? await load($('#compare-select').value) : null;
    if (request !== state.request) return;
    state.primary = primary; state.comparison = comparison;
    render();
  } catch (error) {
    if (request !== state.request) return;
    $('#notice').className = 'notice error';
    $('#notice').textContent = error.message + '. Preview with a local HTTP server; do not open index.html as a file.';
  }
}
function render() {
  const data = state.primary, run = data.run, snap = run.snapshot;
  const datasets = [data, ...(state.comparison && state.comparison.run.id !== run.id ? [state.comparison] : [])];
  state.series = datasets.flatMap((d, index) => d.summary.models.map(m => ({ ...m, data: d, label: `${m.model_id}${datasets.length > 1 ? ` · ${d.run.id}` : ''}`, runLabel: index ? 'Comparison' : 'Primary' }))).map((s, i) => ({ ...s, color: colors[i % colors.length] }));
  state.rows = state.series.flatMap(s => s.data.results.filter(r => r.model_id === s.model_id).map(r => ({ ...r, series: s, task: s.data.run.snapshot.tasks.find(t => t.id === r.task_id), disagreement: s.data.summary.disagreements.includes(r.task_id) })));
  const synthetic = Object.values(snap.model_manifests).some(m => m.synthetic);
  $('#notice').className = 'notice';
  $('#notice').replaceChildren(el('strong', synthetic ? 'Scripted demo results. ' : 'Local model results. '), document.createTextNode(synthetic ? 'Mock responses and delays demonstrate the workflow. They do not measure LLM quality or inference speed.' : 'Results reflect this dataset, configuration, and machine. They do not establish overall model superiority.'));
  if (run.status !== 'completed') $('#notice').append(document.createTextNode(' This run is incomplete; scores use completed tasks only.'));
  $('#run-meta').replaceChildren(document.createTextNode(`${snap.dataset_version} · ${run.status}`), el('br'), document.createTextNode(new Date(run.created_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })));
  const entry = state.index.find(r => r.id === run.id);
  $('#download-report').href = safeFile(entry.report);
  $('#download-json').href = safeFile(entry.file);
  const note = $('#comparison-note'); note.hidden = datasets.length < 2;
  if (!note.hidden) {
    const other = datasets[1].run.snapshot;
    const differences = [];
    if (other.dataset_sha256 !== snap.dataset_sha256) differences.push('datasets');
    if (other.scorer_version !== snap.scorer_version) differences.push('scoring versions');
    if (JSON.stringify(other.hardware) !== JSON.stringify(snap.hardware) || other.config.hardware_notes !== snap.config.hardware_notes) differences.push('hardware descriptions');
    if (other.config_sha256 !== snap.config_sha256) differences.push('configurations');
    note.textContent = differences.length ? `Comparison context differs: ${differences.join(', ')}. Inspect provenance before interpreting score or speed differences. Summary cards describe the primary run.` : 'Matching dataset, scoring version, configuration, and recorded hardware. Summary cards describe the primary run. Timings can still vary.';
  }
  const completed = data.results.length, failures = data.results.filter(r => !r.judgment.passed).length;
  const metricData = [ ['Models evaluated', `${data.summary.models.length}`.padStart(2, '0'), 'Same task set · recorded settings', '◈'], ['Task results', `${completed}`, `${snap.tasks.length} tasks × ${snap.config.models.length} models · ${snap.tasks.length * snap.config.models.length - completed} pending`, '▦'], ['Results to inspect', `${failures}`.padStart(2, '0'), `${data.summary.disagreements.length} tasks with model disagreement`, '⌕'], ['Inference API fees', '$0', 'Local compute · energy cost not measured', '↗'] ];
  $('#metrics').replaceChildren(...metricData.map(([label, value, sub, symbol]) => { const card = el('div', null, 'metric'), head = el('div', label, 'metric-label'); head.append(el('span', symbol, 'metric-symbol')); card.append(head, el('div', value, 'metric-value'), el('div', sub, 'metric-sub')); return card; }));
  renderModelTable(); renderCategories(); renderLatency(); renderConsistency();
  const modelFilter = $('#model-filter'), categoryFilter = $('#category-filter');
  const previousModel = modelFilter.value, previousCategory = categoryFilter.value;
  modelFilter.replaceChildren(option('', 'All models'), ...[...new Set(state.series.map(s => s.model_id))].map(m => option(m, m)));
  categoryFilter.replaceChildren(option('', 'All categories'), ...[...new Set(state.rows.map(r => r.task.category))].sort().map(c => option(c, labels[c] || c)));
  if ([...modelFilter.options].some(o => o.value === previousModel)) modelFilter.value = previousModel;
  if ([...categoryFilter.options].some(o => o.value === previousCategory)) categoryFilter.value = previousCategory;
  $('#provenance').textContent = JSON.stringify(datasets.map(d => ({ run: d.run.id, status: d.run.status, created_at: d.run.created_at, updated_at: d.run.updated_at, ...d.run.snapshot, tasks: `${d.run.snapshot.tasks.length} tasks; included in raw JSON` })), null, 2);
  renderRows();
}
function renderModelTable() {
  $('#model-table tbody').replaceChildren(...state.series.map(s => {
    const row = el('tr'), name = el('td'), title = el('div', null, 'model-name');
    title.append(dot(s.color), document.createTextNode(s.model_id));
    const manifest = s.data.run.snapshot.model_manifests[s.model_id];
    name.append(title, el('small', `${s.data.run.id} · ${manifest.synthetic ? 'SCRIPTED' : manifest.digest.slice(0, 12)}`));
    const score = el('td', null, 'score-cell'), line = el('div', null, 'score-line'), bar = el('div', null, 'score-bar'), fill = el('div', null, 'score-fill');
    fill.style.width = `${(s.pass_rate || 0) * 100}%`; fill.style.background = s.color; bar.append(fill); line.append(el('span', pct(s.pass_rate), 'score-number'), bar); score.append(line);
    const cost = s.cost_usd == null ? 'Not estimated' : `$${s.cost_usd.toFixed(6)}`;
    const costCell = el('td', cost, 'subtle'); costCell.title = `Usage/pricing coverage: ${s.cost_covered_results}/${s.completed}. Electricity and hardware excluded.`;
    row.append(name, score, el('td', `${s.passed} / ${s.completed}${s.completed !== s.planned ? ` (${s.planned} planned)` : ''}`, 'mono'), el('td', ms(s.latency_ms.p50), 'mono'), el('td', ms(s.latency_ms.p95), 'mono'), el('td', pct(s.error_rate), 'mono'), costCell);
    return row;
  }));
}
function renderCategories() {
  const root = $('#category-chart'); root.replaceChildren();
  const categories = [...new Set(state.series.flatMap(s => Object.keys(s.categories)))];
  for (const category of categories) {
    const row = el('div', null, 'category-row'), label = el('div', null, 'category-label');
    label.append(el('span', labels[category] || category), el('span', state.series.map(s => pct(s.categories[category]?.pass_rate)).join(' / '), 'mono'));
    const bars = el('div', null, 'category-bars');
    for (const s of state.series) { const track = el('div', null, 'category-track'), fill = el('div', null, 'category-fill'); fill.style.width = `${(s.categories[category]?.pass_rate || 0) * 100}%`; fill.style.background = s.color; track.title = `${s.label}: ${pct(s.categories[category]?.pass_rate)}`; track.append(fill); bars.append(track); }
    row.append(label, bars); root.append(row);
  }
  root.append(legend(state.series));
}
function renderLatency() {
  const all = state.rows.filter(r => !r.error).map(r => r.latency_ms);
  const root = $('#latency-chart'); root.replaceChildren();
  if (!all.length) { root.append(el('p', 'No successful request timings yet.', 'subtle')); return; }
  const max = Math.max(...all, 1), bins = 8;
  const counts = state.series.map(s => {
    const values = Array(bins).fill(0);
    s.data.results.filter(r => r.model_id === s.model_id && !r.error).forEach(r => values[Math.min(bins - 1, Math.floor(r.latency_ms / max * bins))]++);
    return values;
  });
  const peak = Math.max(...counts.flat(), 1), chart = el('div', null, 'histogram');
  chart.setAttribute('role', 'img');
  chart.setAttribute('aria-label', `Latency histogram, eight equal-width buckets from zero to ${ms(max)}. ${state.series.map((s, i) => `${s.label} counts: ${counts[i].join(', ')}`).join('. ')}`);
  for (let bin = 0; bin < bins; bin++) {
    const group = el('div', null, 'histogram-bin');
    state.series.forEach((s, i) => { const bar = el('div', null, 'histogram-bar'); bar.style.height = `${counts[i][bin] / peak * 100}%`; bar.style.background = s.color; bar.title = `${s.label}: ${counts[i][bin]} requests, ${ms(bin / bins * max)}–${ms((bin + 1) / bins * max)}`; group.append(bar); }); chart.append(group);
  }
  const axis = el('div', null, 'axis'); axis.append(el('span', '0 ms'), el('span', ms(max / 2)), el('span', ms(max)));
  root.append(chart, axis, legend(state.series));
}
function renderConsistency() {
  $('#consistency').replaceChildren(...state.series.map(s => { const box = el('div'), title = el('span'); title.append(dot(s.color), document.createTextNode(` ${s.label}`)); box.append(title, el('strong', `${s.consistency.same_pass_outcome}/${s.consistency.complete_groups}`), el('span', `${s.consistency.all_pass} groups passed every variant`, 'subtle')); return box; }));
}
function renderRows() {
  const term = $('#search').value.toLocaleLowerCase(), model = $('#model-filter').value, category = $('#category-filter').value, outcome = $('#outcome-filter').value;
  state.filtered = state.rows.filter(r => (!model || r.model_id === model) && (!category || r.task.category === category) && (!term || `${r.task_id} ${r.task.prompt} ${r.response || ''}`.toLocaleLowerCase().includes(term)) && (!outcome || (outcome === 'failed' && !r.judgment.passed) || (outcome === 'passed' && r.judgment.passed) || (outcome === 'error' && r.error) || (outcome === 'disagreement' && r.disagreement)));
  $('#result-count').textContent = `${state.filtered.length} of ${state.rows.length} results`;
  $('#empty').hidden = state.filtered.length > 0;
  $('#task-table tbody').replaceChildren(...state.filtered.map(r => {
    const row = el('tr'), task = el('td'); task.append(el('div', r.task_id, 'task-id'), el('div', r.task.variant.replaceAll('_', ' '), 'variant'));
    const model = el('td'), name = el('div', null, 'model-name'); name.append(dot(r.series.color), document.createTextNode(r.model_id)); model.append(name, el('small', r.run_id));
    const outcome = el('td'); outcome.append(el('span', r.error ? '● Error' : r.judgment.passed ? '✓ Pass' : '× Fail', `badge ${r.error ? 'error' : r.judgment.passed ? 'pass' : 'fail'}`));
    const action = el('td'), button = el('button', 'Inspect ↗', 'inspect-button'); button.setAttribute('aria-label', `Inspect ${r.task_id} for ${r.model_id} in ${r.run_id}`); button.addEventListener('click', () => showDetail(r)); action.append(button);
    row.append(task, model, el('td', labels[r.task.category] || r.task.category, 'subtle'), outcome, el('td', ms(r.latency_ms), 'mono'), action); return row;
  }));
}
function showDetail(r) {
  $('#detail-title').textContent = r.task_id;
  const content = $('#detail-content'); content.replaceChildren(el('div', `${r.model_id} · ${r.run_id} · ${r.task.variant.replaceAll('_', ' ')} · ${r.attempts.length} attempt(s) · ${ms(r.latency_ms)}`, 'detail-meta'));
  const grid = el('div', null, 'detail-grid');
  const block = (title, value, full = false) => { const section = el('section', null, `detail-block${full ? ' full' : ''}`); section.append(el('h3', title), el('pre', typeof value === 'string' ? value : JSON.stringify(value, null, 2))); grid.append(section); };
  block('Exact prompt', r.task.prompt, true);
  block('Expected answer', r.task.expected);
  block('Raw response', r.response ?? '(No response saved)');
  block('Deterministic judgment', `${r.judgment.explanation}\nRule: ${r.task.rubric}\nScorer: ${r.judgment.version} · Method: ${r.judgment.method}`, true);
  if (r.error) block('Provider error', r.error, true);
  const config = r.series.data.run.snapshot.config.models.find(m => m.id === r.model_id);
  block('Model & generation settings', { ...config, manifest: r.series.data.run.snapshot.model_manifests[r.model_id] }, true);
  block('Tokens & provider metadata', { input_tokens: r.input_tokens, output_tokens: r.output_tokens, ...r.provider_metadata }, true);
  block('Attempt history', r.attempts, true);
  content.append(grid); $('#detail-dialog').showModal();
}
$('#run-select').addEventListener('change', selectRuns);
$('#compare-select').addEventListener('change', selectRuns);
for (const id of ['search', 'model-filter', 'category-filter', 'outcome-filter']) $(`#${id}`).addEventListener(id === 'search' ? 'input' : 'change', renderRows);
$('#clear-filters').addEventListener('click', () => { for (const id of ['search', 'model-filter', 'category-filter', 'outcome-filter']) $(`#${id}`).value = ''; renderRows(); });
$('#close-dialog').addEventListener('click', () => $('#detail-dialog').close());
$('#detail-dialog').addEventListener('click', event => { if (event.target === $('#detail-dialog')) { const rect = event.target.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) event.target.close(); } });
for (const link of document.querySelectorAll('.nav-link')) link.addEventListener('click', () => { document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active')); link.classList.add('active'); });
try {
  const index = await json('data/index.json');
  if (index.schema_version !== 1 || !Array.isArray(index.runs) || !index.runs.length) throw new Error('No published runs. Run llm-bench export first');
  state.index = index.runs;
  $('#run-count').textContent = String(index.runs.length).padStart(2, '0');
  $('#run-select').replaceChildren(...index.runs.map(r => option(r.id, `${r.name} · ${r.id}`)));
  $('#compare-select').append(...index.runs.map(r => option(r.id, `${r.name} · ${r.id}`)));
  await selectRuns();
} catch (error) { $('#notice').className = 'notice error'; $('#notice').textContent = error.message; }
