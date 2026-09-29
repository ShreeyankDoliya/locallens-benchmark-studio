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
