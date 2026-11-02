"""Client-only baseline facts remain distinct from the ungranted daemon."""
import json
import unittest
from unittest.mock import patch
from test_judge import HERE, judge, grade
from test_profiles import dg
import tool
import summarize


def with_docker():
    p = tool.load_profile('ubuntu2404-nvidia')
    clients = p['document']['categories']['software.containers']
    clients.update(status='partial', reason=None)
    clients['observations']['docker_client'].update(status='observed', value='27.3.1', reason=None, basis='path_program')
    next(m for m in clients['methods'] if m['method'] == 'docker_client')['outcome'] = 'ok'
    assert dg.problems(p['document']) == []
    return p


class ContainerBaseline(unittest.TestCase):
    def test_container_package_aliases_preserve_pending_installation(self):
        for package in ('docker.io', 'docker-ce-cli'):
            with self.subTest(package=package), patch.object(judge, 'syntax', return_value=True):
                answer = '```bash\nsudo apt install ' + package + '\ndocker --version\ndocker ps\n```'
                rows = judge.judge_answer(answer, 'ubuntu2404-nvidia', 'container-run')['commands']
                self.assertEqual([r['status'] for r in rows], ['FITS', 'UNKNOWN', 'UNKNOWN'])
                self.assertIsNone(rows[1]['reason'])
                self.assertIn('daemon not granted', rows[2]['detail'])

    def test_recorded_client_versions_follow_the_regenerated_inventory(self):
        cases = json.loads((HERE / 'tests/container_answers.json').read_text(encoding='utf-8'))
        self.assertEqual(len(cases), 16)
        for case in cases:
            with self.subTest(case=case['id']):
                if case['expected_status'] == 'FITS' and judge.syntax(case['parser'], 'echo ok') is None:
                    self.skipTest('positive client verdict needs the profile parser')
                row = judge.judge_answer(case['answer'], case['profile'], case['task'])['commands'][0]
                self.assertEqual((row['status'], row['reason']), (case['expected_status'], case['expected_reason']))

    def test_tasks_request_baseline_clients_and_keep_daemon_sensitive(self):
        tasks = json.loads((HERE / 'tasks/tasks.json').read_text(encoding='utf-8'))
        by_id = {t['id']: t for t in tasks}
        self.assertIn('software.containers', by_id['container-version']['categories'])
        self.assertNotIn('development.containers', by_id['container-version']['categories'])
        self.assertTrue({'software.containers', 'development.containers'} <= set(by_id['container-run']['categories']))

    def test_daemon_queries_are_data_gaps_in_every_task(self):
        p = with_docker()
        for task in ('container-version', 'container-run', 'list-files'):
            for text in ('docker ps', 'docker run --rm alpine echo hello', 'docker run --version', 'docker --context default ps'):
                with self.subTest(task=task, text=text), patch.object(judge, 'syntax', return_value=True):
                    row = judge.judge_answer('Run `' + text + '`.', p, task)['commands'][0]
                    self.assertEqual(row['status'], 'UNKNOWN')
                    self.assertIn('daemon not granted', row['detail'])
                    self.assertEqual(summarize.unknown_cause(row), 'data')

    def test_global_flags_and_groups_cannot_bypass_daemon_requirement(self):
        p = with_docker()
        for text in ('docker --log-level debug ps', 'docker -l debug run alpine echo hello',
                     'docker builder prune', 'docker checkpoint ls', 'docker future-group inspect'):
            with self.subTest(text=text), patch.object(judge, 'syntax', return_value=True):
                row = judge.judge_answer('Run `' + text + '`.', p, 'container-version')['commands'][0]
                self.assertEqual(row['status'], 'UNKNOWN')

    def test_subcommand_help_is_client_only_but_container_argv_is_not(self):
        p = with_docker()
        with patch.object(judge, 'syntax', return_value=True):
            self.assertEqual(judge.judge_answer('Run `docker run --help`.', p, 'container-version')['status'], 'OK')
            row = judge.judge_answer('Run `docker run alpine echo --help`.', p, 'container-version')['commands'][0]
            self.assertEqual(row['status'], 'UNKNOWN')

    def test_granted_default_daemon_does_not_prove_another_target(self):
        p = with_docker()
        p['granted'].append('development.containers')
        p['document']['categories']['development.containers'] = dict(status='collected', observations={
            'docker_daemon': dict(status='observed', value=dict(reachable=True, version='27.3.1'))})
        with patch.object(judge, 'syntax', return_value=True):
            for target in ('--context unobserved-remote', '--host tcp://example.org:2375'):
                row = judge.judge_answer('Run `docker ' + target + ' ps`.', p, 'container-version')['commands'][0]
                self.assertEqual(row['status'], 'UNKNOWN')
                self.assertEqual(summarize.unknown_cause(row), 'data')

    def test_client_version_never_requires_a_daemon(self):
        p = with_docker()
        with patch.object(judge, 'syntax', return_value=True):
            self.assertEqual(judge.judge_answer('Run `docker --version`.', p, 'container-run')['status'], 'OK')
            self.assertEqual(judge.judge_answer('Run `docker context ls`.', p, 'container-version')['status'], 'OK')
            self.assertEqual(grade('fedora40', 'container-run', 'podman run --rm alpine echo hello')['status'], 'OK')

    def test_synthetic_daemon_grant_can_establish_reachability(self):
        p = with_docker()
        p['granted'].append('development.containers')
        p['document']['categories']['development.containers'] = dict(status='collected', observations={
            'docker_daemon': dict(status='observed', value=dict(reachable=True, version='27.3.1'))})
        with patch.object(judge, 'syntax', return_value=True):
            self.assertEqual(judge.judge_answer('Run `docker ps`.', p, 'container-version')['status'], 'OK')

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

