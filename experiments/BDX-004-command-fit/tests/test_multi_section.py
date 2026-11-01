"""Twelve hand-written multi-OS answers, with literal expectations for 31 profiles."""
import json
import unittest
from test_judge import HERE, judge

PARSERS = {'macos-arm': ['zsh'], 'win11-pwsh-nvidia': ['powershell'],
           'win11-cmd-nogpu': ['powershell', 'cmd'], 'ubuntu2404-nvidia': ['bash'],
           'ubuntu2204-nosudo': ['bash'], 'fedora40': ['bash'], 'alpine-container': ['sh'], 'wsl-ubuntu': ['bash']}


class MultiSection(unittest.TestCase):
    def test_realistic_multi_os_answers(self):
        cases = json.loads((HERE / 'tests/multi_section_answers.json').read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(cases), 10)
        self.assertEqual(len({c['answer'] for c in cases}), len(cases))
        for case in cases:
            for expected in case['checks']:
                with self.subTest(answer=case['id'], profile=expected['profile']):
                    result = judge.judge_answer(case['answer'], expected['profile'], case['task'])
                    status = expected['status']
                    if status == 'OK' and any(judge.syntax(s, 'Get-ChildItem' if s == 'powershell' else 'dir' if s == 'cmd' else ':') is None
                                              for s in PARSERS[expected['profile']]):
                        status = 'UNDECIDED'
                    self.assertEqual(result['status'], status)
                    for key in ('commands_total', 'commands_for_profile', 'targeting'):
                        self.assertEqual(result[key], expected[key])
                    if 'reason' in expected:
                        self.assertEqual(result['reason'], expected['reason'])

