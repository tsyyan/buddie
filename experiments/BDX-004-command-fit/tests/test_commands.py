"""Exercise extraction independently from command grading."""
import sys
import unittest
from test_profiles import HERE

sys.path.insert(0, str(HERE))
import commands


class Extraction(unittest.TestCase):
    def test_prompts_comments_output_and_continuations(self):
        text = ('```bash\n$ python3 -m pip install \\\n  requests # comment\n'
                'Successfully installed requests\n# ignore\necho "#literal"\n```\n'
                '```pwsh\nPS> Write-Output `\n "hello"\nhello\n```\n'
                '```cmd\nC:\\>set APP_MODE=dev\nREM comment\necho ^\n %APP_MODE%\n```')
        self.assertEqual(commands.extract(text), [
            {'text': 'python3 -m pip install requests', 'shell': 'bash'},
            {'text': 'echo "#literal"', 'shell': 'bash'},
            {'text': 'Write-Output "hello"', 'shell': 'powershell'},
            {'text': 'set APP_MODE=dev', 'shell': 'cmd'},
            {'text': 'echo %APP_MODE%', 'shell': 'cmd'}])

    def test_inline_and_fences_keep_answer_order(self):
        text = ('Run `git --version`, inspect `data.txt`, then:\n~~~sh\n'
                'export APP_MODE=development\n~~~\nUse `python3 --version`.\n'
                '```json\n{"command": "rm data.txt"}\n```\n'
                '```\ncurl --version\n```')
        self.assertEqual(commands.extract(text), [
            {'text': 'git --version', 'shell': 'unknown'},
            {'text': 'export APP_MODE=development', 'shell': 'sh'},
            {'text': 'python3 --version', 'shell': 'unknown'},
            {'text': 'curl --version', 'shell': 'unknown'}])

    def test_aliases_and_console_output(self):
        for tag, shell in [('ps1', 'powershell'), ('powershell', 'powershell'),
                           ('bat', 'cmd'), ('zsh', 'zsh'), ('shell', 'unknown'), ('console', 'unknown')]:
            with self.subTest(tag=tag):
                self.assertEqual(commands.extract(f'```{tag}\ngit --version\ngit version 2.47.0\n```'),
                                 [{'text': 'git --version', 'shell': shell}])

    def test_unknown_program_with_flags_and_unclosed_fence(self):
        self.assertEqual(commands.extract('```bash\nnew-tool --help\n'),
                         [{'text': 'new-tool --help', 'shell': 'bash'}])
        self.assertEqual(commands.extract('Use `a filename` and `3.12`.\n'), [])

    def test_compound_commands_are_not_silently_discarded(self):
        self.assertEqual(commands.extract('```bash\ngit --version && absent --help\n```'),
                         [{'text': 'git --version && absent --help', 'shell': 'bash'}])

    def test_quoted_executables_and_wrappers_survive_extraction(self):
        for text, shell in [('"nvidia-smi"', 'zsh'),
                            ('PYTHONPATH=. python3 -m venv .venv', 'bash'),
                            ('& nvidia-smi', 'powershell'),
                            ('"C:\\Program Files\\Python\\python.exe" --version', 'cmd'),
                            ('env APP_MODE=dev python3 --version', 'bash')]:
            with self.subTest(text=text):
                self.assertEqual(commands.extract(f'```{shell}\n{text}\n```'),
                                 [{'text': text, 'shell': shell}])

    def test_common_version_output_is_not_an_extra_command(self):
        text = ('```console\ncurl --version\ncurl 8.10.1 (x86_64-pc-linux-gnu)\n'
                'ffmpeg -version\nffmpeg version 7.0 Copyright\n'
                'python3 -m pip --version\npip 24.0 from /opt/python/site-packages/pip\n'
                'docker --version\nDocker version 27.0.1, build abc\n```')
        self.assertEqual([r['text'] for r in commands.extract(text)],
                         ['curl --version', 'ffmpeg -version', 'python3 -m pip --version', 'docker --version'])
