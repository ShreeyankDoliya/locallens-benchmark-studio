"""Published evidence must remain independently reproducible without inference."""
import json
from pathlib import Path
import unittest

from benchmark_studio.analysis import markdown_report, verify_export

DATA = Path(__file__).resolve().parents[1] / 'dashboard' / 'data'


class PublishedReportTests(unittest.TestCase):
    def test_all_published_reports_recompute(self):
        reports = sorted(p for p in DATA.glob('*.json') if p.name != 'index.json')
        self.assertGreaterEqual(len(reports), 2)
        for path in reports:
            with self.subTest(report=path.name):
                data = verify_export(json.loads(path.read_text()))
                self.assertEqual(markdown_report(data), path.with_suffix('.md').read_text())

    def test_index_matches_published_files(self):
        index = json.loads((DATA / 'index.json').read_text())
        self.assertEqual(index['schema_version'], 1)
        self.assertEqual(len({r['id'] for r in index['runs']}), len(index['runs']))
        self.assertEqual({r['file'] for r in index['runs']}, {p.name for p in DATA.glob('*.json') if p.name != 'index.json'})
        for row in index['runs']:
            with self.subTest(run=row['id']):
                self.assertRegex(row['file'], r'^[a-zA-Z0-9][a-zA-Z0-9_-]*\.json$')
                self.assertEqual(row['report'], row['file'].removesuffix('.json') + '.md')
                data = json.loads((DATA / row['file']).read_text())
                self.assertEqual(data['run']['id'], row['id'])
                self.assertEqual(data['run']['status'], row['status'])
