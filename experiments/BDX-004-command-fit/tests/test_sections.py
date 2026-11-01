"""Only instructions addressed to this profile may cause a machine-fit objection."""
import json
import unittest
from test_judge import HERE, judge
import sections


class Sections(unittest.TestCase):
    def test_mapping_covers_os_distro_manager_runtime_and_shell(self):
        for label, axis, values in [('On macOS', 'os', ['darwin']),
                ('Windows (PowerShell)', 'shell', ['powershell']),
                ('Debian/Ubuntu', 'distro', ['debian', 'ubuntu']),
                ('Fedora', 'package_manager', ['dnf']), ('Alpine', 'distro', ['alpine']),
                ('WSL', 'runtime', ['wsl'])]:
            with self.subTest(label=label):
                self.assertEqual(sections.identify(label)[axis], values)

    def test_four_os_answer_selects_only_matching_pair(self):
        example = json.loads((HERE / 'tests/multi_section_answers.json').read_text())[0]
        selected = sections.select(example['answer'], judge.load_profile('macos-arm'))
        self.assertEqual(selected['targeting'], 'HEDGED')
        self.assertEqual(selected['commands_total'], 8)
        self.assertEqual([r['text'] for r in selected['commands']], ['brew install git', 'git --version'])

    def test_no_matching_section_is_wrong_os_not_no_commands(self):
        result = judge.judge_answer('## Windows\n```powershell\nwinget install Git.Git\n```',
                                   'macos-arm', 'install-git')
        self.assertEqual((result['status'], result['reason']), ('BROKEN', 'wrong_os'))
        self.assertEqual(result['commands_total'], 1)
        self.assertEqual(result['commands_for_profile'], 0)
        self.assertEqual(result['commands'], [])

    def test_nested_verify_inherits_but_peer_verify_is_shared(self):
        text = ('## macOS\n```bash\nbrew install ffmpeg\n```\n### Verify\nRun `ffmpeg -version`.\n'
                '## Debian/Ubuntu\n```bash\nsudo apt install ffmpeg\n```\n'
                '## Verify installation\nRun `ffmpeg -version`.')
        selected = sections.select(text, judge.load_profile('macos-arm'))
        self.assertEqual([c['text'] for c in selected['commands']],
                         ['brew install ffmpeg', 'ffmpeg -version', 'ffmpeg -version'])
        self.assertFalse(sections.select(text, judge.load_profile('fedora40'))['applicable'])

    def test_inline_labels_and_commands_on_same_line(self):
        text = '**macOS:** Run `brew install git`.\n**Fedora:** Run `sudo dnf install git`.'
        self.assertEqual([c['text'] for c in sections.select(text, judge.load_profile('macos-arm'))['commands']],
                         ['brew install git'])

    def test_unselected_setup_cannot_establish_a_venv(self):
        text = ('## macOS\n```bash\npython3 -m venv .venv\n```\n'
                '## Ubuntu\n```bash\nsource .venv/bin/activate\n```')
        result = judge.judge_answer(text, 'ubuntu2404-nvidia', 'python-venv')
        self.assertEqual(result['status'], 'UNDECIDED')
        self.assertEqual((result['commands_total'], result['commands_for_profile']), (2, 1))

    def test_no_sections_preserves_whole_answer_behavior(self):
        result = judge.judge_answer('Run `git --version`.', 'win11-cmd-nogpu', 'install-git')
        self.assertEqual(result['targeting'], 'TARGETED')
        self.assertEqual((result['commands_total'], result['commands_for_profile']), (1, 1))
        self.assertEqual(result['status'], 'OK')

    def test_posix_label_is_not_a_linux_only_label(self):
        text = 'In a POSIX shell:\n```bash\nls\n```\nPowerShell:\n```powershell\nGet-ChildItem\n```'
        self.assertEqual([c['text'] for c in sections.select(text, judge.load_profile('macos-arm'))['commands']], ['ls'])

    def test_matching_os_heading_does_not_hide_unavailable_tagged_shell(self):
        result = judge.judge_answer('## Linux\n```powershell\nGet-ChildItem\n```',
                                   'ubuntu2404-nvidia', 'list-files')
        self.assertEqual((result['status'], result['reason']), ('BROKEN', 'wrong_os'))
