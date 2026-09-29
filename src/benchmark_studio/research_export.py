"""Publish measured pilot evidence and reproducible summaries, never vendor scores."""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
import subprocess
from pathlib import Path

from .analysis import percentile
from .models import digest
from .research import check_terminal_repo

REVISION = '69671fbaac6d67a7ef0dfec016cc38a64ef7a77c'
DATASET_NOTES = {
    ('mbpp', '313'): 'The prompt says print positive numbers, but its original assertions expect the first nonnegative number to be returned. Both models failed those original tests. Kept without post-hoc removal; this is not clean evidence of a coding defect.',
    ('gsm8k', '1288'): 'The question does not specify a unit. GLM-5.3 returned 2040 minutes, equal to the reference 34 hours. The declared numeric scorer marks it wrong because it cannot infer unit equivalence; this is not an arithmetic failure.'
}
LABELS = {'humaneval': 'HumanEval', 'mbpp': 'MBPP', 'gsm8k': 'GSM8K', 'ifeval': 'IFEval', 'terminal-bench': 'Terminal-Bench 2.0'}


def summaries(rows: list[dict]) -> list[dict]:
    output = []
    for benchmark in LABELS:
        for model in sorted({r['model'] for r in rows}):
            group = [r for r in rows if r['benchmark'] == benchmark and r['model'] == model]
            if not group: continue
            timings = sorted(r['latency_ms'] for r in group if r['latency_ms'] is not None)
            known = [r for r in group if r['input_tokens'] is not None and r['output_tokens'] is not None]
            item = {'benchmark': benchmark, 'label': LABELS[benchmark], 'model': model,
                    'completed': len(group), 'passed': sum(r['passed'] for r in group),
                    'errors': sum(bool(r['error']) for r in group),
                    'latency_ms': {'p50': percentile(timings, .5), 'p95': percentile(timings, .95), 'samples': timings},
                    'latency_kind': group[0]['latency_kind'],
                    'input_tokens': sum(r['input_tokens'] for r in known),
                    'output_tokens': sum(r['output_tokens'] for r in known), 'usage_covered': len(known)}
            item['pass_rate'] = item['passed'] / item['completed']
            item['error_rate'] = item['errors'] / item['completed']
            if benchmark == 'ifeval':
                for mode in ('strict', 'loose'):
                    checks = [v for r in group for v in r['judgment'].get(mode, [])]
                    item[mode + '_instruction_accuracy'] = sum(checks) / len(checks) if checks else None
                    item[mode + '_prompt_accuracy'] = sum(r['judgment'].get(mode + '_prompt', False) for r in group) / len(group)
            output.append(item)
    return output


