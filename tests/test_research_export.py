import copy
import json
from pathlib import Path
import unittest

from benchmark_studio.models import digest
from benchmark_studio.research_export import summaries, report, validate_payload

ROOT = Path(__file__).resolve().parents[1]


class PublishedPilotTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads((ROOT / 'dashboard/research/measurements.json').read_text())

    def test_every_summary_recomputes_and_report_is_identical(self):
        validate_payload(self.payload)
        self.assertEqual(summaries(self.payload['results']), self.payload['summary'])
        self.assertEqual(report(self.payload), (ROOT / 'dashboard/research/report.md').read_text())
        self.assertEqual(len(self.payload['results']), 86)
        self.assertEqual({r['model'] for r in self.payload['results']}, {'glm-5.3', 'glm-5.3-flash'})
        self.assertEqual(len({(r['benchmark'],r['task_id'],r['model']) for r in self.payload['results']}),86)

    def test_tampered_response_or_aggregate_is_rejected(self):
        changed=copy.deepcopy(self.payload); changed['results'][0]['response']='changed'
        with self.assertRaisesRegex(ValueError,'fingerprint'): validate_payload(changed)
        changed=copy.deepcopy(self.payload); changed['summary'][0]['passed'] += 1
        changed['evidence_sha256']=digest({k:v for k,v in changed.items() if k!='evidence_sha256'})
        with self.assertRaisesRegex(ValueError,'Summary'): validate_payload(changed)

    def test_terminal_rewards_and_api_identities_reconcile(self):
        for r in self.payload['results']:
            if r['benchmark']=='terminal-bench':
                self.assertEqual(r['passed'],bool(r['judgment']['reward']))
                self.assertEqual(r['passed'],all(t['status']=='passed' for t in r['judgment']['tests']))
                self.assertTrue(r['evidence']['api_calls'])
                for call in r['evidence']['api_calls']:
                    if call['status']==200:
                        self.assertEqual(call['returned_model'],r['model'])
                        self.assertEqual(call['requested_model'],r['model'])
            elif not r['error']:
                self.assertEqual(r['evidence']['provider_metadata']['returned_model'],r['model'])
            self.assertTrue(r['prompt'])
            self.assertEqual(r['passed'],r['judgment']['passed'])

    def test_inconsistent_disagreement_flag_rejected(self):
        changed=copy.deepcopy(self.payload); changed['results'][0]['disagreement']=not changed['results'][0]['disagreement']
        changed['evidence_sha256']=digest({k:v for k,v in changed.items() if k!='evidence_sha256'})
        with self.assertRaisesRegex(ValueError,'Disagreement'): validate_payload(changed)
