import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest

from benchmark_studio.analysis import build_export, export_run, percentile, verify_export, markdown_report
from benchmark_studio.models import RunConfig, load_dataset
from benchmark_studio.providers import Generation, ProviderError
from benchmark_studio.runner import execute
from benchmark_studio.storage import Store


class FakeProvider:
    calls = 0
    active = 0
    peak = 0
    starts = []
    mode = 'success'
    version = 'v1'

    def __init__(self, config): pass
    async def manifest(self): return {'digest': self.version, 'synthetic': True}
    async def close(self): pass
    async def generate(self, prompt, options):
        cls = type(self)
        cls.calls += 1; cls.active += 1
        cls.peak = max(cls.peak, cls.active)
        cls.starts.append(time.monotonic())
        try:
            await asyncio.sleep(.15 if cls.mode == 'slow' else .01)
            if cls.mode == 'retry' and cls.calls == 1: raise ProviderError('busy', True)
            if cls.mode == 'error': raise ProviderError('bad request')
            return Generation('19', 10, 2)
        finally:
            cls.active -= 1


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'results.sqlite')
        raw = json.loads(Path('configs/mock.json').read_text())
        raw.update(requests_per_second=1000.0, timeout_seconds=1.0, retries=1)
        self.config = RunConfig.model_validate(raw)
        self.tasks = [t for t in load_dataset(Path('datasets/studio-sample-v1.jsonl')) if t.id in {'reason-crates','reason-crates-noise'}]
        FakeProvider.calls = FakeProvider.active = FakeProvider.peak = 0
        FakeProvider.starts = []; FakeProvider.mode = 'success'; FakeProvider.version = 'v1'

    def tearDown(self):
        self.store.close(); self.tmp.cleanup()

    async def run_it(self, **kwargs):
        await execute(self.store, 'test', self.tasks, self.config, factory=FakeProvider, **kwargs)

    async def test_resume_preserves_results_and_is_idempotent(self):
        await self.run_it(max_new_results=1)
        original = self.store.results('test')[0]
        self.assertEqual(self.store.run('test')['status'], 'interrupted')
        self.assertEqual(FakeProvider.calls, 1)
        # Reopen the DB to prove persistence across process-like boundaries.
        path = self.store.path; self.store.close(); self.store = Store(path)
        await execute(self.store, 'test', factory=FakeProvider)
        self.assertEqual(FakeProvider.calls, 4)
        self.assertIn(original, self.store.results('test'))
        self.assertEqual(self.store.run('test')['status'], 'completed')
        await execute(self.store, 'test', factory=FakeProvider)
        self.assertEqual(FakeProvider.calls, 4)

    async def test_snapshot_resume_ignores_mutable_inputs(self):
        await self.run_it(max_new_results=1)
        await execute(self.store, 'test', [], self.config.model_copy(update={'name':'changed'}), factory=FakeProvider)
        self.assertEqual(len(self.store.results('test')), 4)
        self.assertEqual(self.store.run('test')['snapshot']['config']['name'], 'Mock demonstration')

    async def test_model_change_blocks_resume(self):
        await self.run_it(max_new_results=1)
        FakeProvider.version = 'v2'
        with self.assertRaisesRegex(ValueError, 'digest'): await execute(self.store, 'test', factory=FakeProvider)
        self.assertEqual(FakeProvider.calls, 1)

    async def test_timeout_is_retried_and_recorded(self):
        FakeProvider.mode = 'slow'
        self.config = self.config.model_copy(update={'timeout_seconds':.01})
        await self.run_it(max_new_results=1)
        row = self.store.results('test')[0]
        self.assertIn('timeout', row['error'])
        self.assertFalse(row['judgment']['passed'])
        history = self.store.attempts('test', row['model_id'], row['task_id'])
        self.assertEqual(len(history), 2)
        self.assertTrue(all(h['retryable'] and h['latency_ms'] > 0 for h in history))

    async def test_transient_error_retries_and_terminal_does_not(self):
        FakeProvider.mode = 'retry'
        await self.run_it(max_new_results=1)
        self.assertEqual(FakeProvider.calls, 2)
        self.assertIsNone(self.store.results('test')[0]['error'])
        FakeProvider.mode = 'error'
        await execute(self.store, 'test', factory=FakeProvider, max_new_results=1)
        self.assertEqual(FakeProvider.calls, 3)
        self.assertEqual(sum(bool(r['error']) for r in self.store.results('test')), 1)

    async def test_cancellation_checkpoints_and_resumes(self):
        FakeProvider.mode = 'slow'
        running = asyncio.create_task(self.run_it())
        await asyncio.sleep(.04)
        running.cancel()
        with self.assertRaises(asyncio.CancelledError): await running
        self.assertEqual(self.store.run('test')['status'], 'interrupted')
        self.assertEqual(len(self.store.results('test')), 0)
        FakeProvider.mode = 'success'
        await execute(self.store, 'test', factory=FakeProvider)
        history = self.store.attempts('test', self.config.models[0].id, self.tasks[0].id)
        self.assertEqual([h['status'] for h in history], ['interrupted','success'])

    async def test_process_crash_recovers_unfinished_attempt(self):
        await self.run_it(max_new_results=1)
        model, task = self.config.models[0], self.tasks[1]
        self.store.begin_attempt('test', model.id, task.id)
        await execute(self.store, 'test', factory=FakeProvider)
        self.assertEqual(self.store.attempts('test', model.id, task.id)[0]['status'], 'interrupted')

    async def test_concurrency_and_rate_bound(self):
        FakeProvider.mode = 'slow'
        self.config = self.config.model_copy(update={'concurrency':2, 'requests_per_second':25.0})
        await self.run_it()
        self.assertEqual(FakeProvider.peak, 2)
        self.assertTrue(all(b - a >= .035 for a,b in zip(FakeProvider.starts, FakeProvider.starts[1:])))

    async def test_export_traceability_partial_denominators_and_cost(self):
        self.config.models[0].input_per_million = 1.0
        self.config.models[0].output_per_million = 2.0
        await self.run_it(max_new_results=1)
        data = build_export(self.store, 'test')
        model = data['summary']['models'][0]
        self.assertEqual((model['completed'], model['planned']), (1,2))
        self.assertEqual(model['pass_rate'], 1)
        self.assertAlmostEqual(model['cost_usd'], .000014)
        self.assertIsNone(data['summary']['models'][1]['pass_rate'])
        self.assertIsNone(data['summary']['models'][1]['cost_usd'])
        output = Path(self.tmp.name) / 'export'
        path = export_run(self.store, 'test', output)
        before = path.read_bytes()
        export_run(self.store, 'test', output)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(json.loads((output/'index.json').read_text())['runs']),1)
        self.assertEqual(len(data['results'][0]['attempts']),1)

    async def test_database_rejects_overlapping_runner(self):
        with self.store.writer_lock():
            with self.assertRaisesRegex(ValueError, 'another runner'): await self.run_it()

    def test_percentile_interpolation(self):
        self.assertEqual(percentile([10,20,30,40],.5),25)
        self.assertEqual(percentile([10,20,30,40],.95),38.5)
        self.assertIsNone(percentile([],.5))


    async def test_published_report_recomputation_detects_tampering(self):
        import copy
        await self.run_it()
        data = build_export(self.store, 'test')
        self.assertEqual(markdown_report(verify_export(data)), markdown_report(data))
        for mutate in [
            lambda d: d['summary']['models'][0].update(pass_rate=0),
            lambda d: d['results'][0].update(response='tampered'),
            lambda d: d['run']['snapshot']['config'].update(name='tampered'),
            lambda d: d['results'].pop(),
        ]:
            altered = copy.deepcopy(data)
            mutate(altered)
            with self.assertRaises(ValueError): verify_export(altered)


    async def test_slow_checkpoint_does_not_compress_request_starts(self):
        from unittest.mock import patch
        FakeProvider.mode = 'slow'
        self.config = self.config.model_copy(update={'concurrency':2, 'requests_per_second':25.0})
        original = self.store.begin_attempt
        first = True

        def delayed_checkpoint(*args):
            nonlocal first
            if first:
                first = False
                time.sleep(.06)
            return original(*args)

        with patch.object(self.store, 'begin_attempt', side_effect=delayed_checkpoint):
            await self.run_it()
        self.assertEqual(FakeProvider.calls, 4)
        gaps = [b - a for a, b in zip(FakeProvider.starts, FakeProvider.starts[1:])]
        self.assertTrue(all(gap >= .035 for gap in gaps), gaps)
