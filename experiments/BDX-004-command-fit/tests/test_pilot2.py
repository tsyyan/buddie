"""Pilot-2 rule changes: availability and syntax, with additive task constraints."""
import copy
import json
import unittest
from unittest.mock import patch
from test_judge import HERE, grade, judge


class Pilot2(unittest.TestCase):
    def test_install_intent_for_all_requested_managers(self):
        from installations import intent
        for text, package in [('apt install -y ffmpeg', 'ffmpeg'), ('dnf install ffmpeg -y', 'ffmpeg'),
                              ('apk add --no-cache ffmpeg', 'ffmpeg'), ('brew install node@20', 'node'),
                              ('winget install --id Gyan.FFmpeg --version 7.0', 'ffmpeg'),
                              ('choco install ffmpeg -y', 'ffmpeg'), ('pip install torch', 'torch'),
                              ('npm install -g typescript', 'typescript'), ('conda install ffmpeg', 'ffmpeg')]:
            with self.subTest(text=text):
                self.assertEqual(intent(text, 'bash')['installs'], [package])

    def test_unmatched_install_suppresses_missing_afterwards_even_if_uncertain(self):
        for pid, text in [('ubuntu2404-nvidia', 'sudo apt install -y ffmpeg'),
                          ('macos-arm', 'sudo brew install ffmpeg')]:
            for connector in ('\n', ' && '):
                with self.subTest(profile=pid, connector=connector), patch.object(judge, 'syntax', return_value=True):
                    rows = grade(pid, 'install-ffmpeg', text + connector + 'ffmpeg -version')['commands']
                    leaves = list(judge.leaf_commands(rows))
                    self.assertIn(leaves[-1]['status'], ('FITS', 'UNKNOWN'))
                    self.assertIsNone(leaves[-1]['reason'])

    def test_unknown_install_does_not_claim_presence_and_cannot_cross_sections(self):
        text = '## macOS\nRun `sudo brew install ffmpeg`.\n### Verify\nRun `ffmpeg -version`.'
        with patch.object(judge, 'syntax', return_value=True):
            result = judge.judge_answer(text, 'macos-arm', 'install-ffmpeg')
            self.assertEqual([r['status'] for r in result['commands']], ['UNKNOWN', 'UNKNOWN'])
            # Same system, separate declared sections: neither installation nor intent leaks.
            result = judge.judge_answer(text + '\n## macOS\nRun `ffmpeg -version`.', 'macos-arm', 'install-ffmpeg')
            self.assertEqual(result['commands'][-1]['reason'], 'program_missing')

    def test_task_declared_existing_venv_and_shell_specific_scripts(self):
        for pid, text in [('ubuntu2404-nvidia', 'source .venv/bin/activate'),
                          ('alpine-container', '. .venv/bin/activate')]:
            with self.subTest(profile=pid), patch.object(judge, 'syntax', return_value=True):
                self.assertEqual(grade(pid, 'activate-venv', text)['commands'][0]['status'], 'FITS')
        for suffix, shell in [('fish', 'fish'), ('csh', 'csh')]:
            p = judge.load_profile('ubuntu2404-nvidia')
            text = 'source .venv/bin/activate.' + suffix
            with patch.object(judge, 'syntax', return_value=True):
                self.assertEqual(judge.judge_answer('Run `' + text + '`.', p, 'activate-venv')['commands'][0]['status'], 'UNKNOWN')
                p['document']['categories']['system.shell']['observations'][shell] = dict(status='observed', value='test')
                self.assertEqual(judge.judge_answer('Run `' + text + '`.', p, 'activate-venv')['commands'][0]['status'], 'FITS')

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
