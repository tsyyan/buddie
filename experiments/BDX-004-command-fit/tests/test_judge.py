"""Pin conservative grading, parser-only checks, and sequential installation state."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_profiles import HERE

sys.path.insert(0, str(HERE))
import judge


def grade(pid, tid, command, shell=None):
    text = f'```{shell or ""}\n{command}\n```'
    return judge.judge_answer(text, pid, tid)


class Judge(unittest.TestCase):
    def test_proven_failures_do_not_need_host_parsers(self):
        cases = [
            ('macos-arm', 'gpu-check', 'nvidia-smi', 'wrong_os'),
            ('ubuntu2204-nosudo', 'install-git', 'sudo apt install git', 'needs_admin'),
            ('ubuntu2204-nosudo', 'python-venv', 'python3 -m venv .venv', 'program_missing'),
            ('wsl-ubuntu', 'pytorch-gpu', 'python3 -m pip install torch --index-url https://download.pytorch.org/whl/cu124', 'version_mismatch'),
            ('win11-pwsh-nvidia', 'python-venv', 'python3 -m venv .venv', 'program_missing'),
            ('ubuntu2404-nvidia', 'install-ffmpeg', 'apt install ffmpeg', 'needs_admin'),
        ]
        for pid, tid, command, reason in cases:
            with self.subTest(pid=pid, tid=tid):
                result = grade(pid, tid, command)
                self.assertEqual(result['status'], 'BROKEN')
                self.assertEqual(result['commands'][0]['reason'], reason)

    def test_shell_mismatch_and_syntax(self):
        self.assertEqual(grade('win11-pwsh-nvidia', 'session-variable', 'export APP_MODE=development', 'bash')
                         ['commands'][0]['reason'], 'wrong_shell_syntax')
        self.assertEqual(grade('alpine-container', 'session-variable', 'export APP_MODE=development', 'bash')
                         ['commands'][0]['reason'], 'wrong_shell_syntax')
        self.assertEqual(grade('win11-cmd-nogpu', 'session-variable', '$env:APP_MODE="development"')
                         ['commands'][0]['reason'], 'wrong_shell_syntax')

    def test_unknown_is_never_fits(self):
        with patch.object(judge, 'syntax', return_value=None):
            result = grade('ubuntu2404-nvidia', 'python-version', 'python3 --version')
        self.assertEqual(result['commands'][0]['status'], 'UNKNOWN')
        self.assertFalse(result['all_commands_decided'])
        self.assertEqual(grade('win11-cmd-nogpu', 'python-version', 'python --imaginary-flag')
                         ['commands'][0]['status'], 'UNKNOWN')
        self.assertEqual(grade('win11-cmd-nogpu', 'list-files', 'totally-new --help')
                         ['commands'][0]['status'], 'UNKNOWN')

    def test_cmd_fits_installs_and_state_is_local(self):
        answer = '```cmd\nffmpeg -version\nchoco install ffmpeg\nffmpeg -version\n```'
        # choco needs administrator privileges; give this scenario an elevated process.
        p = judge.load_profile('win11-cmd-nogpu')
        p['document']['categories']['system.permissions']['observations']['elevated']['value'] = True
        result = judge.judge_answer(answer, p, 'install-ffmpeg')
        self.assertEqual([r['status'] for r in result['commands']], ['WONT_RUN', 'INSTALLS', 'FITS'])
        self.assertEqual(grade('win11-cmd-nogpu', 'install-ffmpeg', 'ffmpeg -version')['status'], 'BROKEN')
        self.assertEqual(grade('win11-cmd-nogpu', 'session-variable', 'set APP_MODE=development')['status'], 'OK')

    def test_unrecognized_install_cannot_create_programs(self):
        answer = '```cmd\nchoco install ffmpeg --made-up\nffmpeg -version\n```'
        result = judge.judge_answer(answer, 'win11-cmd-nogpu', 'install-ffmpeg')
        self.assertEqual(result['commands'][-1]['status'], 'WONT_RUN')

    def test_profile_versions_and_inconclusive_observations(self):
        p = judge.load_profile('win11-cmd-nogpu')
        p['document']['categories']['software.runtimes']['observations']['node'].update(
            status='observed', value='18.0.0', reason=None)
        result = judge.judge_answer('```cmd\nnode --version\n```', p, 'install-node20')
        self.assertEqual(result['commands'][0]['reason'], 'version_mismatch')
        p['document']['categories']['software.runtimes']['observations']['node'].update(
            status='unavailable', value=None, reason='timeout')
        self.assertEqual(judge.judge_answer('```cmd\nnode --version\n```', p, 'install-node20')
                         ['commands'][0]['status'], 'UNKNOWN')

    def test_installed_version_satisfies_later_version_rule(self):
        p = judge.load_profile('win11-cmd-nogpu')
        p['document']['categories']['system.permissions']['observations']['elevated']['value'] = True
        answer = '```cmd\nchoco install nodejs --version=20.18.0\nnode --version\n```'
        result = judge.judge_answer(answer, p, 'install-node20')
        self.assertEqual([r['status'] for r in result['commands']], ['INSTALLS', 'FITS'])

    def test_powershell_curl_alias_is_not_assumed_native_curl(self):
        result = grade('win11-pwsh-nvidia', 'download-file',
                       'curl -o data.txt https://example.org/data.txt', 'powershell')
        self.assertEqual(result['commands'][0]['status'], 'UNKNOWN')

    def test_unlisted_python_alias_is_not_proven_absent(self):
        for alias in ['python', 'python3.12']:
            result = grade('ubuntu2404-nvidia', 'python-version', alias + ' --version')
            self.assertEqual(result['commands'][0]['status'], 'UNKNOWN')

    def test_node20_rejects_other_major_versions(self):
        p = judge.load_profile('win11-cmd-nogpu')
        p['document']['categories']['software.runtimes']['observations']['node'].update(
            status='observed', value='22.0.0', reason=None)
        result = judge.judge_answer('```cmd\nnode --version\n```', p, 'install-node20')
        self.assertEqual(result['commands'][0]['reason'], 'version_mismatch')

    def test_quoted_program_and_environment_wrappers_are_not_lost(self):
        result = grade('macos-arm', 'gpu-check', '"nvidia-smi"', 'zsh')
        self.assertEqual(result['status'], 'BROKEN')
        self.assertEqual(result['commands'][0]['reason'], 'wrong_os')
        for text, pid, tid, shell in [
                ('PYTHONPATH=. python3 -m venv .venv', 'ubuntu2204-nosudo', 'python-venv', 'bash'),
                ('& nvidia-smi', 'win11-pwsh-nvidia', 'gpu-check', 'powershell')]:
            result = grade(pid, tid, text, shell)
            self.assertEqual(result['commands'][0]['status'], 'UNKNOWN')

    def test_question_only_and_explanation(self):
        for text in ['Which operating system and shell are you using?', 'What Python version is installed?',
                     'Do you have an NVIDIA GPU?']:
            self.assertEqual(judge.judge_answer(text, 'macos-arm', 'python-version')['status'], 'ASKED')
        for text in ['I cannot offer commands yet.', 'Would you like some help?']:
            self.assertEqual(judge.judge_answer(text, 'macos-arm', 'python-version')['status'], 'NO_COMMANDS')

    def test_compounds_and_dynamic_code_are_unknown(self):
        for text in ['python --version && echo done', 'python --version > temp.txt', 'python $(evil)',
                     'choco install ffmpeg; ffmpeg -version']:
            self.assertEqual(grade('win11-cmd-nogpu', 'python-version', text)['commands'][0]['status'], 'UNKNOWN')

    def test_cli_outputs_json(self):
        with tempfile.TemporaryDirectory() as directory:
            answer = Path(directory) / 'answer.md'
            answer.write_text('```cmd\nset APP_MODE=development\n```', encoding='utf-8')
            run = subprocess.run([sys.executable, str(HERE / 'judge.py'), '--profile', 'win11-cmd-nogpu',
                                  '--task', 'session-variable', '--answer', str(answer)],
                                 capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)['status'], 'OK')

    def test_real_posix_parsers_only_parse(self):
        for shell in ['bash', 'sh']:
            if judge.syntax(shell, ':') is None:
                continue
            with self.subTest(shell=shell), tempfile.TemporaryDirectory() as directory:
                marker = Path(directory) / 'MUST_NOT_EXIST'
                self.assertTrue(judge.syntax(shell, f'touch "{marker.as_posix()}"'))
                self.assertFalse(marker.exists())
                self.assertFalse(judge.syntax(shell, 'if then'))
            return
        self.skipTest('bash/dash/busybox parser absent')

    def test_real_powershell_parser_only_parses(self):
        if judge.syntax('powershell', 'Write-Output ok') is None:
            self.skipTest('pwsh parser absent')
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'MUST_NOT_EXIST'
            self.assertTrue(judge.syntax('powershell', f'New-Item "{marker}"'))
            self.assertFalse(marker.exists())
        self.assertFalse(judge.syntax('powershell', 'if ('))
