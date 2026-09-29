"""Providers receive only the prompt and settings, never the answer or rubric."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from .models import ModelConfig, digest


@dataclass
class Generation:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ProviderError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


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


def create_provider(config: ModelConfig) -> Provider:
    return MockProvider(config) if config.provider == "mock" else OllamaProvider(config)
