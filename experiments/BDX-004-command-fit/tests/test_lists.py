"""Lists preserve quote boundaries, verdicts and answer-local successful setup."""
import unittest
from test_judge import grade, judge


class Lists(unittest.TestCase):
    def require(self, shell):
        if judge.syntax(shell, ':') is None:
            self.skipTest(f'{shell} parser absent')

    def test_posix_lists_take_worst_verdict_and_keep_children(self):
        self.require('bash')
        for text, status, children in [
                ('ls && mkdir output; rm -f temp.txt', 'FITS', ['FITS'] * 3),
                ('ls || conda --version', 'WONT_RUN', ['FITS', 'WONT_RUN']),
                ('ls; python3 --imaginary', 'UNKNOWN', ['FITS', 'UNKNOWN'])]:
            with self.subTest(text=text):
                result = grade('ubuntu2404-nvidia', 'list-files', text, 'bash')['commands'][0]
                self.assertEqual(result['status'], status)
                self.assertEqual([c['status'] for c in result['commands']], children)

    def test_semicolons_inside_quotes_are_not_split(self):
        self.require('bash')
        result = grade('ubuntu2404-nvidia', 'list-files', "echo 'a; b && c || d'", 'bash')
        self.assertEqual(len(result['commands']), 1)
        self.assertNotIn('commands', result['commands'][0])

    def test_powershell_statements_are_split(self):
        self.require('powershell')
        result = grade('win11-pwsh-nvidia', 'list-files', 'Get-ChildItem; Get-Location', 'powershell')
        self.assertEqual(result['commands'][0]['status'], 'FITS')
        self.assertEqual(len(result['commands'][0]['commands']), 2)

    def test_create_then_activate_in_list_or_later_block(self):
        for pid, shell, activate in [('ubuntu2404-nvidia', 'bash', 'source .venv/bin/activate'),
                                     ('alpine-container', 'sh', '. .venv/bin/activate'),
                                     ('macos-arm', 'zsh', 'source .venv/bin/activate')]:
            self.require(shell)
            for separator in [' && ', '\n']:
                with self.subTest(profile=pid, separator=separator):
                    result = grade(pid, 'python-venv', 'python3 -m venv .venv' + separator + activate, 'bash')
                    self.assertEqual(result['status'], 'OK')
            answer = f'```bash\npython3 -m venv .venv\n```\n```sh\n{activate}\n```'
            self.assertEqual(judge.judge_answer(answer, pid, 'python-venv')['status'], 'OK')

    def test_activation_cannot_leak_from_another_answer_or_failed_setup(self):
        self.require('bash')
        self.assertEqual(grade('ubuntu2404-nvidia', 'python-venv', 'source .venv/bin/activate', 'bash')
                         ['commands'][0]['status'], 'UNKNOWN')
        result = grade('ubuntu2204-nosudo', 'python-venv',
                       'python3 -m venv .venv && source .venv/bin/activate', 'bash')
        self.assertEqual(result['status'], 'BROKEN')
        self.assertEqual(result['commands'][0]['commands'][1]['status'], 'UNKNOWN')

    def test_or_rhs_does_not_assume_failed_lhs_created_a_venv(self):
        self.require('bash')
        result = grade('ubuntu2404-nvidia', 'python-venv',
                       'python3 -m venv .venv || source .venv/bin/activate', 'bash')
        self.assertEqual(result['commands'][0]['commands'][1]['status'], 'UNKNOWN')

    def test_and_chain_before_or_keeps_install_state(self):
        self.require('bash')
        result = grade('fedora40', 'install-ffmpeg',
                       'sudo dnf install ffmpeg && ffmpeg -version || ls', 'bash')
        self.assertEqual(result['commands'][0]['status'], 'INSTALLS')
        self.assertEqual(result['commands'][0]['commands'][1]['status'], 'FITS')

    def test_bad_list_syntax_does_not_create_state(self):
        self.require('bash')
        answer = '```bash\npython3 -m venv .venv &&\n```\n```bash\nsource .venv/bin/activate\n```'
        result = judge.judge_answer(answer, 'ubuntu2404-nvidia', 'python-venv')
        self.assertEqual(result['commands'][0]['status'], 'WONT_RUN')
        self.assertEqual(result['commands'][1]['status'], 'UNKNOWN')

    def test_multiline_quotes_do_not_create_commands_from_literal_data(self):
        import commands
        for shell, head in [('bash', 'echo'), ('powershell', 'Write-Output')]:
            text = head + ' "first\nconda --version\nlast"'
            self.assertEqual(commands.extract(f'```{shell}\n{text}\n```'), [{'text': text, 'shell': shell}])

    def test_unfinished_and_line_is_joined_before_syntax_check(self):
        self.require('bash')
        text = 'python3 -m venv .venv &&\nsource .venv/bin/activate'
        self.assertEqual(grade('ubuntu2404-nvidia', 'python-venv', text, 'bash')['status'], 'OK')

    def test_mutations_and_unknown_commands_invalidate_venv_proofs(self):
        self.require('bash')
        for middle in ['rm -f .venv/bin/activate', 'mv .venv other', 'cp other .venv/bin/activate', 'cd other']:
            text = 'python3 -m venv .venv; ' + middle + '; source .venv/bin/activate'
            result = grade('ubuntu2404-nvidia', 'python-venv', text, 'bash')['commands'][0]
            self.assertEqual(result['commands'][-1]['status'], 'UNKNOWN')

    def test_list_mutation_invalidates_setup_from_an_earlier_block(self):
        self.require('bash')
        for middle in ['rm -f .venv/bin/activate; ls', 'rm -f .venv/bin/activate || ls']:
            answer = ('```bash\npython3 -m venv .venv\n```\n```bash\n' + middle +
                      '\n```\n```bash\nsource .venv/bin/activate\n```')
            self.assertEqual(judge.judge_answer(answer, 'ubuntu2404-nvidia', 'python-venv')
                             ['commands'][-1]['status'], 'UNKNOWN')
