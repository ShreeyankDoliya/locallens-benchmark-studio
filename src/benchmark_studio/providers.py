"""Providers receive only the prompt and settings, never the answer or rubric."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from .models import ModelConfig, ZaiOptions, digest


@dataclass
class Generation:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ProviderError(Exception):
    def __init__(self, message: str, retryable: bool = False, *, fatal: bool = False, code: str | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.fatal = fatal
        self.code = code


class Provider(Protocol):
    async def manifest(self) -> dict[str, Any]: ...
    async def generate(self, prompt: str, options: dict[str, Any]) -> Generation: ...
    async def close(self) -> None: ...


class MockProvider:
    """Scripted fixtures, not an LLM. Unknown prompts return an explicit failure."""
    def __init__(self, config: ModelConfig):
        if config.model not in {"steady", "hasty"}:
            raise ValueError("mock model must be steady or hasty")
        self.model = config.model
        self.fixtures = json.loads(Path(__file__).with_name("mock_responses.json").read_text())
        self.calls: dict[str, int] = {}

    async def manifest(self) -> dict[str, Any]:
        return {"provider": "mock", "model": self.model, "digest": digest(self.fixtures), "version": "scripted-v1", "synthetic": True}

    async def generate(self, prompt: str, options: dict[str, Any]) -> Generation:
        key = hashlib.sha256(prompt.encode()).hexdigest()
        self.calls[key] = self.calls.get(key, 0) + 1
        fixture = self.fixtures.get(key, {}).get(self.model, {"text": "MOCK: unknown prompt"})
        await asyncio.sleep(fixture.get("delay", 0.01))
        if fixture.get("error") and self.calls[key] <= fixture.get("failures", 100):
            raise ProviderError(fixture["error"], retryable=True)
        return Generation(fixture.get("text", ""), metadata={"synthetic": True, "usage": "unavailable"})

    async def close(self) -> None:
        pass


class OllamaProvider:
    def __init__(self, config: ModelConfig, *, transport: httpx.AsyncBaseTransport | None = None):
        self.model = config.model
        endpoint = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        url = urlparse(endpoint)
        if url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1", "::1"} or url.username or url.password or url.query or url.fragment or url.path:
            raise ValueError("OLLAMA_HOST must be a loopback HTTP origin (for example http://127.0.0.1:11434)")
        self.client = httpx.AsyncClient(base_url=endpoint, timeout=None, trust_env=False, transport=transport)

    async def request(self, method: str, path: str, **kwargs: Any) -> dict:
        try:
            response = await self.client.request(method, path, **kwargs)
            if response.is_error:
                raise ProviderError(f"Ollama HTTP {response.status_code}", response.status_code in {408, 429} or response.status_code >= 500)
            data = response.json()
            if not isinstance(data, dict) or data.get("error"):
                raise ProviderError("Ollama returned an error or invalid object")
            return data
        except httpx.TransportError as exc:
            raise ProviderError(f"Ollama transport error: {type(exc).__name__}", True) from exc
        except ValueError as exc:
            raise ProviderError("Ollama returned invalid JSON") from exc

    async def manifest(self) -> dict[str, Any]:
        tags = await self.request("GET", "/api/tags")
        name = self.model if ":" in self.model else self.model + ":latest"
        model = next((m for m in tags.get("models", []) if m.get("name") == name), None)
        if not model or not model.get("digest"):
            raise ProviderError(f"Local model {name} not installed. Run: ollama pull {name}")
        show = await self.request("POST", "/api/show", json={"model": name})
        if show.get("remote_host") or show.get("remote_model") or name.endswith(":cloud"):
            raise ProviderError("Cloud-backed models are excluded from local benchmarks")
        version = await self.request("GET", "/api/version")
        return {"provider": "ollama", "model": name, "digest": model["digest"], "details": model.get("details", {}), "template": show.get("template"), "system": show.get("system"), "parameters": show.get("parameters"), "model_info": show.get("model_info", {}), "ollama_version": version.get("version"), "synthetic": False}

    async def generate(self, prompt: str, options: dict[str, Any]) -> Generation:
        data = await self.request("POST", "/api/generate", json={"model": self.model, "prompt": prompt, "stream": False, "options": options, "keep_alive": "5m"})
        if not isinstance(data.get("response"), str) or data.get("done") is not True:
            raise ProviderError("Ollama returned an incomplete response")
        counts = [data.get("prompt_eval_count"), data.get("eval_count")]
        if any(n is not None and (type(n) is not int or n < 0) for n in counts):
            raise ProviderError("Ollama returned invalid token counts")
        return Generation(data["response"], *counts, {k: v for k, v in data.items() if k != "response"})

    async def close(self) -> None:
        await self.client.aclose()


class ZaiProvider:
    """Optional remote adapter. Credentials never enter a config or manifest.

    HTTP 429 with provider code 1113 is a funding/access failure, not a transient
    rate limit. Stop the run instead of retrying every remaining benchmark task.
    """
    def __init__(self, config: ModelConfig, *, transport: httpx.AsyncBaseTransport | None = None):
        self.model = config.model
        self.key = os.environ.get("ZAI_API_KEY", "")
        if not self.key:
            raise ValueError("Set ZAI_API_KEY in the runner environment; never put it in a config or dashboard")
        self.endpoint = os.environ.get("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4").rstrip("/")
        if self.endpoint not in {"https://api.z.ai/api/paas/v4", "https://api.z.ai/api/coding/paas/v4"}:
            raise ValueError("ZAI_BASE_URL must be an official api.z.ai standard or Coding Plan endpoint")
        self.client = httpx.AsyncClient(base_url=self.endpoint + "/", timeout=None, trust_env=False,
                                       follow_redirects=False, transport=transport,
                                       headers={"Authorization": "Bearer " + self.key})

    def redact(self, value: Any) -> Any:
        if isinstance(value, str):
            return value.replace(self.key, "[REDACTED]")
        if isinstance(value, dict):
            return {self.redact(k): self.redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact(v) for v in value]
        return value

    async def manifest(self) -> dict[str, Any]:
        identity = {"provider": "zai", "model": self.model, "endpoint": self.endpoint}
        return {**identity, "digest": digest(identity), "identity_kind": "mutable API model alias, not a weight digest",
                "version": "zai-chat-v1", "synthetic": False, "remote": True,
                "availability_checked": False, "weights_revision_available": False}

    async def generate(self, prompt: str, options: dict[str, Any]) -> Generation:
        settings = ZaiOptions.model_validate(options).model_dump()
        payload = {"model": self.model, "messages": [{"role": "user", "content": prompt}],
                   "stream": False, **settings}
        try:
            response = await self.client.post("chat/completions", json=payload)
        except httpx.TransportError as exc:
            raise ProviderError(f"Z.ai transport error: {type(exc).__name__}", True) from None
        try:
            data = response.json()
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        if not response.is_success or data.get("error"):
            error = data.get("error") if isinstance(data.get("error"), dict) else {}
            candidate = str(error.get("code", ""))
            code = candidate if re.fullmatch(r"[a-zA-Z0-9_-]{1,16}", candidate) else None
            fatal = response.status_code in {401, 403} or code == "1113"
            retryable = not fatal and (response.status_code in {408, 429} or response.status_code >= 500)
            reason = ": insufficient balance or no resource package" if code == "1113" else ""
            # Never surface arbitrary response bodies, URLs or request headers.
            raise ProviderError(f"Z.ai HTTP {response.status_code}" + (f" (code {code})" if code else "") + reason,
                                retryable, fatal=fatal, code=code)
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderError("Z.ai returned no completion choices")
        choice = choices[0]
        message = choice.get("message") or {}
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ProviderError("Z.ai returned no text response")
        usage = data.get("usage") or {}
        if not isinstance(usage, dict):
            raise ProviderError("Z.ai returned invalid usage")
        counts = [usage.get("prompt_tokens"), usage.get("completion_tokens")]
        if any(n is not None and (type(n) is not int or n < 0) for n in counts):
            raise ProviderError("Z.ai returned invalid token counts")
        metadata = {"provider": "zai", "remote": True, "returned_model": data.get("model"),
                    "request_id": data.get("id"), "finish_reason": choice.get("finish_reason"),
                    "usage": usage, "reasoning_content": message.get("reasoning_content"),
                    "usage_note": "Output count is provider-reported; cached/reasoning details retained when present."}
        return Generation(self.redact(message["content"]), *counts, self.redact(metadata))

    async def close(self) -> None:
        await self.client.aclose()


def create_provider(config: ModelConfig) -> Provider:
    return {"mock": MockProvider, "ollama": OllamaProvider, "zai": ZaiProvider}[config.provider](config)
