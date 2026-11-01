"""Client-only baseline facts remain distinct from the ungranted daemon."""
import json
import unittest
from unittest.mock import patch
from test_judge import HERE, judge, grade
from test_profiles import dg
import tool


class ContainerBaseline(unittest.TestCase):
    def test_client_versions_use_only_baseline_client_facts(self):
        p = tool.load_profile('ubuntu2404-nvidia')
        p['document']['categories']['software.containers']['observations']['docker_client'].update(
            status='observed', value='27.3.1', reason=None)
        with patch.object(judge, 'syntax', return_value=True):
            self.assertEqual(judge.judge_answer('Run `docker --version`.', p, 'container-version')['status'], 'OK')
        p['document']['categories']['software.containers']['observations']['docker_client'].update(
            status='unavailable', value=None, reason='not_found_on_path')
        # Old sensitive-category data cannot override the granted baseline.
        p['document']['categories']['development.containers']['observations']['docker_client'] = dict(
            status='observed', value='99.0', reason=None)
        self.assertEqual(judge.judge_answer('Run `docker --version`.', p, 'container-version')['reason'], 'program_missing')

    def test_all_profiles_collect_and_grant_clients_but_deny_daemon(self):
        index = json.loads((HERE / 'profiles/index.json').read_text(encoding='utf-8'))
        for row in index:
            with self.subTest(profile=row['id']):
                p = tool.load_profile(row['id'])
                self.assertIn('software.containers', p['granted'])
                self.assertNotIn('development.containers', p['granted'])
                clients = p['document']['categories']['software.containers']
                self.assertEqual(set(clients['observations']), {'docker_client', 'podman_client'})
                self.assertEqual(clients['observations']['docker_client']['reason'], 'not_found_on_path')
                self.assertEqual(clients['observations']['podman_client']['status'],
                                 'observed' if row['id'] == 'fedora40' else 'unavailable')
                denied = p['document']['categories']['development.containers']
                self.assertEqual((denied['status'], denied['reason'], denied['observations']), ('denied', 'not_granted', {}))
                self.assertEqual(dg.problems(p['document']), [])

    def test_stand_in_and_catalog_separate_client_and_daemon_grants(self):
        with patch.object(dg, 'collect', side_effect=AssertionError('host collection')):
            doc = tool.environment_snapshot({'categories': ['software.containers', 'development.containers']}, 'fedora40')
        self.assertEqual(doc['categories']['software.containers']['observations']['podman_client']['value'], '5.2.0')
        self.assertEqual(doc['categories']['development.containers']['reason'], 'not_granted')
        self.assertEqual(doc['authorization']['effective'], ['software.containers'])
        self.assertEqual(dg.problems(doc), [])
        catalog = tool.environment_snapshot({'list': True}, 'fedora40')
        entries = {c['id']: c for c in catalog['categories']}
        self.assertEqual(entries['software.containers']['tier'], 'baseline')
        self.assertNotIn('docker_daemon', entries['software.containers']['observations'])
        self.assertEqual(entries['development.containers']['tier'], 'sensitive')

