"""Grade hand-written answers against hand-labelled outcomes, without a model."""
import json
import sys
import unittest
from test_profiles import HERE

sys.path.insert(0, str(HERE))
import judge


class Recorded(unittest.TestCase):
    def test_recorded_answers_and_pair_coverage(self):
        self.assertTrue((HERE / 'tests/answers.json').exists())
        cases = json.loads((HERE / 'tests/answers.json').read_text(encoding='utf-8'))
        pairs = {}
        for case in cases:
            pairs.setdefault((case['profile'], case['task']), set()).add(case['kind'])
            with self.subTest(case=case['id']):
                expected = case['expected']
                shell = case.get('parser')
                if shell and judge.syntax(shell, case['parser_probe']) is None:
                    expected = case['without_parser']
                result = judge.judge_answer(case['answer'], case['profile'], case['task'])
                self.assertEqual(result['status'], expected['status'])
                self.assertEqual([dict(status=r['status'], reason=r['reason']) for r in result['commands']],
                                 expected['commands'])
        complete = [p for p, kinds in pairs.items() if {'fitting', 'broken', 'question'} <= kinds]
        self.assertGreaterEqual(len(complete), 12)
