"""Small provider access checks, explicitly excluded from benchmark scores."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import time

from .models import ModelConfig
from .providers import ProviderError, ZaiProvider


async def check_models(models: list[str]) -> dict:
    results = []
    settings = {"temperature": 1.0, "top_p": 1.0, "max_tokens": 128,
                "thinking": {"type": "enabled"}, "reasoning_effort": "low"}
    for model in models:
        provider = ZaiProvider(ModelConfig(id=model, provider="zai", model=model, options=settings))
        row = {"model": model, "checked_at": datetime.now(timezone.utc).isoformat(),
               "endpoint": provider.endpoint, "prompt": "Reply with only OK.", "settings": settings,
               "response": None, "usage": None, "score": None}
        start = time.perf_counter()
        try:
            async with asyncio.timeout(120):
                generation = await provider.generate(row["prompt"], settings)
            row.update(status="available", response=generation.text, usage=generation.metadata.get("usage"),
                       returned_model=generation.metadata.get("returned_model"), request_id=generation.metadata.get("request_id"))
        except ProviderError as exc:
            row.update(status="blocked" if exc.fatal else "error", error=str(exc), code=exc.code, retryable=exc.retryable)
        except TimeoutError:
            row.update(status="error", error="Provider check exceeded 120 seconds", retryable=True)
        finally:
            row["latency_ms"] = (time.perf_counter() - start) * 1000
            await provider.close()
        results.append(row)
        print(f"{model}: {row['status']}" + (f" — {row['error']}" if row.get("error") else ""), flush=True)
        # At most one probe per explicitly listed model; no automatic retries.
        await asyncio.sleep(1)
    return {"schema_version": 1, "kind": "provider_access_checks", "benchmark_results": False,
            "note": "Connectivity/access probes only. They do not produce benchmark quality scores. Unknown token usage and charges are not reported as zero.",
            "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=["glm-5.3", "glm-5.2"])
    parser.add_argument("--output", type=Path, default=Path("runs/glm/access.json"))
    parser.add_argument("--prompt-key", action="store_true", help="Read an API key without echoing or storing it")
    args = parser.parse_args()
    if args.prompt_key:
        os.environ["ZAI_API_KEY"] = getpass.getpass("Z.ai API key (input hidden): ")
    try:
        payload = asyncio.run(check_models(args.models))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"Access evidence: {args.output}")
        if any(r["status"] != "available" for r in payload["results"]):
            raise SystemExit(2)
    finally:
        if args.prompt_key:
            os.environ.pop("ZAI_API_KEY", None)


if __name__ == "__main__":
    main()
