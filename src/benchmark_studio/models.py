"""Strict, versioned input contracts. Unknown fields fail instead of being ignored."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Task(StrictModel):
    dataset_version: str = Field(min_length=1)
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    category: Literal["instruction_following", "structured_output", "reasoning", "grounding", "code"]
    prompt: str = Field(min_length=1)
    expected: Any
    scoring: Literal["exact", "normalized", "json"]
    group: str = Field(min_length=1)
    variant: Literal["base", "paraphrase", "irrelevant_context"] = "base"
    rubric: str = Field(min_length=1)

    @model_validator(mode="after")
    def check_expected(self) -> Task:
        if self.scoring != "json" and not isinstance(self.expected, str):
            raise ValueError("exact/normalized expected answer must be a string")
        return self


class ZaiOptions(StrictModel):
    temperature: float = Field(default=1.0, ge=0, le=2)
    top_p: float = Field(default=1.0, gt=0, le=1)
    max_tokens: int = Field(default=8192, ge=1, le=128000)
    thinking: dict[str, Literal["enabled"]] = Field(default_factory=lambda: {"type": "enabled"})
    reasoning_effort: Literal["low", "high", "max"] = "high"

    @model_validator(mode="after")
    def thinking_required(self):
        if self.thinking != {"type": "enabled"}:
            raise ValueError("Z.ai comparison requires thinking.type=enabled")
        return self


class ModelConfig(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    provider: Literal["mock", "ollama", "zai"]
    model: str = Field(min_length=1)
    options: dict[str, Any] = Field(default_factory=lambda: {"temperature": 0, "seed": 42, "num_predict": 256, "num_ctx": 2048})
    input_per_million: float | None = Field(default=None, ge=0)
    output_per_million: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def pricing_pair(self) -> ModelConfig:
        if (self.input_per_million is None) != (self.output_per_million is None):
            raise ValueError("provide both input and output prices or neither")
        if self.provider == "zai":
            self.options = ZaiOptions.model_validate(self.options).model_dump()
        return self


class RunConfig(StrictModel):
    name: str = Field(min_length=1)
    models: list[ModelConfig] = Field(min_length=2)
    concurrency: int = Field(default=1, ge=1, le=16)
    requests_per_second: float = Field(default=2.0, gt=0, le=1000)
    timeout_seconds: float = Field(default=120.0, gt=0, le=3600)
    retries: int = Field(default=2, ge=0, le=10)
    hardware_notes: str = Field(min_length=1)

    @model_validator(mode="after")
    def unique_models(self) -> RunConfig:
        if len({m.id for m in self.models}) != len(self.models):
            raise ValueError("model IDs must be unique")
        return self


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json(text: str) -> Any:
    return json.loads(text, parse_constant=reject_constant, object_pairs_hook=unique_object)


def load_dataset(path: Path) -> list[Task]:
    tasks = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            tasks.append(Task.model_validate(strict_json(line)))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{path}:{number}: {exc}") from exc
    if not tasks:
        raise ValueError("dataset must contain tasks")
    if len({task.id for task in tasks}) != len(tasks):
        raise ValueError("duplicate task ID")
    if len({task.dataset_version for task in tasks}) != 1:
        raise ValueError("dataset versions must agree")
    groups: dict[str, list[Task]] = {}
    for task in tasks:
        groups.setdefault(task.group, []).append(task)
    for name, group in groups.items():
        if sum(t.variant == "base" for t in group) != 1:
            raise ValueError(f"group {name} must have exactly one base task")
        if len({t.category for t in group}) != 1 or len({(t.scoring, canonical(t.expected)) for t in group}) != 1:
            raise ValueError(f"group {name} must preserve category, scoring and expected answer")
    return tasks
