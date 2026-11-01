"""Pilot-2 rule changes: availability and syntax, with additive task constraints."""
import copy
import json
import unittest
from unittest.mock import patch
from test_judge import HERE, grade, judge


class Pilot2(unittest.TestCase):
    def test_present_programs_do_not_need_a_form_whitelist(self):
        for pid, task, text in [('ubuntu2404-nvidia', 'download-file', 'curl -L -o data.txt https://example.org/data.txt'),
                                ('macos-arm', 'permissions', 'chmod +x script.sh'),
                                ('ubuntu2404-nvidia', 'cuda-toolkit', 'nvcc -V'),
                                ('alpine-container', 'list-files', 'ls --imaginary')]:
            with self.subTest(text=text), patch.object(judge, 'syntax', return_value=True):
                self.assertEqual(grade(pid, task, text)['commands'][0]['status'], 'FITS')

    def test_constraints_survive_unknown_flags(self):
        p = judge.load_profile('win11-cmd-nogpu')
        p['document']['categories']['software.runtimes']['observations']['node'].update(
            status='observed', value='18.0.0', reason=None)
        result = judge.judge_answer('Run `node --imaginary`.', p, 'install-node20')
        self.assertEqual(result['reason'], 'version_mismatch')

    def test_sudo_reason_priority_and_macos_uncertainty(self):
        for pid, tid, text, status, reason in [
                ('macos-arm', 'permissions', 'sudo chmod +x script.sh', 'UNKNOWN', None),
                ('macos-arm', 'install-git', 'sudo apt install git', 'WONT_RUN', 'wrong_os'),
                ('alpine-container', 'install-git', 'sudo apk add git', 'WONT_RUN', 'program_missing')]:
            with self.subTest(text=text), patch.object(judge, 'syntax', return_value=True):
                row = grade(pid, tid, text)['commands'][0]
                self.assertEqual((row['status'], row['reason']), (status, reason))

    def test_sudo_explicitly_missing_on_macos(self):
        p = judge.load_profile('macos-arm')
        p['document']['categories']['software.tools']['observations']['sudo'] = dict(
            status='unavailable', reason='not_found_on_path', value=None)
        self.assertEqual(judge.judge_answer('Run `sudo chmod +x script.sh`.', p, 'permissions')['reason'],
                         'program_missing')
