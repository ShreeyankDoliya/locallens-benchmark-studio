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
  const [catalog, inventory, controls] = await Promise.all([json('research/catalog.json'), json('research/terminal-tasks.json'), json('research/controls.json')]);
  if (catalog.schema_version !== 1 || inventory.tasks.length !== 89 || controls.kind !== 'harness_controls') throw new Error('Unsupported research evidence');
  $('#research-status').textContent = catalog.evaluation_status;
  $('#reviewed-on').textContent = `Sources reviewed ${catalog.reviewed_on}`;
  const cards = [['Research benchmarks', catalog.benchmarks.length, 'Distinct papers and evaluation protocols'], ['Native terminal tasks', inventory.tasks.length, 'Pinned release · file hashes recorded'], ['Measured GLM runs', catalog.measured_glm_runs.length, 'Not run · provider and usage budget pending'], ['Local harness controls', controls.results.length, 'Reference solution + no-op baseline']];
  $('#research-metrics').replaceChildren(...cards.map(([name, value, sub]) => { const c = el('div', null, 'metric'); c.append(el('div', name, 'metric-label'), el('div', value, 'metric-value'), el('div', sub, 'metric-sub')); return c; }));
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
