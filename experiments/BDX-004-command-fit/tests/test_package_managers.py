"""Distribution applicability and observed optional package managers."""
import unittest
from unittest.mock import patch
from test_judge import judge, grade


class PackageManagers(unittest.TestCase):
    def test_foreign_distribution_manager_is_wrong_os_before_sudo(self):
        for pid, text in [('fedora40', 'sudo apt install git'), ('ubuntu2404-nvidia', 'dnf install git'),
                          ('ubuntu2204-nosudo', 'sudo apk add git'), ('macos-arm', 'pacman -S git'),
                          ('alpine-container', 'sudo zypper install git')]:
            with self.subTest(pid=pid, text=text):
                self.assertEqual(grade(pid, 'install-git', text)['reason'], 'wrong_os')

    def test_observation_governs_brew_winget_and_choco(self):
        for pid, text in [('ubuntu2404-nvidia', 'brew install git'), ('win11-cmd-nogpu', 'winget install Git.Git')]:
            with self.subTest(pid=pid):
                self.assertEqual(grade(pid, 'install-git', text)['reason'], 'program_missing')
        p = judge.load_profile('ubuntu2404-nvidia')
        p['document']['categories']['software.package_managers']['observations']['brew'] = dict(status='observed', value='4.0')
        with patch.object(judge, 'syntax', return_value=True):
            self.assertIn(judge.judge_answer('Run `brew install git`.', p, 'install-git')['commands'][0]['status'], ('FITS', 'INSTALLS'))
