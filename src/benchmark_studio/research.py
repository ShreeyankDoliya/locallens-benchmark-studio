"""Offline research assets and strict, credential-free upstream data preparation.

This module never performs model inference. Native benchmark harnesses own scoring.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
from pathlib import Path
from urllib.request import urlopen

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class DatasetSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    repository: HttpUrl
    revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    rows: int = Field(gt=0)
    evaluation_rows: int = Field(gt=0)
    split: str


class Benchmark(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    paper_title: str
    paper: HttpUrl
    repository: HttpUrl
    measures: str
    limitations: str
    protocol: str
    scope: str
    status: str


class PublishedScore(BaseModel):
    model_config = ConfigDict(extra="forbid")
    benchmark: str
    model: str
    score: float = Field(ge=0, le=100, allow_inf_nan=False)
    metric: str
    origin: str
    source: HttpUrl
    source_date: str
    protocol: str
    uncertainty: str | None = None

    @model_validator(mode="after")
    def published_only(self):
        if self.origin not in {"vendor_reported", "paper_reported"}:
            raise ValueError("Published references must not masquerade as local measurements")
        return self


class Catalog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = Field(ge=1, le=1)
    reviewed_on: str
    benchmarks: list[Benchmark]
    sources: list[DatasetSource]
    published_scores: list[PublishedScore]
    measured_glm_runs: list = Field(max_length=0)
    evaluation_status: str

    @model_validator(mode="after")
    def unique_benchmarks(self):
        ids = [b.id for b in self.benchmarks]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate benchmark ID")
        if any(s.id not in ids for s in self.sources):
            raise ValueError("Source refers to an unknown benchmark")
        return self


def load_catalog(path: Path) -> Catalog:
    return Catalog.model_validate_json(path.read_text())


def verify_dataset(data: bytes, source: DatasetSource) -> list[dict]:
    if hashlib.sha256(data).hexdigest() != source.sha256:
        raise ValueError(f"{source.id}: upstream data checksum mismatch")
    decoded = gzip.decompress(data) if source.path.endswith(".gz") else data
    rows = [json.loads(line) for line in decoded.splitlines() if line.strip()]
    if len(rows) != source.rows:
        raise ValueError(f"{source.id}: unexpected row count")
    required = {
        "humaneval": {"task_id", "prompt", "test", "entry_point", "canonical_solution"},
        "mbpp": {"task_id", "text", "test_list", "code"},
        "gsm8k": {"question", "answer"},
        "ifeval": {"key", "prompt", "instruction_id_list", "kwargs"},
    }[source.id]
    if any(not required.issubset(row) for row in rows):
        raise ValueError(f"{source.id}: missing required task fields")
    if source.id == "mbpp":
        rows = [r for r in rows if 11 <= r["task_id"] <= 510]
    if len(rows) != source.evaluation_rows:
        raise ValueError(f"{source.id}: incorrect evaluation split")
    ids = [r.get("task_id", r.get("key", i)) for i, r in enumerate(rows)]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{source.id}: duplicate task IDs")
    return rows


def prepare(catalog: Catalog, output: Path, limit: int) -> dict:
    """Fetch immutable public data; keep reference answers out of prompt payloads.

    The files remain upstream formats, not LocalLens exact-match tasks. These are
    selection manifests for native scorers, never fake substitute benchmarks.
    """
    if limit < 1:
        raise ValueError("limit must be positive")
    output.mkdir(parents=True, exist_ok=True)
    selections = []
    for source in catalog.sources:
        repository = str(source.repository).removeprefix("https://github.com/").rstrip("/")
        if str(source.repository).split('/')[2] != "github.com":
            raise ValueError("Only pinned public GitHub dataset sources are supported")
        target = output / (source.id + (".jsonl.gz" if source.path.endswith(".gz") else ".jsonl"))
        url = f"https://raw.githubusercontent.com/{repository}/{source.revision}/{source.path}"
        data = target.read_bytes() if target.exists() else urlopen(url, timeout=60).read()
        rows = verify_dataset(data, source)
        if not target.exists():
            target.write_bytes(data)
        # Hash ordering has stable membership without relying on Python RNG versions.
        indexed = [(str(r.get("task_id", r.get("key", i))), r) for i, r in enumerate(rows)]
        ordered = sorted(indexed, key=lambda item: hashlib.sha256(f"locallens-pilot-v1:{source.id}:{item[0]}".encode()).hexdigest())
        selections.append({"benchmark": source.id, "revision": source.revision,
                           "dataset_sha256": source.sha256, "split": source.split,
                           "population": len(rows), "task_ids": [i for i, _ in ordered[:limit]],
                           "selection": "sha256(locallens-pilot-v1:benchmark:id), ascending"})
    manifest = {"schema_version": 1, "inference_performed": False, "selections": selections}
    (output / "selection.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def check_terminal_repo(repo: Path, revision: str) -> list[dict]:
    """Inspect the exact official revision without executing task code."""
    import tomllib
    actual = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    if actual != revision:
        raise ValueError(f"Terminal-Bench checkout must be {revision}")
    dirty = subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True)
    if dirty.strip():
        raise ValueError("Terminal-Bench checkout has local changes")
    rows = []
    for config in sorted(repo.glob("*/task.toml")):
        task = config.parent
        data = tomllib.loads(config.read_text())
        files = [p for p in task.rglob("*") if p.is_file()]
        if not all((task / path).exists() for path in ("instruction.md", "solution/solve.sh", "tests/test.sh")):
            raise ValueError(f"Incomplete native task: {task.name}")
        hashes = {str(p.relative_to(task)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
        rows.append({"id": task.name, "category": data["metadata"]["category"],
                     "difficulty": data["metadata"]["difficulty"],
                     "agent_timeout_sec": data["agent"]["timeout_sec"],
                     "verifier_timeout_sec": data["verifier"]["timeout_sec"],
                     "environment": data["environment"],
                     "files_sha256": hashes})
    if len(rows) != 89:
        raise ValueError("Expected all 89 Terminal-Bench 2.0 tasks")
    return rows


def export_controls(jobs: list[Path], task_repo: Path, output: Path) -> dict:
    """Export only native oracle/no-op checks, never label them model results.

    Deliberately do not publish job config, environment values or exception
    messages, which may contain credentials. Evidence is an explicit allowlist.
    """
    revision = "69671fbaac6d67a7ef0dfec016cc38a64ef7a77c"
    check_terminal_repo(task_repo, revision)
    results = []
    for job in jobs:
        for path in sorted(job.glob("*/result.json")):
            raw = json.loads(path.read_text())
            info = raw["agent_info"]
            if info["name"] not in {"oracle", "nop"} or info.get("model_info") is not None:
                raise ValueError("Control export accepts oracle/nop only, not model evaluations")
            name = raw["task_name"]
            if Path(name).name != name or not (task_repo / name).is_dir():
                raise ValueError("Unknown task name in control")
            reward = (raw.get("verifier_result") or {}).get("rewards", {}).get("reward")
            if reward not in (0, 1) or raw.get("exception_info"):
                raise ValueError("Incomplete or errored control; inspect native logs first")
            ctrf = json.loads((path.parent / "verifier/ctrf.json").read_text())["results"]
            tests = [{"name": t["name"], "status": t["status"]} for t in ctrf["tests"]]
            if not tests or int(all(t["status"] == "passed" for t in tests)) != reward:
                raise ValueError("Verifier reward disagrees with individual tests")
            evidence_path = path.parent / "agent/oracle.txt"
            results.append({"job": job.name, "trial": raw["trial_name"], "task_id": name,
                            "agent": info["name"], "agent_version": info["version"],
                            "task_checksum": raw["task_checksum"], "reward": reward,
                            "started_at": raw["started_at"], "finished_at": raw["finished_at"],
                            "raw_result_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            "prompt": (task_repo / name / "instruction.md").read_text(),
                            "response": evidence_path.read_text() if evidence_path.exists() else "No commands executed (no-op control).",
                            "tests": tests,
                            "explanation": "Native task tests verify the resulting files. All tests must pass for reward 1."})
    if not results:
        raise ValueError("No completed control trials found")
    payload = {"schema_version": 1, "kind": "harness_controls", "benchmark": "Terminal-Bench 2.0",
               "revision": revision, "harness": "harbor==0.23.0", "results": results,
               "note": "Reference-solution and no-op controls only. No GLM inference and no model performance score."}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("dashboard/research/catalog.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    prep = sub.add_parser("prepare")
    prep.add_argument("--output", type=Path, default=Path("runs/research/sources"))
    prep.add_argument("--limit", type=int, default=10)
    inspect = sub.add_parser("inspect-terminal")
    inspect.add_argument("--repo", type=Path, required=True)
    inspect.add_argument("--output", type=Path, required=True)
    controls = sub.add_parser("export-controls")
    controls.add_argument("--jobs", type=Path, nargs="+", required=True)
    controls.add_argument("--repo", type=Path, required=True)
    controls.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    catalog = load_catalog(args.catalog)
    if args.command == "verify":
        print(f"Validated {len(catalog.benchmarks)} benchmarks and {len(catalog.published_scores)} published references; no GLM measurements.")
    elif args.command == "prepare":
        manifest = prepare(catalog, args.output, args.limit)
        for item in manifest["selections"]:
            print(f"{item['benchmark']}: {len(item['task_ids'])} selected / {item['population']} eligible tasks; SHA-256 verified")
    elif args.command == "export-controls":
        result = export_controls(args.jobs, args.repo, args.output)
        print(f"Exported {len(result['results'])} harness controls; no model measurements")
    else:
        revision = "69671fbaac6d67a7ef0dfec016cc38a64ef7a77c"
        rows = check_terminal_repo(args.repo, revision)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"schema_version": 1, "revision": revision, "tasks": rows}, indent=2) + "\n")
        print(f"Inspected {len(rows)} native Terminal-Bench tasks; no inference performed")


if __name__ == "__main__":
    main()
