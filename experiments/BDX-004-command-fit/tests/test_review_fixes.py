"""Regressions for the PR review's shell families and verdict semantics."""
import unittest
from test_judge import grade, judge


class ShellFamilies(unittest.TestCase):
    def test_posix_tags_share_a_family(self):
        if judge.syntax('sh', ':') is None:
            self.skipTest('dash parser absent')
        for pid in ['macos-arm', 'alpine-container']:
            for tag in ['bash', 'sh', 'zsh', 'shell', 'console']:
                with self.subTest(profile=pid, tag=tag):
                    result = grade(pid, 'session-variable', 'export APP_MODE=development', tag)
                    self.assertEqual(result['commands'][0]['status'], 'FITS')

    def test_os_and_missing_program_precede_cross_family_tag(self):
        for pid, tid, text, tag, reason in [
            ('macos-arm', 'gpu-check', 'nvidia-smi', 'powershell', 'wrong_os'),
            ('macos-arm', 'python-version', 'conda --version', 'cmd', 'program_missing'),
            ('win11-pwsh-nvidia', 'python-version', 'python3 --version', 'bash', 'program_missing')]:
            with self.subTest(profile=pid, text=text):
                self.assertEqual(grade(pid, tid, text, tag)['commands'][0]['reason'], reason)

    def test_cross_family_tags_still_fail(self):
        for tag in ['bash', 'sh', 'zsh', 'shell', 'console', 'powershell']:
            self.assertEqual(grade('win11-cmd-nogpu', 'list-files', 'dir', tag)
                             ['commands'][0]['reason'], 'wrong_shell_syntax')

    def test_sh_bashisms_survive_extraction_and_fail(self):
        for text in ['[[ -d output ]]', 'items=(one two)', 'source .venv/bin/activate']:
            with self.subTest(text=text):
                result = grade('alpine-container', 'list-files', text, 'bash')
                self.assertEqual(len(result['commands']), 1)
                self.assertEqual(result['commands'][0]['status'], 'WONT_RUN')
                self.assertEqual(result['commands'][0]['reason'], 'wrong_shell_syntax')

    def test_zsh_non_posix_syntax_is_unknown(self):
        for text in ['[[ -d output ]]', 'items=(one two)']:
            result = grade('macos-arm', 'list-files', text, 'zsh')
            self.assertEqual(result['commands'][0]['status'], 'UNKNOWN')
