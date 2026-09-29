import { enhanceSelects, refreshSelects } from './select.js';

const $ = s => document.querySelector(s);
const el = (tag, text, cls) => { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; };
function link(label, url) {
  const a = el('a', label); const parsed = new URL(url, location.href);
  if (parsed.protocol !== 'https:') throw new Error('Research source links must use HTTPS');
  a.href = parsed.href; a.target = '_blank'; a.rel = 'noopener'; return a;
}
async function json(path) { const r = await fetch(path); if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`); return r.json(); }
function detail(title, sections) {
  $('#research-detail-title').textContent = title;
  const root = $('#research-detail-content'); root.replaceChildren();
  for (const [heading, value] of sections) {
    const block = el('section', null, 'detail-block');
    block.append(el('h3', heading), value instanceof Node ? value : el('pre', typeof value === 'string' ? value : JSON.stringify(value, null, 2)));
    root.append(block);
  }
  $('#research-dialog').showModal();
}
$('#close-research-dialog').addEventListener('click', () => $('#research-dialog').close());

try {
  const [catalog, inventory, controls, access, measured] = await Promise.all([json('research/catalog.json'), json('research/terminal-tasks.json'), json('research/controls.json'), json('research/access.json'), json('research/measurements.json')]);
  if (catalog.schema_version !== 1 || inventory.tasks.length !== 89 || controls.kind !== 'harness_controls') throw new Error('Unsupported research evidence');
  $('#research-status').textContent = catalog.evaluation_status;
  $('#reviewed-on').textContent = `Sources reviewed ${catalog.reviewed_on}`;
  const cards = [['Research benchmarks', catalog.benchmarks.length, 'Distinct papers and evaluation protocols'], ['Native terminal tasks', inventory.tasks.length, 'Pinned release · file hashes recorded'], ['Measured GLM runs', catalog.measured_glm_runs.length, 'Two saved jobs · inspectable results'], ['Local harness controls', controls.results.length, 'Reference solution + no-op baseline']];
  $('#research-metrics').replaceChildren(...cards.map(([name, value, sub]) => { const c = el('div', null, 'metric'); c.append(el('div', name, 'metric-label'), el('div', value, 'metric-value'), el('div', sub, 'metric-sub')); return c; }));
  renderMeasured(measured);
  if (access.kind !== 'provider_access_checks' || access.benchmark_results !== false) throw new Error('Access checks must not be benchmark scores');
  for (const check of access.results) {
    const row = el('tr');
    row.append(el('td', check.model, 'task-id'), el('td', check.status, 'mono'), el('td', `${check.endpoint.includes('/coding/') ? 'Coding Plan' : 'Standard'} · ${check.returned_model || (check.code ? `HTTP ${check.http_status} / ${check.code}` : 'unknown')}`, 'mono'), el('td', 'Not scored', 'subtle'));
    $('#access-table tbody').append(row);
  }
  const accessDownload = el('a', 'Download access evidence ↗'); accessDownload.href = 'research/access.json'; accessDownload.download = 'access.json';
  $('#access-note').append(document.createTextNode(access.note + ' '), accessDownload);
  const vendors = catalog.published_scores.filter(s => s.origin === 'vendor_reported');
  for (const benchmark of [...new Set(vendors.map(s => s.benchmark))]) {
    const scores = vendors.filter(s => s.benchmark === benchmark), first = scores[0], row = el('tr'), action = el('td'), button = el('button', 'Inspect source ↗', 'inspect-button');
    button.setAttribute('aria-label', `Inspect source for ${benchmark}`);
    button.addEventListener('click', () => detail(benchmark, [
      ['Evidence type', 'Vendor-reported. LocalLens has not reproduced this score and has no individual model responses for it.'],
      ['Reported scores', scores.map(s => `${s.model}: ${s.score.toFixed(1)} · ${s.metric}`).join('\n')],
      ['Protocol note', first.protocol], ['Published / retrieved', `${first.source_date} / ${catalog.reviewed_on}`],
      ['Primary source', link('Z.ai model release and evaluation footnotes ↗', first.source)],
      ['Comparison boundary', 'Versions and agent settings differ from the January 2026 Terminal-Bench 2.0 paper. Do not compare these rows as if they used identical tasks or compute.']
    ]));
    action.append(button);
    row.append(el('td', benchmark, 'task-id'), ...['GLM-5.3', 'GLM-5.2'].map(model => el('td', scores.find(s => s.model === model)?.score.toFixed(1) ?? 'Not reported', 'mono')), el('td', first.metric, 'subtle'), action);
    $('#reference-table tbody').append(row);
  }
  const paper = catalog.published_scores.find(s => s.origin === 'paper_reported');
  $('#paper-reference').append(el('strong', `Historical paper result: ${paper.model} + Terminus 2 · ${paper.score}% ± 2.4 pp`), el('p', 'Terminal-Bench 2.0 · authors’ reported 95% confidence interval. This is a different version and protocol from the vendor table. It is not a result from this machine.'), link('Table 2, page 81 ↗', paper.source));
  for (const c of controls.results) {
    const card = el('div', null, 'panel control-check'), button = el('button', 'Inspect verifier evidence ↗', 'inspect-button'), passed = c.tests.filter(t => t.status === 'passed').length;
    card.append(el('div', c.agent === 'oracle' ? 'REFERENCE SOLUTION' : 'NO-OP CONTROL', 'eyebrow'), el('h3', c.agent === 'oracle' ? 'The supplied solution passes.' : 'Doing nothing fails.'), el('div', `${passed}/${c.tests.length} tests passed · reward ${c.reward}`, 'mono'), el('p', c.task_id, 'subtle'), button);
    button.addEventListener('click', () => detail(`${c.agent} · ${c.task_id}`, [['What this establishes', controls.note], ['Exact task instruction', c.prompt], ['Agent output', c.response], ['Expected result and judgment', c.explanation], ['Individual verifier checks', c.tests], ['Recorded provenance', { ...c, prompt: undefined, response: undefined, tests: undefined, revision: controls.revision, harness: controls.harness }]]));
    $('#control-checks').append(card);
  }
  for (const b of catalog.benchmarks) {
    const card = el('article', null, 'panel paper-card'), links = el('div', null, 'paper-links'), details = el('details');
    links.append(link('Research paper ↗', b.paper), link('Official tasks ↗', b.repository));
    details.append(el('summary', 'Protocol & limitations'), el('h4', b.paper_title), el('p', b.protocol), el('h4', 'What it cannot establish'), el('p', b.limitations));
    card.append(el('div', b.scope, 'eyebrow'), el('h3', b.name), el('p', b.measures), links, details, el('div', b.status, 'paper-status'));
    $('#paper-grid').append(card);
  }
  const category = $('#native-category');
  [...new Set(inventory.tasks.map(t => t.category))].sort().forEach(c => { const o = el('option', c.replaceAll('-', ' ')); o.value = c; category.append(o); });
  function tasks() {
    const term = $('#native-search').value.toLocaleLowerCase();
    const rows = inventory.tasks.filter(t => (!category.value || t.category === category.value) && (!term || `${t.id} ${t.category}`.toLocaleLowerCase().includes(term)));
    $('#native-count').textContent = `${rows.length} / 89 tasks`; $('#native-empty').hidden = rows.length > 0;
    $('#native-table tbody').replaceChildren(...rows.map(t => {
      const tr = el('tr'), name = el('td'), source = el('td', null, 'task-source-links');
      name.append(el('div', t.id, 'task-id'), el('div', t.difficulty, 'variant'));
      const base = `https://github.com/harbor-framework/terminal-bench-2/blob/${inventory.revision}/${encodeURIComponent(t.id)}`;
      source.append(link('Prompt ↗', `${base}/instruction.md`), link('Verifier ↗', `${base}/tests/test.sh`));
      tr.append(name, el('td', t.category, 'subtle'), el('td', `${t.environment.cpus} / ${t.environment.memory}`, 'mono'), el('td', `${t.agent_timeout_sec / 60} min`, 'mono'), source); return tr;
    }));
  }
  $('#native-search').addEventListener('input', tasks); category.addEventListener('change', tasks);
  $('#source-pins').textContent = JSON.stringify({ terminal_bench_revision: inventory.revision, datasets: catalog.sources }, null, 2);
  enhanceSelects(); refreshSelects(); tasks();
} catch (error) { $('#research-status').className = 'notice error'; $('#research-status').textContent = `Research evidence could not load: ${error.message}. Serve the dashboard over HTTP.`; }

