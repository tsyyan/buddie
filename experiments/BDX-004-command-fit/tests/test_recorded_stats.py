"""The UNKNOWN share counts commands, including UNKNOWNs in broken answers."""
import unittest
from test_judge import judge
import recorded_stats


class RecordedStats(unittest.TestCase):
    def test_denominator_is_commands_not_answers(self):
        cases = [
            dict(id='good', profile='win11-cmd-nogpu', task='session-variable',
                 answer='```cmd\nset APP_MODE=development\n```'),
            dict(id='mixed', profile='win11-cmd-nogpu', task='python-version',
                 answer='```cmd\npython --imaginary\nconda --version\n```'),
            dict(id='question', profile='win11-cmd-nogpu', task='python-version',
                 answer='Which operating system do you use?')]
        summary = recorded_stats.summarize(cases)
        self.assertEqual(summary['answers'], 3)
        self.assertEqual(summary['commands'], 3)
        self.assertEqual(summary['unknown_commands'], 1)
        self.assertAlmostEqual(summary['unknown_share'], 1 / 3)
        self.assertEqual(summary['answer_outcomes'], {'OK': 1, 'BROKEN': 1, 'ASKED': 1})

    def test_empty_denominator_is_explicit(self):
        summary = recorded_stats.summarize([])
        self.assertEqual(summary['commands'], 0)
        self.assertIsNone(summary['unknown_share'])

    def test_comparison_keeps_original_and_expanded_denominators(self):
        cases = [dict(id=cid, profile='win11-cmd-nogpu', task='python-version',
                      answer='```cmd\npython --version\n```') for cid in ['original', 'new']]
        baseline = dict(commit='baseline', rows=[dict(id='original', commands=[dict(status='UNKNOWN')])])
        report = recorded_stats.compare(cases, baseline)
        self.assertEqual(report['before']['unknown_share'], 1)
        self.assertEqual(report['after_original']['commands'], 1)
        self.assertEqual(report['after_original']['unknown_commands'], 0)
        self.assertEqual(report['after_all']['commands'], 2)
        with self.assertRaises(ValueError):
            recorded_stats.compare(cases[1:], baseline)