def terminal_rows(job: Path, repo: Path, api_log: Path) -> tuple[list[dict], dict]:
    inventory = check_terminal_repo(repo, REVISION)
    calls = [json.loads(line) for line in api_log.read_text().splitlines()]
    rows = []; assigned = set()
    for path in sorted(job.glob('*/result.json')):
        raw = json.loads(path.read_text())
        name = raw['task_name']; model = raw['config']['agent']['model_name'].removeprefix('openai/')
        if model not in {'glm-5.3', 'glm-5.3-flash'} or raw['agent_info']['name'] != 'terminus-2':
            raise ValueError('Unexpected terminal model/scaffold')
        if not any(t['id'] == name for t in inventory): raise ValueError('Unknown task')
        instruction = (repo / name / 'instruction.md').read_text()
        selected = []
        for i, call in enumerate(calls):
            messages = call['request'].get('messages', [])
            if call['requested_model'] == model and any(instruction.strip() in str(m.get('content', '')) for m in messages):
                if i in assigned: raise ValueError('Ambiguous API call attribution')
                assigned.add(i); selected.append(call)
        if not selected: raise ValueError(f'No API evidence for {model}/{name}')
        if any(c['status'] == 200 and c['returned_model'] != model for c in selected):
            raise ValueError('Model identity mismatch')
        reward = (raw.get('verifier_result') or {}).get('rewards', {}).get('reward')
        error = raw.get('exception_info')
        if reward not in (0, 1) and not error: raise ValueError('Incomplete trial')
        ctrf_path = path.parent / 'verifier/ctrf.json'
        tests = [{k: t.get(k) for k in ('name', 'status', 'message')} for t in json.loads(ctrf_path.read_text())['results']['tests']] if ctrf_path.exists() else []
        if tests and reward is not None and int(all(t['status'] == 'passed' for t in tests)) != reward:
            raise ValueError('Reward disagrees with verifier tests')
        trajectory_path = path.parent / 'agent/trajectory.json'
        trajectory = json.loads(trajectory_path.read_text()) if trajectory_path.exists() else None
        timing = raw.get('agent_execution') or {}
        latency = (datetime.fromisoformat(timing['finished_at']) - datetime.fromisoformat(timing['started_at'])).total_seconds()*1000 if timing.get('finished_at') else None
        usage = raw.get('agent_result') or {}
        base = f'https://github.com/harbor-framework/terminal-bench-2/blob/{REVISION}/{name}'
        rows.append({'benchmark': 'terminal-bench', 'task_id': name, 'model': model,
                     'passed': reward == 1 and not error, 'error': error,
                     'prompt': instruction, 'response': trajectory,
                     'expected': {'rule': 'Native final-state verifier; reward 1 requires all checks to pass.', 'tests': tests, 'source': base + '/tests/test.sh'},
                     'judgment': {'passed': reward == 1 and not error, 'reward': reward, 'kind': 'deterministic', 'method': 'native Harbor verifier', 'tests': tests,
                                  'explanation': 'Official task verifier checks the final container state after Terminus 2 finishes; exceptions count as unsuccessful completion.'},
                     'latency_ms': latency, 'latency_kind': 'agent wall time including tools; excludes setup/verifier',
                     'input_tokens': usage.get('n_input_tokens'), 'output_tokens': usage.get('n_output_tokens'),
                     'evidence': {'trial': raw['trial_name'], 'task_checksum': raw['task_checksum'], 'source_revision': REVISION,
                                  'raw_result_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                  'agent': raw['config']['agent'], 'agent_info': raw['agent_info'],
                                  'started_at': raw['started_at'], 'finished_at': raw['finished_at'],
                                  'agent_result': usage, 'api_calls': selected,
                                  'task_files_sha256': next(t['files_sha256'] for t in inventory if t['id'] == name)},
                     'protocol': 'Three resource-selected tasks, one trial each, Harbor 0.23.0 / Terminus 2, 32K context budget, 8192 output tokens, 50 turns, native task timeouts. Not a full leaderboard evaluation.'})
    if len(rows) != 6: raise ValueError('Expected all six terminal trials before publication')
    if len(assigned) != len(calls): raise ValueError('Unattributed API calls; inspect log before publishing')
    images = []
    for tag in sorted({t['environment']['docker_image'] for t in inventory if t['id'] in {r['task_id'] for r in rows}}):
        inspected = json.loads(subprocess.check_output(['docker', 'image', 'inspect', tag], text=True))[0]
        images.append({'tag': tag, **{k: inspected[k] for k in ('Id', 'RepoDigests', 'Architecture', 'Os')}})
    return rows, {'job': job.name, 'harness': 'harbor==0.23.0', 'task_revision': REVISION,
                  'gateway_log_sha256': hashlib.sha256(api_log.read_bytes()).hexdigest(), 'calls': len(calls),
                  'images_observed_at_export': images,
                  'harness_dependency_sha256': hashlib.sha256(Path('requirements-harbor.txt').read_bytes()).hexdigest(),
                  'job_config': json.loads((job / 'config.json').read_text())}