function renderMeasured(data) {
  if (data.kind !== 'measured_research_pilot' || data.origin !== 'measured') throw new Error('Expected measured evidence');
  $('#pilot-scope').textContent = data.scope + ' ' + data.model_identity_note;
  $('#pilot-caveats').textContent = 'Interpretation notes: ' + data.dataset_notes.join(' ');
  $('#pilot-provenance').textContent = JSON.stringify({hardware: data.native_run.snapshot.hardware, settings: data.native_run.snapshot.settings, terminal: data.terminal_run, dataset_notes: data.dataset_notes, billing: data.billing, evidence_sha256: data.evidence_sha256}, null, 2);
  const labels = Object.fromEntries(data.summary.map(s => [s.benchmark, s.label]));
  function inspect(r) {
    detail(`${labels[r.benchmark]} · ${r.task_id} · ${r.model}`, [
      ['Measured result', `${r.passed ? 'PASS' : 'FAIL'} · ${r.judgment.method}. ${r.protocol}`],
      [r.benchmark === 'terminal-bench' ? 'Task instruction (full model requests in recorded evidence)' : 'Exact prompt', r.prompt], ['Model response / agent trajectory', r.response ?? 'No response'],
      ['Expected result', r.expected], ['Judgment and scoring explanation', r.judgment],
      ['Dataset / interpretation caveat', r.dataset_caveat || 'No task-specific caveat recorded; general benchmark limitations still apply.'],
      ['Recorded evidence', {error:r.error, input_tokens:r.input_tokens, output_tokens:r.output_tokens, latency_ms:r.latency_ms, latency_kind:r.latency_kind, source_revision:r.source_revision, ...r.evidence}]
    ]);
  }
  for (const s of data.summary) {
    const tr = el('tr'), name = el('td'), action = el('td'), button = el('button', 'Inspect protocol ↗', 'inspect-button');
    name.append(el('div', s.label, 'task-id'), el('div', s.model, 'variant'));
    if (s.benchmark === 'ifeval') name.append(el('div', 'strict prompt accuracy', 'variant'));
    button.setAttribute('aria-label', `Inspect ${s.label} ${s.model} protocol`);
    button.addEventListener('click', () => detail(`${s.label} · ${s.model}`, [['Measured subset', `${s.passed}/${s.completed} passed, ${s.errors} errors. One completion/trial per task. No universal model ranking.`], ['Protocol', data.results.find(r => r.benchmark === s.benchmark && r.model === s.model).protocol], ['Aggregate metrics', s], ['Generation settings', data.native_run.snapshot.settings], ['Billing', data.billing]]));
    action.append(button);
    const plotCell = el('td'), plot = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    plot.setAttribute('viewBox','0 0 160 28'); plot.setAttribute('class','latency-dots'); plot.setAttribute('role','img');
    const times = s.latency_ms.samples, max = Math.max(...times, 1);
    plot.setAttribute('aria-label', `${s.completed} task latencies, 0 to ${(max/1000).toFixed(1)} seconds; ${s.latency_kind}`);
    const line = document.createElementNS(plot.namespaceURI,'line'); for (const [k,v] of Object.entries({x1:5,x2:155,y1:14,y2:14})) line.setAttribute(k,v); plot.append(line);
    for (const t of times) { const dot=document.createElementNS(plot.namespaceURI,'circle'); dot.setAttribute('cx',5+150*t/max); dot.setAttribute('cy',14); dot.setAttribute('r',3); const title=document.createElementNS(plot.namespaceURI,'title'); title.textContent=`${(t/1000).toFixed(2)} seconds`; dot.append(title); plot.append(dot); }
    plotCell.append(plot);
    const timing = s.latency_ms.p50 == null ? 'unknown' : `${(s.latency_ms.p50/1000).toFixed(1)} / ${(s.latency_ms.p95/1000).toFixed(1)} s`;
    tr.append(name, el('td', `${s.passed}/${s.completed} · ${(s.pass_rate*100).toFixed(0)}%`, 'mono'), plotCell, el('td',timing,'mono'), el('td', `${(s.error_rate*100).toFixed(0)}%`, 'mono'),action); $('#measured-table tbody').append(tr);
  }
  for (const [id, values] of [['pilot-benchmark', Object.keys(labels)], ['pilot-model', [...new Set(data.results.map(r=>r.model))]]]) {
    for (const value of values) { const o=el('option', labels[value] || value); o.value=value; $('#'+id).append(o); }
  }
  function draw() {
    const rows=data.results.filter(r => (!$('#pilot-benchmark').value || r.benchmark === $('#pilot-benchmark').value) && (!$('#pilot-model').value || r.model === $('#pilot-model').value) && (!$('#pilot-outcome').value || ($('#pilot-outcome').value === 'fail' ? !r.passed : r.disagreement)));
    $('#pilot-count').textContent=`${rows.length} / ${data.results.length} results`; $('#pilot-empty').hidden=rows.length>0;
    $('#pilot-results tbody').replaceChildren(...rows.map(r => {const tr=el('tr'), action=el('td'), button=el('button','Inspect result ↗','inspect-button'); button.setAttribute('aria-label',`Inspect ${r.benchmark} ${r.task_id} ${r.model}`); button.addEventListener('click',()=>inspect(r)); action.append(button); tr.append(el('td',`${labels[r.benchmark]} · ${r.task_id}`,'task-id'),el('td',r.model,'mono'),el('td',r.passed?'PASS':'FAIL',r.passed?'pilot-pass':'pilot-fail'),el('td',r.latency_ms == null ? 'unknown' : `${(r.latency_ms/1000).toFixed(1)} s`,'mono'),action);return tr;}));
  }
  for (const id of ['pilot-benchmark','pilot-model','pilot-outcome']) $('#'+id).addEventListener('change',draw);
  draw();
}
