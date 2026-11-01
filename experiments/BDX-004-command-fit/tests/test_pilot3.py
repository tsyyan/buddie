"""Whole pilot answers and focused regressions for the last judge correction."""
import json
import hashlib
import unittest
from unittest.mock import patch
from test_judge import HERE, judge, grade


class Pipelines(unittest.TestCase):
    def test_explicit_linux_distro_parentheses_remain_constraints(self):
        import sections
        text = '## Linux (Debian/Ubuntu)\nRun `sudo apt install git`.'
        self.assertEqual(sections.select(text, judge.load_profile('alpine-container'))['commands_for_profile'], 0)
        self.assertEqual(sections.select(text, judge.load_profile('ubuntu2404-nvidia'))['commands_for_profile'], 1)

    def test_inline_only_alternatives_are_hedged_sections(self):
        import sections
        text = 'Install with `sudo apt install inxi` (Debian/Ubuntu) or `sudo dnf install inxi` (Fedora).'
        result = sections.select(text, judge.load_profile('fedora40'))
        self.assertEqual(result['targeting'], 'HEDGED')
        self.assertEqual([c['text'] for c in result['commands']], ['sudo dnf install inxi'])

    def test_audience_comments_do_not_split_quotes_or_control_units(self):
        import sections
        for text in ['echo "first\n# Windows\nconda --version\nlast"',
                     'if true; then\n# Windows\nls\nfi']:
            with self.subTest(text=text):
                rows = sections.select('```bash\n' + text + '\n```', judge.load_profile('ubuntu2404-nvidia'))['commands']
                self.assertEqual(len(rows), 1)
                with patch.object(judge, 'syntax', return_value=True):
                    self.assertEqual(grade('ubuntu2404-nvidia', 'list-files', text)['status'], 'OK')

    def test_all_ten_whole_answers_preserve_source_bytes_and_expected_outcomes(self):
        source = [json.loads(line) for line in (HERE / 'tests/pilot/pilot3_answers.jsonl').read_text(encoding='utf-8').splitlines()]
        cases = json.loads((HERE / 'tests/pilot3_answers.json').read_text(encoding='utf-8'))
        self.assertEqual(len(cases), 10)
        for case, original in zip(cases, source):
            with self.subTest(case=case['id']):
                self.assertEqual(case['answer'], original['answer'])
                self.assertEqual(hashlib.sha256(case['answer'].encode('utf-8')).hexdigest(), case['sha256'])
                if any(judge.syntax(shell, ':') is None for shell in ('bash', 'sh', 'powershell')):
                    self.skipTest('whole-answer outcome requires bash/dash/pwsh')
                result = judge.judge_answer(case['answer'], case['profile'], case['task'])
                self.assertEqual(result['status'], case['expected_status'])

    def test_table_pipeline_is_one_cell_and_output_is_not_a_command(self):
        import sections
        text = '## Linux\n| Tool | Command |\n|---|---|\n| PCI | `lspci | grep VGA` |\nTypical output:\n```\npython3  12345 alice  TCP *:8000 (LISTEN)\n```'
        rows = sections.select(text, judge.load_profile('ubuntu2404-nvidia'))['commands']
        self.assertEqual([r['text'] for r in rows], ['lspci | grep VGA'])

    def test_interpretation_table_header_is_not_an_instruction(self):
        import sections
        text = '## Linux\n| Output of `systemctl status/is-active` | Meaning |\n|---|---|\n| `active (running)` | Running |'
        self.assertEqual(sections.select(text, judge.load_profile('ubuntu2404-nvidia'))['commands'], [])

    def test_windows_whole_answer_keeps_inline_policy_command(self):
        case = json.loads((HERE / 'tests/pilot3_answers.json').read_text(encoding='utf-8'))[0]
        with patch.object(judge, 'syntax', return_value=True):
            rows = judge.judge_answer(case['answer'], case['profile'], case['task'])['commands']
            self.assertTrue(any(r['text'].startswith('Set-ExecutionPolicy ') for r in rows))


    def test_multi_system_heading_is_a_union(self):
        import sections
        text = '## Unix-like shells (Linux, macOS, WSL)\nRun `ls -la`.'
        for pid in ('macos-arm', 'wsl-ubuntu', 'ubuntu2404-nvidia', 'alpine-container'):
            with self.subTest(profile=pid):
                self.assertEqual(sections.select(text, judge.load_profile(pid))['commands_for_profile'], 1)
        self.assertFalse(sections.select(text, judge.load_profile('win11-cmd-nogpu'))['applicable'])

    def test_table_cells_and_post_command_audiences(self):
        import sections
        text = ('## Linux\n| Tool | Command | Notes |\n|---|---|---|\n'
                '| GPU | `nvidia-smi` | Install with `sudo apt install inxi` (Debian/Ubuntu) or `sudo dnf install inxi` (Fedora). |')
        for pid, selected in [('ubuntu2404-nvidia', ['nvidia-smi', 'sudo apt install inxi']),
                              ('fedora40', ['nvidia-smi', 'sudo dnf install inxi']),
                              ('alpine-container', ['nvidia-smi'])]:
            self.assertEqual([c['text'] for c in sections.select(text, judge.load_profile(pid))['commands']], selected)

    def test_git_bash_requires_its_own_observation(self):
        import sections
        text = '## Git Bash / MSYS2\n```bash\nls\n```'
        for pid in ('ubuntu2404-nvidia', 'win11-cmd-nogpu'):
            self.assertFalse(sections.select(text, judge.load_profile(pid))['applicable'])
        p = judge.load_profile('win11-cmd-nogpu')
        p['document']['categories']['system.shell']['observations']['git_bash'] = dict(status='observed', value='5.2')
        self.assertEqual(sections.select(text, p)['commands_for_profile'], 1)
        with patch.object(judge, 'syntax', return_value=True):
            result = judge.judge_answer(text, p, 'list-files')
            self.assertNotEqual(result['reason'], 'wrong_shell_syntax')

    def test_wsl_guest_can_refine_a_windows_host_heading(self):
        import sections
        text = '## Windows\n### Git Bash / MSYS2 / WSL on Windows\n```bash\nls\n```'
        self.assertEqual(sections.select(text, judge.load_profile('wsl-ubuntu'))['commands_for_profile'], 1)
        self.assertEqual(sections.select(text, judge.load_profile('ubuntu2404-nvidia'))['commands_for_profile'], 0)

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

