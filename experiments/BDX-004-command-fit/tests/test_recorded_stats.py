"""The UNKNOWN share counts commands, including UNKNOWNs in broken answers."""
import unittest
from test_judge import judge
import recorded_stats


class RecordedStats(unittest.TestCase):
    def test_offered_and_selected_counts_are_distinct(self):
        case = dict(id='selection', profile='macos-arm', task='install-git',
                    answer='## Windows\n```powershell\nwinget install Git.Git\n```')
        summary = recorded_stats.summarize([case])
        self.assertEqual(summary['commands_total'], 1)
        self.assertEqual(summary['commands_for_profile'], 0)
        self.assertEqual(summary['commands'], 0)
        self.assertIsNone(summary['unknown_share'])
        self.assertEqual(summary['answer_outcomes'], {'BROKEN': 1})

    def test_broken_parent_does_not_hide_unknown_leaves(self):
        if judge.syntax('bash', ':') is None:
            self.skipTest('bash parser absent')
        case = dict(id='compound', profile='ubuntu2404-nvidia', task='list-files',
                    answer='```bash\nls; unobserved-tool --help; conda --version\n```')
        summary = recorded_stats.summarize([case])
        self.assertEqual(summary['commands'], 1)
        self.assertEqual(summary['unknown_commands'], 0)
        self.assertEqual(summary['leaf_commands'], 3)
        self.assertEqual(summary['unknown_leaf_commands'], 1)
        self.assertAlmostEqual(summary['unknown_leaf_share'], 1 / 3)
        result = judge.judge_answer(case['answer'], case['profile'], case['task'])
        self.assertFalse(result['all_commands_decided'])
        self.assertEqual(result['unknown_commands'], 1)

    def test_denominator_is_commands_not_answers(self):
        cases = [
            dict(id='good', profile='win11-cmd-nogpu', task='session-variable',
                 answer='```cmd\nset APP_MODE=development\n```'),
            dict(id='mixed', profile='win11-cmd-nogpu', task='python-version',
                 answer='```cmd\nunobserved-tool --help\nconda --version\n```'),
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
