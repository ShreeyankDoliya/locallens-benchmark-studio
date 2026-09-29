"""Resumable native research pilot. Shares providers, not diagnostic scorers."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import json
import os
from pathlib import Path
import time

from .models import ModelConfig, ZaiOptions, digest
from .native_scoring import ResearchTask, build_tasks, score_task
from .providers import Generation, ProviderError, ZaiProvider
from .research import load_catalog
from .runner import RateLimiter, hardware
from .storage import Store, now


def source_hash(upstream: Path) -> str:
    own = [Path(__file__), Path(__file__).with_name('native_scoring.py'), Path(__file__).with_name('providers.py')]
    files = own + sorted((upstream / 'instruction_following_eval').glob('*.py'))
    return digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files})


def summarize(snapshot: dict, rows: list[dict]) -> list[dict]:
    summary = []
    for benchmark in sorted({t['benchmark'] for t in snapshot['tasks']}):
        for model in snapshot['models']:
            selected = [r for r in rows if r['benchmark'] == benchmark and r['model_id'] == model]
            passed = sum(r['judgment']['passed'] for r in selected)
            counts = [r for r in selected if r.get('input_tokens') is not None and r.get('output_tokens') is not None]
            item = {'benchmark': benchmark, 'model': model, 'planned': sum(t['benchmark'] == benchmark for t in snapshot['tasks']),
                    'completed': len(selected), 'passed': passed, 'pass_rate': passed / len(selected) if selected else None,
                    'errors': sum(bool(r.get('error')) for r in selected),
                    'input_tokens': sum(r['input_tokens'] for r in counts), 'output_tokens': sum(r['output_tokens'] for r in counts),
                    'usage_covered': len(counts), 'returned_models': sorted({r['provider_metadata'].get('returned_model', 'unknown') for r in selected if not r.get('error')})}
            if benchmark == 'ifeval' and selected:
                for metric in ['strict', 'loose']:
                    checks = [v for r in selected for v in r['judgment'].get(metric, [])]
                    item[metric + '_instruction_accuracy'] = sum(checks) / len(checks) if checks else None
                    item[metric + '_prompt_accuracy'] = sum(r['judgment'].get(metric + '_prompt', False) for r in selected) / len(selected)
            timings = sorted(r['latency_ms'] for r in selected if not r.get('error'))
            from .analysis import percentile
            item['latency_ms'] = {'p50': percentile(timings, .5), 'p95': percentile(timings, .95)}
            summary.append(item)
    return summary


def export(store: Store, run_id: str, output: Path):
    run = store.run(run_id); rows = store.results(run_id)
    payload = {'schema_version': 1, 'kind': 'research_measurements', 'scope': 'preselected pilot subsets; not full benchmark scores',
               'run': run, 'results': rows, 'summary': summarize(run['snapshot'], rows)}
    payload['evidence_sha256'] = digest({'run': run, 'results': rows})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n')
    return payload


async def execute_native(store: Store, run_id: str, snapshot: dict, upstream: Path, max_new: int | None = None):
    with store.writer_lock():
        if store.db.execute('SELECT 1 FROM runs WHERE id=?', (run_id,)).fetchone():
            saved = store.run(run_id)
            if saved['snapshot'] != snapshot:
                raise ValueError('Research protocol, selected tasks, source, endpoint or models changed; start a new run')
            if saved['status'] == 'completed':
                return
        else:
            store.create(run_id, snapshot)
        store.db.execute('CREATE TABLE IF NOT EXISTS research_responses (run_id TEXT, model_id TEXT, task_id TEXT, payload TEXT, PRIMARY KEY(run_id,model_id,task_id))')
        store.db.commit(); store.recover(run_id); store.status(run_id, 'running')
        done = {(r['model_id'], r['task_id']) for r in store.results(run_id)}
        configs = {m: ModelConfig(id=m, provider='zai', model=m, options=snapshot['settings']) for m in snapshot['models']}
        providers = {}; workers = []; limiter = RateLimiter(snapshot['requests_per_second'])
        tasks = [ResearchTask.model_validate(t) for t in snapshot['tasks']]
        pairs = [(m, t) for t in tasks for m in snapshot['models'] if (m, t.benchmark + ':' + t.id) not in done]
        if max_new is not None: pairs = pairs[:max_new]
        queue = asyncio.Queue()
        for pair in pairs: queue.put_nowait(pair)
        async def evaluate(model: str, task: ResearchTask):
            task_id = task.benchmark + ':' + task.id
            cached = store.db.execute('SELECT payload FROM research_responses WHERE run_id=? AND model_id=? AND task_id=?', (run_id, model, task_id)).fetchone()
            if cached:
                response = json.loads(cached[0])
            else:
                response = None
                history = store.attempts(run_id, model, task_id)
                failures = sum(a['status'] == 'error' and not a.get('fatal') for a in history)
                while response is None:
                    await limiter.wait()
                    attempt_id, attempt = store.begin_attempt(run_id, model, task_id)
                    start = time.perf_counter()
                    try:
                        limiter.mark_started()
                        async with asyncio.timeout(snapshot['timeout_seconds']):
                            generation = await providers[model].generate(task.prompt, snapshot['settings'])
                        returned = generation.metadata.get('returned_model')
                        attempt.update(returned_model=returned, input_tokens=generation.input_tokens, output_tokens=generation.output_tokens)
                        if returned != model:
                            raise ProviderError(f'Model identity mismatch: requested {model}, returned {returned}', fatal=True)
                        response = {'response': generation.text, 'input_tokens': generation.input_tokens,
                                    'output_tokens': generation.output_tokens, 'provider_metadata': generation.metadata,
                                    'latency_ms': (time.perf_counter() - start) * 1000, 'error': None}
                        attempt.update(status='success', ended_at=now(), latency_ms=response['latency_ms'])
                        with store.db:
                            store.db.execute('UPDATE attempts SET payload=? WHERE id=?', (json.dumps(attempt), attempt_id))
                            store.db.execute('INSERT INTO research_responses VALUES (?,?,?,?)', (run_id, model, task_id, json.dumps(response)))
                    except (ProviderError, TimeoutError) as exc:
                        fatal = isinstance(exc, ProviderError) and exc.fatal
                        retryable = isinstance(exc, TimeoutError) or exc.retryable
                        attempt.update(status='error', ended_at=now(), error=str(exc) or 'Request timeout', fatal=fatal, retryable=retryable,
                                       latency_ms=(time.perf_counter() - start) * 1000)
                        store.finish_attempt(attempt_id, attempt)
                        if fatal: raise
                        failures += 1
                        if not retryable or failures > snapshot['retries']:
                            response = {'response': None, 'input_tokens': None, 'output_tokens': None, 'provider_metadata': {},
                                        'latency_ms': attempt['latency_ms'], 'error': attempt['error']}
                            with store.db:
                                store.db.execute('INSERT INTO research_responses VALUES (?,?,?,?)', (run_id, model, task_id, json.dumps(response)))
                        else:
                            await asyncio.sleep(min(2 ** failures, 30))
            if response['error']:
                judgment = {'passed': False, 'kind': 'deterministic', 'method': 'provider_error', 'explanation': 'No answer; provider error counted in task completion denominator.'}
            else:
                # Scorer errors interrupt without discarding or paying again for the saved response.
                judgment = await score_task(task, response['response'], image=snapshot['sandbox_image'], upstream=upstream)
            result = {'run_id': run_id, 'model_id': model, 'task_id': task_id, 'benchmark': task.benchmark,
                      'task': task.model_dump(), **response, 'judgment': judgment,
                      'attempts': store.attempts(run_id, model, task_id), 'completed_at': now()}
            with store.db:
                store.db.execute('INSERT INTO results VALUES (?,?,?,?)', (run_id, model, task_id, json.dumps(result)))
            print(f"{model} {task_id}: {'PASS' if judgment['passed'] else 'FAIL'}", flush=True)
        async def worker():
            while not queue.empty():
                await evaluate(*queue.get_nowait())
        try:
            providers = {m: ZaiProvider(c) for m, c in configs.items()}
            workers = [asyncio.create_task(worker()) for _ in range(min(snapshot['concurrency'], len(pairs)))]
            await asyncio.gather(*workers)
            complete = len(store.results(run_id)) == len(tasks) * len(configs)
            store.status(run_id, 'completed' if complete else 'interrupted')
        except BaseException:
            for worker_task in workers: worker_task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            store.status(run_id, 'interrupted')
            raise
        finally:
            for p in providers.values(): await p.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--models', nargs='+', default=['glm-5.3', 'glm-5.3-flash'])
    parser.add_argument('--source-dir', type=Path, default=Path('runs/research/sources'))
    parser.add_argument('--upstream', type=Path, default=Path('runs/research/upstream'))
    parser.add_argument('--image', required=True)
    parser.add_argument('--db', type=Path, default=Path('runs/glm/research.sqlite'))
    parser.add_argument('--output', type=Path, default=Path('runs/glm/pilot.json'))
    parser.add_argument('--max-new', type=int)
    parser.add_argument('--prompt-key', action='store_true')
    args = parser.parse_args()
    if len(set(args.models)) != len(args.models) or not args.models:
        parser.error('model IDs must be unique')
    if args.max_new is not None and args.max_new < 1:
        parser.error('--max-new must be positive')
    if args.prompt_key: os.environ['ZAI_API_KEY'] = getpass.getpass('Z.ai API key (input hidden): ')
    catalog = load_catalog(Path('dashboard/research/catalog.json'))
    selection = json.loads((args.source_dir / 'selection.json').read_text())
    tasks = build_tasks(catalog, args.source_dir, selection)
    snapshot = {'tasks': [t.model_dump() for t in tasks], 'selection': selection, 'models': args.models,
                'settings': ZaiOptions().model_dump(), 'endpoint': os.environ.get('ZAI_BASE_URL', 'https://api.z.ai/api/paas/v4'),
                'source_sha256': source_hash(args.upstream), 'hardware': hardware(), 'sandbox_image': args.image,
                'concurrency': 2, 'requests_per_second': 1.0, 'timeout_seconds': 300.0, 'retries': 2,
                'billing': 'Coding Plan token usage; dollar list-price estimates are not subscription charges',
                'scorer_version': 'research-native-v1', 'repetitions': 1}
    store = Store(args.db)
    try:
        asyncio.run(execute_native(store, args.run_id, snapshot, args.upstream, args.max_new))
    finally:
        if store.db.execute('SELECT 1 FROM runs WHERE id=?', (args.run_id,)).fetchone():
            export(store, args.run_id, args.output)
        store.close()
        if args.prompt_key: os.environ.pop('ZAI_API_KEY', None)


if __name__ == '__main__':
    main()
