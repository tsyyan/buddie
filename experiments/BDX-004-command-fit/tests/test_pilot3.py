"""Whole pilot answers and focused regressions for the last judge correction."""
import json
import hashlib
import unittest
from unittest.mock import patch
from test_judge import HERE, judge, grade


class Pipelines(unittest.TestCase):
    def test_each_stage_is_judged_and_the_worst_wins(self):
        for text, statuses in [('ps -ef | grep sshd', ['FITS', 'FITS']),
                               ('ls | conda --version', ['FITS', 'WONT_RUN']),
                               ('ls | unobserved-tool --help', ['FITS', 'UNKNOWN'])]:
            with self.subTest(text=text), patch.object(judge, 'syntax', return_value=True):
                row = grade('ubuntu2404-nvidia', 'list-files', text)['commands'][0]
                self.assertEqual([c['status'] for c in row['commands']], statuses)
                self.assertEqual(row['status'], max(statuses, key=judge.RANK.get))

    def test_filter_userland_and_powershell_pipeline(self):
        with patch.object(judge, 'syntax', return_value=True):
            for pid in ('alpine-container', 'macos-arm', 'fedora40'):
                row = grade(pid, 'list-files', "ps -ef | grep sshd | awk '{print $1}' | sed -n '1p' | sort | head | tail | wc -l | xargs echo")['commands'][0]
                self.assertEqual(row['status'], 'FITS')
            row = grade('win11-pwsh-nvidia', 'list-files', 'Get-Process | Select-Object Name', 'powershell')['commands'][0]
            self.assertEqual([c['status'] for c in row['commands']], ['FITS', 'FITS'])

    def test_quotes_and_list_precedence(self):
        with patch.object(judge, 'syntax', return_value=True):
            row = grade('ubuntu2404-nvidia', 'list-files', "echo 'a|b' | grep 'a|b'; ls || ls")['commands'][0]
            self.assertEqual(len(row['commands']), 3)
            self.assertEqual(len(row['commands'][0]['commands']), 2)

