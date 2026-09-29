import asyncio
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmark_studio.native_scoring import ResearchTask, extract_code, numeric_answer, score_task
from benchmark_studio.providers import Generation, ProviderError
from benchmark_studio.research_run import execute_native, export, summarize
from benchmark_studio.storage import Store


def math_task():
    return ResearchTask(benchmark='gsm8k',id='0',prompt='What is 2+2? End with #### answer.',expected={'answer':'4'},protocol='test',source_revision='test',source_sha256='test')


class ScorerTests(unittest.TestCase):
    def test_final_number_is_anchored_and_exact(self):
        self.assertEqual(numeric_answer('Reasoning 99.\n#### 1,234.50'),Decimal('1234.5'))
        self.assertEqual(numeric_answer('#### -4'),Decimal('-4'))
        for answer in ['4','#### 4 or 5','#### NaN','#### 4\nExplanation','not #### +Infinity']:
            self.assertIsNone(numeric_answer(answer))

    def test_code_extraction_does_not_repair_or_take_partial_blocks(self):
        self.assertEqual(extract_code('```python\ndef x():\n    return 4\n```')[0], 'def x():\n    return 4')
        self.assertEqual(extract_code('[BEGIN]\ndef x(): pass\n[DONE]')[0], 'def x(): pass')
        text='Explanation\n```python\nx=1\n```'
        self.assertEqual(extract_code(text)[0], text)


class NativeResumeTests(unittest.IsolatedAsyncioTestCase):
    async def test_resume_reuses_saved_generation_after_scorer_failure(self):
        calls=[]
        class Provider:
            def __init__(self, config): self.model=config.model
            async def close(self): pass
            async def generate(self,prompt,options):
                calls.append(prompt)
                return Generation('#### 4',5,3,{'returned_model':self.model})
        snapshot={'tasks':[math_task().model_dump()],'models':['glm-5.3'],'settings':{},'requests_per_second':1000.0,'timeout_seconds':10,'retries':1,'sandbox_image':'unused','concurrency':1}
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite')
            try:
                with patch('benchmark_studio.research_run.ZaiProvider',Provider):
                    with patch('benchmark_studio.research_run.score_task',side_effect=RuntimeError('scorer interrupted')):
                        with self.assertRaisesRegex(RuntimeError,'scorer interrupted'):
                            await execute_native(store,'test',snapshot,Path(tmp))
                    self.assertEqual(store.results('test'),[])
                    self.assertEqual(store.run('test')['status'],'interrupted')
                    await execute_native(store,'test',snapshot,Path(tmp))
                    self.assertEqual(len(calls),1)
                    payload=export(store,'test',Path(tmp)/'out.json')
                    self.assertEqual(payload['summary'][0]['pass_rate'],1)
                    self.assertEqual(payload['summary'][0]['returned_models'],['glm-5.3'])
            finally: store.close()

    async def test_model_identity_mismatch_is_not_a_score(self):
        class Provider:
            def __init__(self, config): pass
            async def close(self): pass
            async def generate(self,prompt,options): return Generation('#### 4',5,3,{'returned_model':'glm-5.3-flash'})
        snapshot={'tasks':[math_task().model_dump()],'models':['glm-5.3'],'settings':{},'requests_per_second':1000.0,'timeout_seconds':10,'retries':1,'sandbox_image':'unused','concurrency':1}
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite')
            try:
                with patch('benchmark_studio.research_run.ZaiProvider',Provider), self.assertRaisesRegex(ProviderError,'identity mismatch'):
                    await execute_native(store,'test',snapshot,Path(tmp))
                self.assertEqual(store.results('test'),[])
                self.assertEqual(store.run('test')['status'],'interrupted')
            finally: store.close()