def build(native: dict, terminal: list[dict], provenance: dict) -> dict:
    if native['run']['status'] != 'completed': raise ValueError('Prompt pilot is incomplete')
    expected = {(t['benchmark'], t['id'], m) for t in native['run']['snapshot']['tasks'] for m in native['run']['snapshot']['models']}
    observed = {(r['benchmark'], r['task']['id'], r['model_id']) for r in native['results']}
    if expected != observed or len(observed) != len(native['results']): raise ValueError('Missing or duplicate native model/task results')
    if native['evidence_sha256'] != digest({'run': native['run'], 'results': native['results']}):
        raise ValueError('Native evidence fingerprint mismatch')
    rows = []
    for r in native['results']:
        if not r['error'] and r['provider_metadata'].get('returned_model') != r['model_id']:
            raise ValueError('Returned identity differs from score label')
        rows.append({'benchmark': r['benchmark'], 'task_id': r['task']['id'], 'model': r['model_id'],
                     'passed': r['judgment']['passed'], 'error': r['error'], 'prompt': r['task']['prompt'],
                     'response': r['response'], 'expected': r['task']['expected'], 'judgment': r['judgment'],
                     'latency_ms': r['latency_ms'], 'latency_kind': 'API response wall time; excludes scoring',
                     'input_tokens': r['input_tokens'], 'output_tokens': r['output_tokens'], 'protocol': r['task']['protocol'],
                     'evidence': {k: r[k] for k in ('provider_metadata', 'attempts', 'completed_at')},
                     'source_revision': r['task']['source_revision'], 'source_sha256': r['task']['source_sha256']})
    rows.extend(terminal)
    for r in rows:
        r['dataset_caveat'] = DATASET_NOTES.get((r['benchmark'], r['task_id']))
        r['disagreement'] = len({x['passed'] for x in rows if x['benchmark'] == r['benchmark'] and x['task_id'] == r['task_id']}) > 1
    payload = {'schema_version': 1, 'kind': 'measured_research_pilot', 'origin': 'measured',
               'scope': '10 preselected tasks per prompt benchmark and 3 resource-selected terminal tasks; one completion/trial per model. These small samples do not establish overall model superiority.',
               'model_identity_note': 'The Coding Plan endpoint returned glm-5.3 for glm-5.2 requests. No measured GLM-5.2 score is claimed. GLM-5.3-Flash was independently verified and used as the second model.',
               'billing': 'Coding Plan subscription usage. Actual monetary charges are unknown; token totals are not a bill. No paid service is needed for the separate local/mock workflow.',
               'dataset_notes': [f'{benchmark}:{task}: {note}' for (benchmark, task), note in DATASET_NOTES.items()],
               'native_run': native['run'], 'native_evidence_sha256': native['evidence_sha256'],
               'terminal_run': provenance, 'results': rows, 'summary': summaries(rows)}
    payload['evidence_sha256'] = digest(payload)
    return payload


def validate_payload(payload: dict):
    expected = payload['evidence_sha256']
    if digest({k: v for k, v in payload.items() if k != 'evidence_sha256'}) != expected:
        raise ValueError('Evidence fingerprint mismatch')
    if summaries(payload['results']) != payload['summary']:
        raise ValueError('Summary disagrees with task evidence')
    seen = set()
    for r in payload['results']:
        key = (r['benchmark'], r['task_id'], r['model'])
        if key in seen: raise ValueError('Duplicate measured task/model pair')
        seen.add(key)
        if r['passed'] != r['judgment']['passed']: raise ValueError('Result disagrees with judgment')
        disagreement = len({x['passed'] for x in payload['results'] if x['benchmark'] == r['benchmark'] and x['task_id'] == r['task_id']}) > 1
        if r['disagreement'] != disagreement: raise ValueError('Disagreement flag does not match paired outcomes')


