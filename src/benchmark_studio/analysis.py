"""All summaries derive from the exported task-level evidence."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import json
import math

from .storage import Store


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summarize(snapshot: dict, results: list[dict]) -> dict:
    tasks = {t["id"]: t for t in snapshot["tasks"]}
    summaries = []
    for model in snapshot["config"]["models"]:
        rows = [r for r in results if r["model_id"] == model["id"]]
        count = len(rows)
        categories = {}
        for category in sorted({t["category"] for t in tasks.values()}):
            subset = [r for r in rows if tasks[r["task_id"]]["category"] == category]
            passed = sum(r["judgment"]["passed"] for r in subset)
            categories[category] = {"completed": len(subset), "planned": sum(t["category"] == category for t in tasks.values()), "passed": passed, "pass_rate": passed / len(subset) if subset else None}
        groups = defaultdict(list)
        for row in rows:
            groups[tasks[row["task_id"]]["group"]].append(row)
        paired = [g for name, g in groups.items() if len(g) > 1 and len(g) == sum(t["group"] == name for t in tasks.values())]
        latencies = [r["latency_ms"] for r in rows if not r["error"]]
        known_costs = []
        for row in rows:
            if model["input_per_million"] is not None and row["input_tokens"] is not None and row["output_tokens"] is not None:
                known_costs.append((row["input_tokens"] * model["input_per_million"] + row["output_tokens"] * model["output_per_million"]) / 1_000_000)
        passed = sum(r["judgment"]["passed"] for r in rows)
        summaries.append({"model_id": model["id"], "completed": count, "planned": len(tasks), "passed": passed,
                          "pass_rate": passed / count if count else None, "errors": sum(bool(r["error"]) for r in rows),
                          "error_rate": sum(bool(r["error"]) for r in rows) / count if count else None,
                          "categories": categories, "latency_ms": {"p50": percentile(latencies, .5), "p90": percentile(latencies, .9), "p95": percentile(latencies, .95), "samples": len(latencies)},
                          "cost_usd": sum(known_costs) if known_costs else None, "cost_covered_results": len(known_costs),
                          "consistency": {"complete_groups": len(paired), "same_pass_outcome": sum(len({r["judgment"]["passed"] for r in g}) == 1 for g in paired), "all_pass": sum(all(r["judgment"]["passed"] for r in g) for g in paired)}})
    by_task = defaultdict(list)
    for row in results:
        by_task[row["task_id"]].append(row)
    disagreements = [tid for tid, rows in sorted(by_task.items()) if len({r["judgment"]["passed"] for r in rows}) > 1]
    return {"models": summaries, "disagreements": disagreements}


def build_export(store: Store, run_id: str) -> dict:
    run = store.run(run_id)
    rows = store.results(run_id)
    for row in rows:
        row["attempts"] = store.attempts(run_id, row["model_id"], row["task_id"])
    return {"schema_version": 1, "run": run, "summary": summarize(run["snapshot"], rows), "results": rows}


def compare_runs(store: Store, run_a: str, run_b: str, *, color: bool = False, fancy: bool = True) -> str:
    """Terminal comparison of two saved runs; models are matched by configured ID.

    `color` adds ANSI styling; `fancy` allows non-ASCII arrows and rules.
    """
    runs = [store.run(r) for r in (run_a, run_b)]
    results = [store.results(r) for r in (run_a, run_b)]
    summaries = [{m["model_id"]: m for m in summarize(run["snapshot"], rows)["models"]} for run, rows in zip(runs, results)]
    snaps = [run["snapshot"] for run in runs]
    arrow, rule, dash = ('→', '─', '—') if fancy else ('->', '-', '-')
    codes = {"bold": "1", "dim": "2", "green": "32", "red": "31", "yellow": "33"}
    paint = lambda text, style: f'\033[{codes[style]}m{text}\033[0m' if color and text.strip() else text

    lines = []
    name_width = max(len(run_a), len(run_b))
    for label, run in (('A', runs[0]), ('B', runs[1])):
        when = run["created_at"][:16].replace('T', ' ') + ' UTC'
        lines.append(f'{paint("Run " + label, "bold")}  {run["id"].ljust(name_width)}  {run["status"]:<11}  {paint(when, "dim")}')
    lines.append('')
    differences = [label for label, key in (("datasets", "dataset_sha256"), ("scorer versions", "scorer_version"), ("configurations", "config_sha256"), ("hardware", "hardware")) if snaps[0][key] != snaps[1][key]]
    if differences:
        lines += [paint(f'Note: the runs used different {", ".join(differences)}. Compare with care.', 'yellow'), '']

    def score(m):
        if not m:
            return 'not in run', None
        if m["pass_rate"] is None:
            return 'no results', None
        text = f'{m["passed"]}/{m["completed"]} ({m["pass_rate"]:.0%})'
        return text + (f' of {m["planned"]}' if m["completed"] != m["planned"] else ''), None

    def change(a, b):
        if not a or not b or a["pass_rate"] is None or b["pass_rate"] is None:
            return dash, None
        points = round((b["pass_rate"] - a["pass_rate"]) * 100, 1)
        if points == 0:
            return 'same', 'dim'
        text = f'{points:+g} pts'.replace('-', '−' if fancy else '-')
        return text, 'green' if points > 0 else 'red'

    def seconds(m):
        value = m["latency_ms"]["p50"] if m else None
        if value is None:
            return dash
        return f'{value:.0f} ms' if value < 1000 else f'{value / 1000:.2f} s'

    models = list(dict.fromkeys([*summaries[0], *summaries[1]]))
    header = ['Model', 'Run A score', 'Run B score', 'Change', 'Typical answer time (A ' + arrow + ' B)']
    rows = []
    for model in models:
        a, b = summaries[0].get(model), summaries[1].get(model)
        rows.append([(model, None), score(a), score(b), change(a, b), (f'{seconds(a)} {arrow} {seconds(b)}', None)])
    widths = [max(len(header[i]), *(len(r[i][0]) for r in rows)) for i in range(len(header))]
    # Pad before painting so escape codes never break column alignment.
    lines.append('  '.join(paint(h.ljust(widths[i]), 'bold') for i, h in enumerate(header)).rstrip())
    lines.append(paint(rule * (sum(widths) + 2 * (len(widths) - 1)), 'dim'))
    for row in rows:
        lines.append('  '.join(paint(text.ljust(widths[i]), style) if style else text.ljust(widths[i]) for i, (text, style) in enumerate(row)).rstrip())

    outcome = lambda r: 'error' if r["error"] else 'pass' if r["judgment"]["passed"] else 'fail'
    before = {(r["model_id"], r["task_id"]): outcome(r) for r in results[0]}
    changed = []
    for row in results[1]:
        key = (row["model_id"], row["task_id"])
        if key in before and before[key] != outcome(row):
            changed.append((*key, before[key], outcome(row)))
    lines.append('')
    if not before.keys() & {(r["model_id"], r["task_id"]) for r in results[1]}:
        lines.append(paint('No model ran the same task in both runs, so answers cannot be compared task by task.', 'dim'))
    elif not changed:
        lines.append(paint('Every shared task had the same outcome in both runs.', 'green'))
    else:
        styles = {'pass': 'green', 'fail': 'red', 'error': 'yellow'}
        lines.append(paint(f'{len(changed)} task{"s" if len(changed) != 1 else ""} changed outcome:', 'bold'))
        model_width = max(len(m) for m, *_ in changed)
        task_width = max(len(t) for _, t, *_ in changed)
        for model, task, old, new in sorted(changed):
            lines.append(f'  {model.ljust(model_width)}  {task.ljust(task_width)}  {paint(old, styles[old])} {arrow} {paint(new, styles[new])}')
    return '\n'.join(lines)


def markdown_report(data: dict) -> str:
    run = data["run"]
    snap = run["snapshot"]
    lines = [f'# LLM Benchmark Studio — {run["id"]}', '', f'Status: **{run["status"]}** · Dataset: `{snap["dataset_version"]}`', '',
             'Small diagnostic sample; these scores do not establish overall model superiority.', '',
             '| Model | Passed / completed | Planned | Pass rate | Errors | p50 / p95 ms |', '|---|---:|---:|---:|---:|---:|']
    for m in data["summary"]["models"]:
        fmt = lambda v: f'{v:.2f}' if v is not None else '—'
        rate = f'{m["pass_rate"]:.1%}' if m['pass_rate'] is not None else '—'
        lines.append(f'| {m["model_id"]} | {m["passed"]} / {m["completed"]} | {m["planned"]} | {rate} | {m["errors"]} | {fmt(m["latency_ms"]["p50"])} / {fmt(m["latency_ms"]["p95"])} |')
    lines += ['', '## Provenance', '', f'- Dataset SHA-256: `{snap["dataset_sha256"]}`', f'- Configuration SHA-256: `{snap["config_sha256"]}`', f'- Runner SHA-256: `{snap["engine_sha256"]}`', f'- Scorer: `{snap["scorer_version"]}`', f'- Hardware: {snap["config"]["hardware_notes"]}', f'- Host: `{json.dumps(snap["hardware"], sort_keys=True)}`', '', '## Interpretation', '',
              'Errors count as failures. Incomplete runs use completed tasks as the denominator and show planned counts. Latency percentiles interpolate successful final request durations and exclude queue time, retry backoff and failed attempts. They include model loading when applicable. All attempts are in the JSON evidence.', '',
              'Mock outputs and delays are scripted. Unknown token counts and costs stay null. Local execution has no API fee; electricity and hardware costs are not measured. Optional configured prices estimate only observed token usage, excluding failed attempts with unknown usage.', '',
              'Consistency means equal pass/fail outcomes across a complete perturbation group, not identical answers. A group may consistently fail.', '', '## Disagreements', '']
    lines += [f'- `{tid}`' for tid in data['summary']['disagreements']] or ['None.']
    lines += ['', 'See the adjacent JSON file for every task, prompt, expected answer, response, scoring explanation, model manifest and attempt.', '']
    return '\n'.join(lines)


def export_run(store: Store, run_id: str, output: Path) -> Path:
    data = build_export(store, run_id)
    output.mkdir(parents=True, exist_ok=True)
    path = output / f'{run_id}.json'
    # Replace files atomically so a local dashboard never reads half-written JSON.
    def write(target: Path, content: str):
        temporary = target.with_suffix(target.suffix + '.tmp')
        temporary.write_text(content, encoding='utf-8')
        temporary.replace(target)
    write(path, json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    write(output / f'{run_id}.md', markdown_report(data))
    entries = []
    for candidate in sorted(output.glob('*.json')):
        if candidate.name == 'index.json':
            continue
        content = json.loads(candidate.read_text())
        if content.get('schema_version') == 1 and 'run' in content:
            r = content['run']
            entries.append({'id': r['id'], 'name': r['snapshot']['config']['name'], 'status': r['status'], 'created_at': r['created_at'], 'file': candidate.name, 'report': candidate.stem + '.md'})
    write(output / 'index.json', json.dumps({'schema_version': 1, 'runs': entries}, indent=2) + '\n')
    return path


def verify_export(data: dict) -> dict:
    """Recompute scores and summaries from evidence; hashes are not signatures."""
    from .models import RunConfig, Task, digest
    from .scoring import SCORER_VERSION, score
    if data.get('schema_version') != 1:
        raise ValueError('unsupported export schema')
    snap = data['run']['snapshot']
    if snap['scorer_version'] != SCORER_VERSION:
        raise ValueError('unsupported scorer version')
    tasks = {t['id']: Task.model_validate(t) for t in snap['tasks']}
    if len(tasks) != len(snap['tasks']):
        raise ValueError('duplicate task ID in snapshot')
    config = RunConfig.model_validate(snap['config'])
    models = {m.id for m in config.models}
    if digest(snap['tasks']) != snap['dataset_sha256'] or digest(snap['config']) != snap['config_sha256']:
        raise ValueError('snapshot fingerprint mismatch')
    seen = set()
    for row in data['results']:
        key = (row['model_id'], row['task_id'])
        if key in seen or key[0] not in models or key[1] not in tasks or row['run_id'] != data['run']['id']:
            raise ValueError('invalid or duplicate result identity')
        seen.add(key)
        if row['error']:
            if row['judgment']['passed'] or row['judgment']['score'] != 0:
                raise ValueError('provider error incorrectly scored as a pass')
        elif score(tasks[row['task_id']], row['response']).to_dict() != row['judgment']:
            raise ValueError(f'scoring mismatch: {key}')
    if data['run']['status'] == 'completed' and len(seen) != len(models) * len(tasks):
        raise ValueError('completed run has missing results')
    summary = summarize(snap, data['results'])
    if summary != data['summary']:
        raise ValueError('aggregate summary does not match task evidence')
    return {**data, 'summary': summary}
