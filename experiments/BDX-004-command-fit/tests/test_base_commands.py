"""Base userland must be data-backed, shell-specific, and bounded by command forms."""
import copy
import unittest
from test_judge import judge


def base_grade(pid, text):
    task = copy.deepcopy(judge.load_task('list-files'))
    req = task['requirements'][pid]
    req['commands'] = []
    req['assumed_programs'] = []
    answer = f'```\n{text}\n```'
    return judge.judge_answer(answer, pid, task)


class BaseCommands(unittest.TestCase):
    def test_posix_userland_without_task_specific_whitelist(self):
        if judge.syntax('sh', ':') is None or judge.syntax('bash', ':') is None:
            self.skipTest('bash/dash parsers absent')
        for pid in ['ubuntu2404-nvidia', 'fedora40', 'alpine-container', 'macos-arm']:
            for text in ['ls', 'ls -la', 'mkdir output', 'mkdir -p output', 'rm -f temp.txt',
                         'tar -czf data.tar.gz data']:
                with self.subTest(profile=pid, command=text):
                    self.assertEqual(base_grade(pid, text)['commands'][0]['status'], 'FITS')

    def test_cmd_builtins_without_task_specific_whitelist(self):
        for text in ['dir', 'dir /b', 'mkdir output', 'del temp.txt', 'set', 'set APP_MODE=development']:
            with self.subTest(command=text):
                self.assertEqual(base_grade('win11-cmd-nogpu', text)['commands'][0]['status'], 'FITS')

    def test_core_powershell_cmdlets_without_task_specific_whitelist(self):
        if judge.syntax('powershell', 'Get-ChildItem') is None:
            self.skipTest('pwsh parser absent')
        for text in ['Get-ChildItem', 'Get-ChildItem -Force', 'New-Item -ItemType Directory output',
                     'Remove-Item temp.txt']:
            self.assertEqual(base_grade('win11-pwsh-nvidia', text)['commands'][0]['status'], 'FITS')

    def test_util_linux_subset_is_not_assumed_on_macos(self):
        if judge.syntax('bash', ':') is None:
            self.skipTest('bash parser absent')
        self.assertEqual(base_grade('ubuntu2404-nvidia', 'lsblk')['commands'][0]['status'], 'FITS')
        self.assertEqual(base_grade('macos-arm', 'lsblk')['commands'][0]['status'], 'UNKNOWN')

    def test_unknown_flags_and_foreign_userland_are_not_fits(self):
        for pid, text in [('win11-cmd-nogpu', 'ls -la'), ('ubuntu2404-nvidia', 'Get-ChildItem')]:
            with self.subTest(profile=pid, command=text):
                self.assertNotEqual(base_grade(pid, text)['commands'][0]['status'], 'FITS')

    def test_missing_observation_overrides_baseline_assumption(self):
        p = judge.load_profile('ubuntu2404-nvidia')
        p['document']['categories']['software.tools']['observations']['tar'].update(
            status='unavailable', value=None, reason='not_found_on_path')
        result = judge.judge_answer('```bash\ntar -czf data.tar.gz data\n```', p, 'archive-create')
        self.assertEqual(result['commands'][0]['reason'], 'program_missing')
