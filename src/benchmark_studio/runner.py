"""Bounded async workers, global start-rate limiting, durable per-attempt evidence."""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
import platform
import subprocess
import time
from typing import Callable

from . import __version__
from .models import RunConfig, Task, digest
from .providers import Provider, ProviderError, create_provider
from .scoring import SCORER_VERSION, score
from .storage import Store, now


def engine_digest() -> str:
    root = Path(__file__).parent
    files = sorted(root.glob("*.py")) + sorted(root.glob("*.json"))
    return hashlib.sha256(b"".join(p.name.encode() + p.read_bytes() for p in files)).hexdigest()


def hardware() -> dict:
    ram = None
    try:
        if platform.system() == "Darwin":
            ram = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True))
        else:
            ram = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, subprocess.SubprocessError, AttributeError):
        pass
    return {"os": platform.platform(), "architecture": platform.machine(), "cpu": platform.processor() or platform.machine(), "logical_cpus": os.cpu_count(), "ram_bytes": ram, "python": platform.python_version()}


class RateLimiter:
    def __init__(self, rate: float):
        self.interval = 1 / rate
        self.next_start = 0.0
        self.lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self.lock:
            await asyncio.sleep(max(0, self.next_start - time.monotonic()))
            self.next_start = time.monotonic() + self.interval


async def execute(store: Store, run_id: str, tasks: list[Task] | None = None,
                  config: RunConfig | None = None, *,
                  factory: Callable[..., Provider] = create_provider,
                  max_new_results: int | None = None) -> None:
    """Resume uses immutable snapshots, never mutable input files."""
    with store.writer_lock():
        existing = store.db.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone()
        if existing:
            run = store.run(run_id)
            snapshot = run["snapshot"]
            if snapshot["engine_sha256"] != engine_digest():
                raise ValueError("runner/scorer source changed; restore recorded revision or start a new run")
            tasks = [Task.model_validate(t) for t in snapshot["tasks"]]
            config = RunConfig.model_validate(snapshot["config"])
            if run["status"] == "completed":
                return
            if snapshot["hardware"] != hardware():
                raise ValueError("hardware/runtime changed; start a new run for a fair comparison")
        assert tasks is not None and config is not None
        providers: dict[str, Provider] = {}
        workers: list[asyncio.Task] = []
        created = bool(existing)
        try:
            manifests = {}
            for model in config.models:
                provider = factory(model)
                providers[model.id] = provider
                manifests[model.id] = await asyncio.wait_for(provider.manifest(), config.timeout_seconds)
            if existing:
                if snapshot["model_manifests"] != manifests:
                    raise ValueError("model digest, template or server version changed; start a new run")
            else:
                task_data = [t.model_dump() for t in tasks]
                snapshot = {"schema_version": 1, "studio_version": __version__, "scorer_version": SCORER_VERSION,
                            "engine_sha256": engine_digest(), "dataset_sha256": digest(task_data),
                            "config_sha256": digest(config.model_dump()), "dataset_version": tasks[0].dataset_version,
                            "tasks": task_data, "config": config.model_dump(), "hardware": hardware(), "model_manifests": manifests}
                store.create(run_id, snapshot)
                created = True
            store.recover(run_id)
            store.status(run_id, "running")
            done = {(r["model_id"], r["task_id"]) for r in store.results(run_id)}
            pending = [(model, task) for model in config.models for task in tasks if (model.id, task.id) not in done]
            if max_new_results is not None:
                pending = pending[:max_new_results]
            queue: asyncio.Queue = asyncio.Queue()
            for item in pending:
                queue.put_nowait(item)
            limiter = RateLimiter(config.requests_per_second)

            async def evaluate(model, task):
                history = store.attempts(run_id, model.id, task.id)
                failures = sum(a["status"] == "error" for a in history)
                while True:
                    await limiter.wait()
                    attempt_id, attempt = store.begin_attempt(run_id, model.id, task.id)
                    started = time.perf_counter()
                    generation = None
                    error = None
                    retryable = False
                    try:
                        generation = await asyncio.wait_for(providers[model.id].generate(task.prompt, model.options), config.timeout_seconds)
                    except (ProviderError, TimeoutError) as exc:
                        error = str(exc) or "Generation exceeded total timeout"
                        retryable = isinstance(exc, TimeoutError) or exc.retryable
                    except asyncio.CancelledError:
                        attempt.update(status="interrupted", ended_at=now(), latency_ms=(time.perf_counter() - started) * 1000, error="Runner interrupted")
                        store.finish_attempt(attempt_id, attempt)
                        raise
                    latency = (time.perf_counter() - started) * 1000
                    attempt.update(status="error" if error else "success", ended_at=now(), latency_ms=latency, error=error, retryable=retryable)
                    if error:
                        failures += 1
                    terminal = not error or not retryable or failures > config.retries
                    result = None
                    if terminal:
                        judgment = score(task, generation.text).to_dict() if generation else {"passed": False, "score": 0.0, "method": task.scoring, "kind": "deterministic", "version": SCORER_VERSION, "explanation": "Provider error; counted as a failed task. No answer was scored."}
                        result = {"run_id": run_id, "model_id": model.id, "task_id": task.id,
                                  "response": generation.text if generation else None, "judgment": judgment,
                                  "error": error, "latency_ms": latency,
                                  "input_tokens": generation.input_tokens if generation else None,
                                  "output_tokens": generation.output_tokens if generation else None,
                                  "provider_metadata": generation.metadata if generation else {},
                                  "completed_at": now()}
                    store.finish_attempt(attempt_id, attempt, result)
                    if terminal:
                        return
                    await asyncio.sleep(min(0.25 * 2 ** (failures - 1), 8))

            async def worker():
                while not queue.empty():
                    model, task = queue.get_nowait()
                    await evaluate(model, task)

            workers = [asyncio.create_task(worker()) for _ in range(min(config.concurrency, len(pending)))]
            await asyncio.gather(*workers)
            count = len(store.results(run_id))
            store.status(run_id, "completed" if count == len(tasks) * len(config.models) else "interrupted")
        except BaseException:
            for worker_task in workers:
                worker_task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            if created:
                store.status(run_id, "interrupted")
            raise
        finally:
            for provider in providers.values():
                await provider.close()
