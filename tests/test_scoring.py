import unittest
from benchmark_studio.models import Task
from benchmark_studio.scoring import score


def task(method='exact', expected='Hello'):
    return Task(dataset_version='v1', id='t', category='reasoning', prompt='Test', expected=expected, scoring=method, group='g', rubric='Check')


class ScoringTests(unittest.TestCase):
    def test_exact_preserves_whitespace_and_case(self):
        self.assertTrue(score(task(), 'Hello').passed)
        for value in ['hello', 'Hello\n', ' Hello', 'Hello!']:
            self.assertFalse(score(task(), value).passed)

    def test_normalization_is_documented_and_not_substring(self):
        self.assertTrue(score(task('normalized', 'Hello world'), ' ＨＥＬＬＯ\n  WORLD ').passed)
        self.assertFalse(score(task('normalized'), 'Hello!').passed)
        self.assertFalse(score(task('normalized'), 'The answer is Hello').passed)

    def test_json_order_insensitive_but_strict_types(self):
        t = task('json', {'x': 1, 'y': True})
        self.assertTrue(score(t, '{"y":true,"x":1}').passed)
        for value in ['{"x":true,"y":true}', '{"x":1.0,"y":true}', '{"x":"1","y":true}', '{"x":1,"y":true,"z":0}', '```json\n{"x":1,"y":true}\n```', '{"x":1,"x":1,"y":true}', '{"x":NaN,"y":true}', '{} trailing']:
            with self.subTest(value=value):
                self.assertFalse(score(t, value).passed)

    def test_json_array_order_matters(self):
        self.assertFalse(score(task('json', [1, 2]), '[2,1]').passed)

    def test_all_judgments_are_traceable_deterministic(self):
        result = score(task(), 'Hello').to_dict()
        self.assertEqual(result['kind'], 'deterministic')
        self.assertEqual(result['version'], 'deterministic-v1')
        self.assertIn('PASS', result['explanation'])
