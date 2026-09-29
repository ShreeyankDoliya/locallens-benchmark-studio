import json
from pathlib import Path
import tempfile
import unittest
from pydantic import ValidationError
from benchmark_studio.models import RunConfig, load_dataset
from test_scoring import task


class DatasetTests(unittest.TestCase):
    def load(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'data.jsonl'
            path.write_text('\n'.join(json.dumps(row) for row in rows))
            return load_dataset(path)

    def test_original_sample(self):
        tasks = load_dataset(Path('datasets/studio-sample-v1.jsonl'))
        self.assertEqual(len(tasks), 20)
        self.assertEqual(len({t.category for t in tasks}), 5)
        self.assertEqual(sum(t.variant != 'base' for t in tasks), 6)

    def test_rejects_duplicate_ids_and_empty_data(self):
        for rows in [[], [task().model_dump()] * 2]:
            with self.assertRaises(ValueError): self.load(rows)

    def test_invalid_fields_are_not_silently_accepted(self):
        for change in [{'expected': 3}, {'scoring': 'judge'}, {'prompt': ''}, {'category': 'unknown'}, {'unexpected': 'value'}, {'id': '../escape'}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.load([{**task().model_dump(), **change}])

    def test_versions_and_perturbation_invariants(self):
        base = task().model_dump()
        for change in [{'id':'t2','dataset_version':'v2'}, {'id':'t2'}, {'id':'t2','variant':'paraphrase','expected':'different'}, {'id':'t2','variant':'paraphrase','category':'grounding'}]:
            with self.subTest(change=change), self.assertRaises(ValueError): self.load([base, {**base, **change}])
        with self.assertRaises(ValueError): self.load([{**base, 'variant':'paraphrase'}])
        self.assertEqual(len(self.load([base, {**base, 'id':'t2','variant':'paraphrase'}])), 2)

    def test_duplicate_json_keys_and_nonfinite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.jsonl'
            for raw in ['{"id":"a","id":"b"}', '{"expected":NaN}']:
                path.write_text(raw)
                with self.assertRaisesRegex(ValueError, ':1:'): load_dataset(path)

    def test_config_validation(self):
        valid = json.loads(Path('configs/mock.json').read_text())
        for change in [{'concurrency':0}, {'concurrency':True}, {'timeout_seconds':0.0}, {'requests_per_second':-1.0}, {'retries':-1}, {'models':[valid['models'][0]] * 2}]:
            with self.subTest(change=change), self.assertRaises(ValidationError): RunConfig.model_validate({**valid, **change})
