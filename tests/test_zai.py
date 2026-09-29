import json
import os
import unittest
from unittest.mock import patch

import httpx
from pydantic import ValidationError

from benchmark_studio.models import ModelConfig, RunConfig
from benchmark_studio.providers import ProviderError, ZaiProvider
from pathlib import Path


class ZaiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"ZAI_API_KEY": "unit-test-secret", "ZAI_BASE_URL": "https://api.z.ai/api/paas/v4"})
        self.env.start()
        self.config = ModelConfig(id="glm-5.3", provider="zai", model="glm-5.3", options={})

    def tearDown(self):
        self.env.stop()

    def provider(self, handler):
        return ZaiProvider(self.config, transport=httpx.MockTransport(handler))

    async def test_payload_usage_identity_and_secret_redaction(self):
        def handler(request):
            self.assertEqual(str(request.url), "https://api.z.ai/api/paas/v4/chat/completions")
            self.assertEqual(request.headers['Authorization'], 'Bearer unit-test-secret')
            data = json.loads(request.content)
            self.assertEqual(data['messages'], [{'role':'user', 'content':'Test prompt'}])
            self.assertEqual(data['thinking'], {'type':'enabled'})
            self.assertEqual(data['reasoning_effort'], 'high')
            self.assertNotIn('expected', data)
            return httpx.Response(200, json={'id':'test-id', 'model':'glm-5.3', 'choices':[{'message':{'content':'OK unit-test-secret', 'reasoning_content':'unit-test-secret'}, 'finish_reason':'stop'}], 'usage':{'prompt_tokens':12,'completion_tokens':7,'total_tokens':19}})
        provider = self.provider(handler)
        try:
            manifest = await provider.manifest()
            self.assertTrue(manifest['remote'])
            self.assertIn('not a weight digest', manifest['identity_kind'])
            self.assertNotIn('unit-test-secret', json.dumps(manifest))
            result = await provider.generate('Test prompt', self.config.options)
            self.assertEqual((result.input_tokens,result.output_tokens), (12,7))
            self.assertEqual(result.text, 'OK [REDACTED]')
            self.assertNotIn('unit-test-secret', json.dumps(result.metadata))
        finally:
            await provider.close()

    async def test_balance_and_auth_errors_are_fatal_but_rate_limits_retry(self):
        for status,code,fatal,retry in [(429,'1113',True,False),(401,'1002',True,False),(403,'1003',True,False),(429,'1302',False,True),(503,None,False,True),(400,'bad',False,False)]:
            with self.subTest(status=status,code=code):
                p = self.provider(lambda _: httpx.Response(status,json={'error':{'code':code,'message':'unit-test-secret'}}))
                try:
                    with self.assertRaises(ProviderError) as caught:
                        await p.generate('x', self.config.options)
                    self.assertEqual(caught.exception.fatal,fatal)
                    self.assertEqual(caught.exception.retryable,retry)
                    self.assertNotIn('unit-test-secret',str(caught.exception))
                finally:
                    await p.close()

    async def test_no_redirects_and_invalid_responses_rejected(self):
        responses=[httpx.Response(302,headers={'Location':'https://example.com'}),httpx.Response(200,json={}),httpx.Response(200,json={'choices':[{'message':{'content':'x'}}],'usage':{'completion_tokens':True}})]
        for response in responses:
            p=self.provider(lambda _: response)
            try:
                with self.assertRaises(ProviderError): await p.generate('x',self.config.options)
            finally: await p.close()

    def test_missing_key_and_unapproved_endpoint_fail_before_network(self):
        with patch.dict(os.environ, {'ZAI_API_KEY':''}), self.assertRaisesRegex(ValueError,'ZAI_API_KEY'):
            self.provider(lambda _:None)
        for url in ['http://api.z.ai/api/paas/v4','https://example.com','https://api.z.ai/api/paas/v4?key=x']:
            with patch.dict(os.environ,{'ZAI_BASE_URL':url}), self.assertRaises(ValueError):
                self.provider(lambda _:None)

    def test_config_enforces_reasoning_and_supported_fields(self):
        cfg = RunConfig.model_validate_json(Path('configs/zai.json').read_text())
        self.assertEqual([m.model for m in cfg.models], ['glm-5.3','glm-5.2'])
        for options in [{'thinking':{'type':'disabled'}},{'messages':[]},{'max_tokens':0},{'api_key':'bad'}]:
            with self.assertRaises(ValidationError):
                ModelConfig(id='glm',provider='zai',model='glm-5.3',options=options)
