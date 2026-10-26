import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis import summarize, paired_differences


def run(arm='A_direct', **kw):
    return dict(case='PR_CI', arm=arm, repetition=1, model='frozen-model', runtime='frozen-runtime',
                manifest_sha='1'*64, fixture_sha='2'*64, sampling_sha='3'*64, variant='baseline',
                buddie_sha='a' * 40, cache='cold', hooks=False, correct_completed=True,
                wall_clock_s=2, correction_turns=0, tools=[],
                usage={'input_tokens': 10, 'cache_read_tokens': 0, 'cache_creation_tokens': 1,
                       'output_tokens': 2, 'cost_usd': .02}, **kw)


class AnalysisTests(unittest.TestCase):
    def test_wrong_answer_spend_stays_in_cost_per_correct_task(self):
        a=run(); b=copy.deepcopy(a); b['correct_completed']=False
        summary=summarize([a,b])[0]
        self.assertEqual(summary['accuracy'], .5)
        self.assertEqual(summary['cost_per_correct_completed'], .04)

    def test_missing_usage_is_not_zero_or_inferred_from_bytes(self):
        a=run(); a['usage']={}
        summary=summarize([a])[0]
        self.assertIsNone(summary['total_cost_usd'])
        self.assertIsNone(summary['tokens']['input_tokens'])
        a['usage']={'input_tokens': None, 'cost_usd': None}
        self.assertIsNone(summarize([a])[0]['tokens']['input_tokens'])

    def test_pairs_do_not_pool_different_caches_and_report_signed_differences(self):
        a=run(); b=run('B_core'); b['wall_clock_s']=1
        self.assertEqual(paired_differences([a,b])[0]['wall_clock_B_minus_A_s'], -1)
        b['cache']='warm'
        self.assertTrue(all(not p['complete'] for p in paired_differences([a,b])))
        with self.assertRaises(ValueError):
            paired_differences([a,a])

    def test_different_fixtures_are_not_paired_or_pooled(self):
        a=run(); b=run('B_core'); b['fixture_sha']='4'*64
        self.assertTrue(all(not p['complete'] for p in paired_differences([a,b])))
        b['arm']='A_direct'
        self.assertEqual(len(summarize([a,b])), 2)

    def test_invalid_trace_metrics_are_rejected(self):
        for field,value in [('wall_clock_s', float('nan')), ('correction_turns', -1)]:
            r=run();r[field]=value
            with self.assertRaises(ValueError):
                summarize([r])
