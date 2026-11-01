"""Grade hand-written answers against hand-labelled outcomes, without a model."""
import json
import sys
import unittest
from test_profiles import HERE

sys.path.insert(0, str(HERE))
import judge


class Recorded(unittest.TestCase):
    def test_list_and_control_records_have_literal_child_expectations(self):
        cases = json.loads((HERE / 'tests/answers.json').read_text(encoding='utf-8'))
        ids = {c['id'] for c in cases}
        self.assertTrue({'list-posix', 'list-powershell', 'venv-and-source', 'venv-and-dot',
                         'control-if', 'control-for', 'control-while', 'control-case'} <= ids)
        from judge import leaf_commands
        for case in cases:
            if 'expected_leaf_statuses' not in case:
                continue
            if judge.syntax(case['parser'], case['parser_probe']) is None:
                continue
            with self.subTest(case=case['id']):
                result = judge.judge_answer(case['answer'], case['profile'], case['task'])
                self.assertEqual([r['status'] for r in leaf_commands(result['commands'])],
                                 case['expected_leaf_statuses'])

    def test_review_cases_are_recorded_with_literal_expectations(self):
        cases = json.loads((HERE / 'tests/answers.json').read_text(encoding='utf-8'))
        by_id = {c['id']: c for c in cases}
        for cid, status in [('bash-on-macos', 'FITS'), ('bash-on-alpine', 'FITS'),
                            ('alpine-double-brackets', 'WONT_RUN'), ('alpine-array', 'WONT_RUN'),
                            ('powershell-on-cmd', 'WONT_RUN')]:
            self.assertIn(cid, by_id)
            self.assertEqual(by_id[cid]['expected']['commands'][0]['status'], status)

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