def report(payload: dict) -> str:
    lines = ['# GLM research pilot', '', f"Prompt run: `{payload['native_run']['id']}` · started {payload['native_run']['created_at']}. Terminal job: `{payload['terminal_run']['job']}`.", '', payload['scope'], '', payload['model_identity_note'], '', 'IFEval rates use strict prompt accuracy. HumanEval/MBPP use original tests on one completion; GSM8K uses exact final-number matching; Terminal-Bench uses native verifier rewards.', '',
             '| Benchmark | Model | Passed | Rate | p50 / p95 seconds | Errors |', '| --- | --- | --- | --- | --- | --- |']
    for s in payload['summary']:
        t = s['latency_ms']
        times = f"{t['p50']/1000:.2f} / {t['p95']/1000:.2f}" if t['p50'] is not None else 'unknown'
        lines.append(f"| {s['label']} | {s['model']} | {s['passed']}/{s['completed']} | {s['pass_rate']:.0%} | {times} | {s['errors']} |")
    lines += ['', 'Terminal latency is agent execution wall time including tools; other rows measure API response time. Percentiles use linear interpolation. Do not compare these timing definitions directly.', '', payload['billing'], '', '## IFEval secondary metrics', '']
    for s in payload['summary']:
        if s['benchmark'] == 'ifeval':
            lines.append(f"- {s['model']}: strict prompt {s['strict_prompt_accuracy']:.1%}, loose prompt {s['loose_prompt_accuracy']:.1%}, strict instruction {s['strict_instruction_accuracy']:.1%}, loose instruction {s['loose_instruction_accuracy']:.1%}.")
    lines += ['', '## Reported token usage', '']
    for model in sorted({r['model'] for r in payload['results']}):
        group = [s for s in payload['summary'] if s['model'] == model]
        lines.append(f"- {model}: {sum(s['input_tokens'] for s in group):,} input / {sum(s['output_tokens'] for s in group):,} output tokens, covering {sum(s['usage_covered'] for s in group)}/{sum(s['completed'] for s in group)} results. See individual call records for cached usage.")
    lines += ['', 'These totals exclude the separate access probes; unknown provider billing is not estimated.', '', '## Failures', '']
    for r in payload['results']:
        if not r['passed']: lines.append(f"- {r['model']} · {r['benchmark']}:{r['task_id']} · {r.get('dataset_caveat') or r['judgment']['explanation']}")
    lines += ['', '## Dataset caveat', '', *payload['dataset_notes'], '', '## Hardware and provenance', '', '```json', json.dumps(payload['native_run']['snapshot']['hardware'], indent=2), '```', '',
              'Terminal environments ran in Docker on the same host; amd64 images use emulation on Apple Silicon. Native task image tags and network-installed dependencies can drift.', '',
              'The evidence JSON contains the exact prompts, responses, native tests, judgments, settings, source hashes, API identity/usage and agent trajectories. The dashboard can filter individual failures and disagreements.', '',
              f"Evidence SHA-256: `{payload['evidence_sha256']}`", '']
    return '\n'.join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--native', type=Path, default=Path('runs/glm/native-pilot.json'))
    p.add_argument('--job', type=Path, default=Path('runs/harbor/glm-terminal-pilot-v1'))
    p.add_argument('--repo', type=Path, default=Path('runs/research/terminal-bench-2'))
    p.add_argument('--api-log', type=Path, default=Path('runs/glm/harbor-api-calls.jsonl'))
    p.add_argument('--output', type=Path, default=Path('dashboard/research/measurements.json'))
    p.add_argument('--report-only', type=Path, help='Recompute report from a published evidence JSON without inference')
    p.add_argument('--report', type=Path, default=Path('dashboard/research/report.md'))
    args = p.parse_args()
    if args.report_only:
        payload = json.loads(args.report_only.read_text())
        validate_payload(payload)
    else:
        rows, provenance = terminal_rows(args.job, args.repo, args.api_log)
        payload = build(json.loads(args.native.read_text()), rows, provenance)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n')
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report(payload))
    print(f"Verified {len(payload['results'])} measured results across {len(LABELS)} benchmark protocols; report: {args.report}")

if __name__ == '__main__': main()
