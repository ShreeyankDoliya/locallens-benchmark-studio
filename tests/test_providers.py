import asyncio
import json
import os
import unittest
from unittest.mock import patch
import httpx
from benchmark_studio.models import ModelConfig
from benchmark_studio.providers import OllamaProvider, ProviderError


class OllamaTests(unittest.IsolatedAsyncioTestCase):
    def provider(self, handler):
        return OllamaProvider(ModelConfig(id='tiny',provider='ollama',model='tiny:1b'),transport=httpx.MockTransport(handler))

    async def test_manifest_and_generation_protocol(self):
        seen = []
        def handler(request):
            seen.append(request)
            if request.url.path == '/api/tags': return httpx.Response(200,json={'models':[{'name':'tiny:1b','digest':'sha256:abc','details':{'quantization_level':'Q4_K_M'}}]})
            if request.url.path == '/api/show': return httpx.Response(200,json={'template':'{{ .Prompt }}','parameters':'temperature 0'})
            if request.url.path == '/api/version': return httpx.Response(200,json={'version':'0.test'})
            payload = json.loads(request.content)
            self.assertEqual(payload['prompt'],'answer me')
            self.assertEqual(payload['options'],{'seed':42})
            self.assertFalse(payload['stream'])
            self.assertNotIn('expected',payload)
            return httpx.Response(200,json={'response':'42','done':True,'prompt_eval_count':4,'eval_count':1,'load_duration':10})
        provider = self.provider(handler)
        try:
            self.assertEqual((await provider.manifest())['digest'],'sha256:abc')
            result = await provider.generate('answer me',{'seed':42})
            self.assertEqual((result.text,result.input_tokens,result.output_tokens),('42',4,1))
            self.assertEqual(result.metadata['load_duration'],10)
        finally: await provider.close()

    async def test_errors_and_missing_usage(self):
        for status in [400,429,500]:
            provider = self.provider(lambda _: httpx.Response(status))
            try:
                with self.assertRaises(ProviderError) as caught: await provider.generate('test',{})
                self.assertEqual(caught.exception.retryable,status != 400)
            finally: await provider.close()
        provider = self.provider(lambda _: httpx.Response(200,json={'response':'x','done':True}))
        try: self.assertIsNone((await provider.generate('test',{})).input_tokens)
        finally: await provider.close()

    async def test_invalid_or_incomplete_response(self):
        for payload in [{'response':'x','done':False}, {'response':2,'done':True}, {'response':'x','done':True,'eval_count':True}]:
            provider = self.provider(lambda _: httpx.Response(200,json=payload))
            try:
                with self.assertRaises(ProviderError): await provider.generate('test',{})
            finally: await provider.close()

    async def test_cloud_models_rejected(self):
        def handler(request):
            if request.url.path == '/api/tags': return httpx.Response(200,json={'models':[{'name':'tiny:1b','digest':'abc'}]})
            return httpx.Response(200,json={'remote_host':'https://example.com'})
        provider = self.provider(handler)
        try:
            with self.assertRaisesRegex(ProviderError,'Cloud'): await provider.manifest()
        finally: await provider.close()

    def test_remote_or_credential_bearing_host_rejected(self):
        for host in ['https://api.example.com','http://user:secret@localhost:11434','http://localhost:11434/path','http://localhost:11434?token=x']:
            with patch.dict(os.environ,{'OLLAMA_HOST':host}), self.assertRaises(ValueError): self.provider(lambda _: None)
