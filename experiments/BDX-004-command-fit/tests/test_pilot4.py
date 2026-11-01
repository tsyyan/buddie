"""Pilot-4 forms: executable identities, file proofs, userland and foreign cmdlets."""
import copy
import json
import unittest
from unittest.mock import patch
from test_judge import HERE, grade, judge


class ExecutablePaths(unittest.TestCase):
    def test_absolute_executable_uses_program_rules(self):
        for pid, task, text, status, reason in [
                ('ubuntu2404-nvidia', 'cuda-toolkit', '/usr/local/cuda/bin/nvcc -V', 'FITS', None),
                ('macos-arm', 'cuda-toolkit', '/usr/local/cuda/bin/nvcc --version', 'WONT_RUN', 'wrong_os'),
                ('win11-pwsh-nvidia', 'cuda-toolkit', '& "C:\\Program Files\\CUDA\\bin\\nvcc.exe" --version', 'WONT_RUN', 'program_missing')]:
            with self.subTest(text=text), patch.object(judge, 'syntax', return_value=True):
                row = grade(pid, task, text)['commands'][0]
                self.assertEqual((row['status'], row['reason']), (status, reason))
                self.assertEqual(row['text'], text)

    def test_absolute_path_cannot_bypass_version_constraint(self):
        p = judge.load_profile('win11-cmd-nogpu')
        p['document']['categories']['software.runtimes']['observations']['node'].update(
            status='observed', value='18.0.0', reason=None)
        row = judge.judge_answer('```cmd\n"C:\\Tools\\node.exe" --version\n```', p, 'install-node20')['commands'][0]
        self.assertEqual(row['reason'], 'version_mismatch')

    def test_cmd_absolute_syntax_and_powershell_inline_call_are_extracted(self):
        import commands
        self.assertTrue(judge.syntax('cmd', '"C:\\Tools\\git.exe" --version'))
        rows = commands.extract('Run `& "C:\\Tools\\nvcc.exe" --version`.')
        self.assertEqual(len(rows), 1)


class ForeignCmdlets(unittest.TestCase):
    def test_cmdlet_in_posix_only_profile_has_shell_reason(self):
        for text in ('Write-Output hello', 'Get-Item -Path .', 'Select-Object Name'):
            with self.subTest(text=text):
                self.assertEqual(grade('alpine-container', 'list-files', text)['reason'], 'wrong_shell_syntax')

    def test_real_hyphenated_program_is_not_a_cmdlet(self):
        for text in ('nvidia-smi', 'apt-get --version'):
            with patch.object(judge, 'syntax', return_value=True):
                self.assertNotEqual(grade('ubuntu2404-nvidia', 'list-files', text)['reason'], 'wrong_shell_syntax')


class DistroUserland(unittest.TestCase):
    def test_distribution_specific_network_and_service_tools(self):
        with patch.object(judge, 'syntax', return_value=True):
            for pid, text in [('ubuntu2404-nvidia', 'service ssh status'), ('wsl-ubuntu', 'ss -ltnp'),
                              ('wsl-ubuntu', 'nc -z localhost 8000'), ('fedora40', 'ncat -z localhost 8000'),
                              ('alpine-container', 'nc -z localhost 8000'), ('macos-arm', 'nc -z localhost 8000')]:
                with self.subTest(profile=pid, command=text):
                    self.assertEqual(grade(pid, 'port-process', text)['commands'][0]['status'], 'FITS')

    def test_unshipped_and_explicitly_missing_tools_are_not_assumed(self):
        with patch.object(judge, 'syntax', return_value=True):
            for pid, text in [('macos-arm', 'service ssh status'), ('alpine-container', 'ss -ltnp'),
                              ('ubuntu2404-nvidia', 'ncat -z localhost 8000')]:
                self.assertEqual(grade(pid, 'port-process', text)['commands'][0]['status'], 'UNKNOWN')
            p = judge.load_profile('wsl-ubuntu')
            p['document']['categories']['software.tools']['observations']['nc'] = dict(status='unavailable', reason='not_found_on_path', value=None)
            self.assertEqual(judge.judge_answer('Run `nc -z localhost 8000`.', p, 'port-process')['reason'], 'program_missing')

    def test_new_service_alias_does_not_bypass_admin(self):
        with patch.object(judge, 'syntax', return_value=True):
            self.assertEqual(grade('ubuntu2204-nosudo', 'service-restart', 'service ssh restart')['reason'], 'needs_admin')

