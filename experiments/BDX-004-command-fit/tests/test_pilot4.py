"""Pilot-4 forms: executable identities, file proofs, userland and foreign cmdlets."""
import copy
import json
import unittest
from unittest.mock import patch
from test_judge import HERE, grade, judge


class ExecutablePaths(unittest.TestCase):
    def test_placeholder_executable_path_is_not_an_observed_program_path(self):
        with patch.object(judge, 'syntax', return_value=True):
            self.assertEqual(grade('ubuntu2404-nvidia', 'cuda-toolkit', '/full/path/to/nvcc --version')['commands'][0]['status'], 'UNKNOWN')

    def test_attached_powershell_call_operator_keeps_executable_identity(self):
        result = grade('win11-pwsh-nvidia', 'cuda-toolkit', '&"C:\\Tools\\nvcc.exe" --version', 'powershell')
        self.assertEqual(result['reason'], 'program_missing')

    def test_path_normalization_does_not_erase_unquoted_shell_operators(self):
        with patch.object(judge, 'syntax', return_value=True):
            row = grade('win11-cmd-nogpu', 'install-git', 'C:\\tools&other\\git.exe --version')['commands'][0]
            self.assertNotEqual(row['status'], 'FITS')

    def test_empty_powershell_invocation_does_not_crash(self):
        p = judge.load_profile('win11-pwsh-nvidia')
        req = judge.load_task('list-files')['requirements'][p['id']]
        row = judge.judge_command(dict(text='&', shell='powershell'), p, req, {}, set())
        self.assertIn(row['status'], ('UNKNOWN', 'WONT_RUN'))

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
    def test_service_force_reload_needs_admin(self):
        self.assertEqual(grade('ubuntu2204-nosudo', 'service-restart', 'service ssh force-reload')['reason'], 'needs_admin')

    def test_distribution_specific_network_and_service_tools(self):
        with patch.object(judge, 'syntax', return_value=True):
            for pid, text in [('ubuntu2404-nvidia', 'service ssh status'), ('wsl-ubuntu', 'ss -ltnp'),
                              ('wsl-ubuntu', 'nc -z localhost 8000'), ('fedora40', 'ncat -z localhost 8000'),
                              ('alpine-container', 'nc -z localhost 8000'), ('macos-arm', 'nc -z localhost 8000')]:
                with self.subTest(profile=pid, command=text):
                    self.assertEqual(grade(pid, 'port-process', text)['commands'][0]['status'], 'FITS')

    def test_unlisted_and_explicitly_missing_tools_are_not_assumed(self):
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


class FileExecution(unittest.TestCase):
    def test_pilot_shaped_recordings_have_literal_expected_outcomes(self):
        cases = json.loads((HERE / 'tests/pilot4_answers.json').read_text(encoding='utf-8'))
        self.assertEqual(len(cases), 18)
        for case in cases:
            with self.subTest(case=case['id']):
                if 'FITS' in case['expected_statuses'] and judge.syntax(case['parser'], 'echo ok') is None:
                    self.skipTest('success outcome needs profile parser')
                result = judge.judge_answer(case['answer'], case['profile'], case['task'])
                self.assertEqual([r['status'] for r in result['commands']], case['expected_statuses'])
                self.assertEqual([r['reason'] for r in result['commands']], case['expected_reasons'])

    def test_absolute_mutations_invalidate_file_and_venv_proofs(self):
        with patch.object(judge, 'syntax', return_value=True):
            self.assertEqual(grade('ubuntu2404-nvidia', 'permissions', '/bin/rm -f script.sh\n./script.sh')['commands'][-1]['status'], 'UNKNOWN')
            result = grade('ubuntu2404-nvidia', 'python-venv', 'python3 -m venv .venv\n/bin/rm -f .venv/bin/activate\nsource .venv/bin/activate')
            self.assertEqual(result['commands'][-1]['status'], 'UNKNOWN')

    def test_curl_requires_a_single_literal_url_and_output_pair(self):
        with patch.object(judge, 'syntax', return_value=True):
            for first in ('curl -o local.sh', 'curl -o local.sh -o other.sh https://example.org/file'):
                result = grade('ubuntu2404-nvidia', 'download-file', first + '\n./local.sh')
                self.assertEqual(result['commands'][-1]['status'], 'UNKNOWN')

    def test_task_or_earlier_command_provides_the_file(self):
        for tid, text, expected in [('permissions', './script.sh', ['FITS']),
                                    ('list-files', './script.sh', ['UNKNOWN']),
                                    ('list-files', 'touch local.sh\n./local.sh', ['FITS', 'FITS']),
                                    ('permissions', 'chmod +x /opt/tools/script.sh\n/opt/tools/script.sh', ['FITS', 'FITS'])]:
            with self.subTest(text=text), patch.object(judge, 'syntax', return_value=True):
                self.assertEqual([r['status'] for r in grade('ubuntu2404-nvidia', tid, text)['commands']], expected)

    def test_placeholder_and_removed_files_never_gain_presence(self):
        task = copy.deepcopy(judge.load_task('permissions'))
        task['requirements']['ubuntu2404-nvidia']['provided_files'] = ['/full/path/to/script.sh']
        with patch.object(judge, 'syntax', return_value=True):
            self.assertEqual(judge.judge_answer('Run `/full/path/to/script.sh`.', 'ubuntu2404-nvidia', task)['commands'][0]['status'], 'UNKNOWN')
            result = grade('ubuntu2404-nvidia', 'permissions', 'rm -f script.sh\n./script.sh')
            self.assertEqual(result['commands'][-1]['status'], 'UNKNOWN')

    def test_conditional_and_failed_creation_do_not_escape(self):
        with patch.object(judge, 'syntax', return_value=True):
            for first in ('if true; then touch local.sh; fi', 'unobserved-tool --help && touch local.sh'):
                result = grade('ubuntu2404-nvidia', 'list-files', first + '\n./local.sh')
                self.assertEqual(result['commands'][-1]['status'], 'UNKNOWN')

    def test_downloaded_literal_output_can_provide_a_file(self):
        with patch.object(judge, 'syntax', return_value=True):
            for first, expected in [('curl -fLo local.sh https://example.org/script.sh', 'FITS'),
                                    ('curl --help -o local.sh', 'UNKNOWN')]:
                result = grade('ubuntu2404-nvidia', 'download-file', first + '\n./local.sh')
                self.assertEqual(result['commands'][-1]['status'], expected)

