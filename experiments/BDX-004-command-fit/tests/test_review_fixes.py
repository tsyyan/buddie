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
                p = judge.load_profile(pid)
                req = judge.load_task(tid)['requirements'][pid]
                row = judge.judge_command(dict(text=text, shell=tag), p, req, {}, set())
                self.assertEqual(row['reason'], reason)  # validation order, after section selection

    def test_missing_python_module_precedes_the_tag(self):
        p = judge.load_profile('ubuntu2204-nosudo')
        req = judge.load_task('python-venv')['requirements'][p['id']]
        self.assertEqual(judge.judge_command(dict(text='python3 -m venv .venv', shell='powershell'),
                                           p, req, {}, set())['reason'], 'program_missing')

    def test_cross_family_tags_still_fail(self):
        for tag in ['bash', 'sh', 'zsh', 'shell', 'console']:
            self.assertEqual(grade('win11-cmd-nogpu', 'list-files', 'dir', tag)
                             ['reason'], 'wrong_os')

    def test_a_block_for_an_observed_other_shell_is_not_a_wrong_shell(self):
        # PROTOCOL v1: the cmd profile has Windows PowerShell, the PowerShell profile has cmd
        for pid, tag, text in [('win11-cmd-nogpu', 'powershell', 'Get-ChildItem'), ('win11-pwsh-nvidia', 'cmd', 'dir')]:
            row = grade(pid, 'list-files', text, tag)['commands'][0]
            expected = 'UNKNOWN' if tag == 'powershell' and judge.syntax('powershell', 'Get-ChildItem') is None else 'FITS'
            self.assertEqual((row['status'], row['reason']), (expected, None))
        self.assertEqual(grade('alpine-container', 'list-files', 'Get-ChildItem', 'powershell')
                         ['reason'], 'wrong_os')

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

    def test_quoted_bashism_text_is_not_a_shell_failure(self):
        for text in ["echo 'items=(one two)'", "echo 'use source here'", "echo 'x; [[ -d y ]]'"]:
            result = grade('alpine-container', 'list-files', text, 'bash')
            self.assertEqual(result['commands'][0]['status'], 'UNKNOWN')

    def test_foreign_tokenizer_cannot_prove_a_shell_failure(self):
        quoted = 'Write-Output ' + chr(34) + chr(96) + chr(34) * 2
        for pid, shell, text in [('win11-pwsh-nvidia', 'powershell', quoted),
                                 ('win11-cmd-nogpu', 'cmd', 'echo "unterminated')]:
            result = grade(pid, 'list-files', text, shell)
            self.assertEqual(result['commands'][0]['status'], 'UNKNOWN')


class AnswerOutcomes(unittest.TestCase):
    def test_unknown_only_and_mixed_answers_are_undecided(self):
        for text in ['python --imaginary', 'python --version\npython --imaginary']:
            result = grade('win11-cmd-nogpu', 'python-version', text, 'cmd')
            self.assertEqual(result['status'], 'UNDECIDED')
            self.assertEqual(result['unknown_commands'], 1)
            self.assertFalse(result['all_commands_decided'])

    def test_broken_takes_precedence_over_unknown(self):
        result = grade('win11-cmd-nogpu', 'python-version', 'python --imaginary\nconda --version', 'cmd')
        self.assertEqual(result['status'], 'BROKEN')
        self.assertEqual(result['unknown_commands'], 1)

    def test_ok_requires_only_fits_and_installs(self):
        result = grade('win11-cmd-nogpu', 'python-version', 'python --version', 'cmd')
        self.assertEqual(result['status'], 'OK')
        self.assertTrue(result['all_commands_decided'])
        self.assertEqual(result['unknown_commands'], 0)
