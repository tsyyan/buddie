import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import replay


class ReplayTests(unittest.TestCase):
    def test_same_source_map_reaches_direct_and_existing_buddie_adapters(self):
        result = replay.smoke()
        self.assertEqual(result['direct_pr_state'], 'open')
        self.assertEqual(result['receipt_outcomes'], {'PR_CI': 'PASS', 'FALSE_MERGE': 'FAIL'})
        self.assertEqual(sum(e['boundary'] == 'agent_tool' for e in result['metrics']), 3)
        self.assertTrue(any(e['boundary'] == 'github_http' for e in result['metrics']))
        self.assertIsNone(result['usage'])
        self.assertIsNone(result['cost_usd'])
