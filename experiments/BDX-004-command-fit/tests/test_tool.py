"""The stand-in must neither over-disclose a fixture nor inspect its host."""
import copy
import json
import sys
import unittest
from unittest.mock import patch
from test_profiles import HERE, dg

sys.path.insert(0, str(HERE))
import tool
from buddie import mcp, probes


class Snapshot(unittest.TestCase):
    def test_denied_has_no_observations_and_valid_envelope(self):
        p = tool.load_profile('macos-arm')
        p['granted'] = ['system.os']
        before = copy.deepcopy(p)
        doc = tool.environment_snapshot({'categories': ['system.os', 'hardware.gpu'], 'task': 'install'}, p)
        self.assertEqual(set(doc['categories']), {'system.os', 'hardware.gpu'})
        self.assertEqual(doc['categories']['hardware.gpu'], dict(status='denied', reason='not_granted',
                         tier='baseline', methods=[], observations={}))
        self.assertEqual(doc['authorization']['effective'], ['system.os'])
        self.assertEqual(doc['supplied'], {'task': 'install'})
        self.assertEqual(dg.problems(doc), [])
        self.assertEqual(p, before)

    def test_validation_and_no_host_collection(self):
        with patch.object(dg, 'collect', side_effect=AssertionError('host probe')):
            for args in ({'categories': []}, {'categories': 'system.os'}, {'categories': ['system.os'], 'task': 1},
                         {'categories': ['system.os'], 'path': ''}, {'consent': True}, {'command': 'whoami'}):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    tool.environment_snapshot(args, 'macos-arm')
            doc = tool.environment_snapshot({'categories': ['system.os', 'network.ports', 'other.fake', 'bad/id']}, 'macos-arm')
        self.assertEqual(doc['categories']['network.ports']['status'], 'unsupported')
        self.assertEqual(doc['request']['rejected'][0]['reason'], 'unknown_category')
        self.assertEqual(doc['request']['rejected'][1]['id'], None)
        self.assertEqual(dg.problems(doc), [])

    def test_tools_are_filtered_and_bad_names_reported(self):
        doc = tool.environment_snapshot({'categories': ['software.tools'], 'tools': ['git', 'sudo', 'x/y']}, 'fedora40')
        obs = doc['categories']['software.tools']['observations']
        self.assertEqual(set(obs), {'git', 'sudo'})
        self.assertEqual(obs['sudo']['reason'], 'not_in_catalog')
        self.assertEqual(doc['request']['tools'], ['git'])
        empty = tool.environment_snapshot({'categories': ['software.tools']}, 'fedora40')
        self.assertEqual(empty['categories']['software.tools']['reason'], 'no_tools_given')
        self.assertEqual(dg.problems(doc), [])

    def test_path_categories_do_not_read_real_directories(self):
        p = tool.load_profile('fedora40')
        p['granted'].append('development.project')
        for path, reason in [(None, 'no_path_given'), (str(HERE), 'path_not_granted')]:
            args = {'categories': ['development.project']}
            if path:
                args['path'] = path
            doc = tool.environment_snapshot(args, p)
            self.assertEqual(doc['categories']['development.project']['reason'], reason)
            self.assertEqual(dg.problems(doc), [])

    def test_catalog_matches_real_tool_with_profile_grants(self):
        p = tool.load_profile('fedora40')
        with patch.object(dg, 'load_grants', return_value=dg.Grants('active', frozenset(p['granted']))), \
             patch.object(probes, 'platform_key', return_value='linux'):
            real = dg.catalog()
        self.assertEqual(tool.environment_snapshot({'list': True}, p), real)

    def test_chat_schema_is_exact_mcp_schema(self):
        source = next(t for t in mcp.TOOLS if t['name'] == 'environment_snapshot')
        self.assertEqual(tool.TOOL['function'], dict(name=source['name'], description=source['description'],
                                                   parameters=source['inputSchema']))
