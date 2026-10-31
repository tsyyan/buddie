"""Keep task rules and the deterministic eligible-unit manifest usable."""
import json
import re
import unittest
from test_profiles import HERE


class Tasks(unittest.TestCase):
    def test_coverage_and_requirements(self):
        self.assertTrue((HERE / 'tasks/tasks.json').exists())
        tasks = json.loads((HERE / 'tasks/tasks.json').read_text())
        profiles = json.loads((HERE / 'profiles/index.json').read_text())
        ids = {p['id'] for p in profiles}
        self.assertGreaterEqual(len(tasks), 24)
        self.assertEqual(len({t['id'] for t in tasks}), len(tasks))
        self.assertGreaterEqual(sum(t['shell_dependent'] for t in tasks), len(tasks) / 3)
        expected = []
        for task in tasks:
            applicable = ids if task['applies_to'] == 'all' else set(task['applies_to'])
            self.assertTrue(applicable <= ids)
            self.assertEqual(set(task['requirements']), applicable)
            self.assertTrue(task['prompt'] and task['categories'])
            for pid, req in task['requirements'].items():
                self.assertIn(req['shell'], ('bash', 'zsh', 'powershell', 'cmd', 'sh'))
                self.assertTrue(req['commands'])
                for rule in req['commands']:
                    re.compile(rule['pattern'])
                    self.assertIn(rule['effect'], ('FITS', 'INSTALLS'))
                expected.append([pid, task['id']])
        units = json.loads((HERE / 'tasks/units.json').read_text())
        self.assertEqual(units['seed'], 4)
        self.assertEqual(sorted(units['pairs']), sorted(expected))
        self.assertEqual(len(units['pairs']), len(set(map(tuple, units['pairs']))))
