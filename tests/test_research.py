import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from benchmark_studio.research import DatasetSource, PublishedScore, export_controls, load_catalog, prepare, verify_dataset

ROOT = Path(__file__).resolve().parents[1]


class ResearchTests(unittest.TestCase):
    def test_catalog_separates_references_and_missing_measurements(self):
        catalog = load_catalog(ROOT / "dashboard/research/catalog.json")
        self.assertEqual(len(catalog.benchmarks), 5)
        self.assertEqual(catalog.measured_glm_runs, [])
        self.assertTrue(all(s.origin in {"paper_reported", "vendor_reported"} for s in catalog.published_scores))
        self.assertTrue(all("pending" in b.status or "not run" in b.status for b in catalog.benchmarks))
        native = json.loads((ROOT / "dashboard/research/terminal-tasks.json").read_text())
        self.assertEqual(len(native["tasks"]), 89)
        self.assertEqual(len({t["id"] for t in native["tasks"]}), 89)
        for task in native["tasks"]:
            self.assertIn("instruction.md", task["files_sha256"])
            self.assertIn("tests/test.sh", task["files_sha256"])

    def test_cannot_label_external_score_as_measured(self):
        data = load_catalog(ROOT / "dashboard/research/catalog.json").published_scores[0].model_dump()
        for change in ({"origin": "measured"}, {"score": float("nan")}, {"score": 101}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                PublishedScore.model_validate({**data, **change})

    def test_upstream_hash_and_mbpp_split_are_enforced(self):
        rows = [{"task_id": n, "text": "prompt", "test_list": [], "code": "reference"} for n in [2, 11, 510, 511]]
        data = b"\n".join(json.dumps(r).encode() for r in rows)
        source = DatasetSource(id="mbpp", repository="https://github.com/google-research/google-research", revision="a"*40, path="mbpp/mbpp.jsonl", sha256=hashlib.sha256(data).hexdigest(), rows=4, evaluation_rows=2, split="test IDs 11–510")
        self.assertEqual([r["task_id"] for r in verify_dataset(data, source)], [11, 510])
        with self.assertRaisesRegex(ValueError, "checksum"):
            verify_dataset(data + b" ", source)
        with self.assertRaisesRegex(ValueError, "row count"):
            verify_dataset(data, source.model_copy(update={"rows": 5}))

    def test_preparation_is_repeatable_and_never_claims_inference(self):
        catalog = load_catalog(ROOT / "dashboard/research/catalog.json")
        rows = [{"question": f"question{i}", "answer": f"#### {i}"} for i in range(10)]
        raw = b"\n".join(json.dumps(r).encode() for r in rows)
        source = next(s for s in catalog.sources if s.id == "gsm8k").model_copy(update={"sha256": hashlib.sha256(raw).hexdigest(), "rows": 10, "evaluation_rows": 10})
        catalog.sources = [source]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            (output / "gsm8k.jsonl").write_bytes(raw)
            with patch("benchmark_studio.research.urlopen", side_effect=AssertionError("Should use verified local cache")):
                first = prepare(catalog, output, 3)
                second = prepare(catalog, output, 3)
            self.assertEqual(first, second)
            self.assertFalse(first["inference_performed"])
            self.assertEqual(len(first["selections"][0]["task_ids"]), 3)
            self.assertNotIn("question", json.dumps(first))

    def test_published_controls_reconcile_with_individual_tests(self):
        payload = json.loads((ROOT / "dashboard/research/controls.json").read_text())
        self.assertEqual(payload["kind"], "harness_controls")
        results = payload["results"]
        self.assertEqual({r["agent"] for r in results}, {"oracle", "nop"})
        for result in results:
            self.assertEqual(result["reward"], int(all(t["status"] == "passed" for t in result["tests"])))
            self.assertEqual(len(result["tests"]), 6)
            self.assertEqual(result["reward"], 1 if result["agent"] == "oracle" else 0)
            self.assertRegex(result["raw_result_sha256"], r"^[a-f0-9]{64}$")

    def test_control_export_rejects_model_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); trial = root / "job" / "trial"; trial.mkdir(parents=True)
            (trial / "result.json").write_text(json.dumps({"agent_info": {"name": "terminus-2", "model_info": {"name": "glm-5.3"}}}))
            with patch("benchmark_studio.research.check_terminal_repo", return_value=[]):
                with self.assertRaisesRegex(ValueError, "not model evaluations"):
                    export_controls([root / "job"], root, root / "out.json")
            self.assertFalse((root / "out.json").exists())
