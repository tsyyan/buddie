"""Catch incomplete or internally inconsistent experiment machines."""
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE.parents[1]))
from buddie import diagnostics as dg


class Profiles(unittest.TestCase):
    def test_profiles_are_complete_diagnostics(self):
        files = list((HERE / 'profiles').glob('*.json'))
        self.assertGreaterEqual(len(files), 9)
        index = json.loads((HERE / 'profiles/index.json').read_text())
        self.assertEqual(len({p['id'] for p in index}), len(index))
        for row in index:
            with self.subTest(profile=row['id']):
                doc = json.loads((HERE / 'profiles' / (row['id'] + '.json')).read_text())
                self.assertEqual(dg.problems(doc), [])
                self.assertEqual(row['provenance'], 'hand-built')
                self.assertTrue(row['description'])
                self.assertTrue(set(row['granted']) <= set(doc['categories']))
                baseline = dg.expand(['baseline'])
                self.assertTrue(baseline <= set(doc['categories']))
                for cid in baseline:
                    self.assertIn(doc['categories'][cid]['status'],
                                  ('collected', 'partial', 'unavailable'))
                for cid, entry in doc['categories'].items():
                    for name, obs in entry['observations'].items():
                        self.assertIn(name, dg.REGISTRY[cid].observations)
                        self.assertIn(obs['method'], dg.REGISTRY[cid].methods)
                        self.assertIn(obs['method'], [m['method'] for m in entry['methods']])


if __name__ == '__main__':
    unittest.main()
