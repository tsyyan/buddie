import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import harness
import instrumentation as ins


class PreparationTests(unittest.TestCase):
    def test_manifest_freezes_all_cases_and_inputs_without_expected_answers(self):
        manifest = harness.prepare()
        self.assertEqual(len(manifest['tasks']), 10)
        self.assertEqual(len({t['case'] for t in manifest['tasks']}), 5)
        self.assertFalse(manifest['paid_execution_enabled'])
        self.assertNotIn('expected', json.dumps(manifest['tasks']))
        self.assertEqual(set(manifest['sha256']), {'cases.json', 'evaluation/expected.json'})

    def test_paid_run_always_refuses(self):
        self.assertEqual(harness.main(['run']), 2)

    def test_prepare_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'plan.json'
            self.assertEqual(harness.main(['prepare', '--out', str(out)]), 0)
            self.assertEqual(harness.main(['prepare', '--out', str(out)]), 2)

    def test_tool_wrapper_counts_bytes_but_never_persists_payload_or_exception(self):
        rows = []
        clock = iter([10.0, 10.25, 20.0, 20.5]).__next__
        wrapper = ins.ToolMeter(rows, clock=clock, allowed_tools={'agent_tool': {'github_read'}, 'github_http': {'get'}})
        request = {'secret': 'synthetic-secret', 'path': 'C:/Users/synthetic/private'}
        self.assertEqual(wrapper.call('agent_tool', 'github_read', lambda x: {'value': 3}, request), {'value': 3})
        def fail(x):
            raise RuntimeError('synthetic-secret')
        with self.assertRaises(RuntimeError):
            wrapper.call('github_http', 'get', fail, request)
        stored = json.dumps(rows)
        self.assertNotIn('synthetic-secret', stored)
        self.assertNotIn('C:/Users', stored)
        self.assertEqual(rows[0]['request_bytes'], len(ins.encode(request)))
        self.assertEqual(rows[0]['duration_s'], .25)
        self.assertFalse(rows[1]['ok'])
        self.assertIsNone(rows[1]['response_bytes'])

    def test_runtime_usage_requires_actual_counters_not_byte_estimates(self):
        raw = {'type': 'result', 'usage': {'input_tokens': 2, 'cache_read_input_tokens': 8,
               'cache_creation_input_tokens': 3, 'output_tokens': 4}, 'total_cost_usd': .012}
        got = ins.usage(raw)
        self.assertEqual(got['input_tokens'], 2)
        self.assertEqual(got['cache_read_tokens'], 8)
        self.assertEqual(got['cost_usd'], .012)
        for damaged in [{}, {'usage': {'bytes': 200}}, {**raw, 'total_cost_usd': None}]:
            with self.assertRaises(ValueError):
                ins.usage(damaged)
        for damaged in [[], None, {**raw, 'total_cost_usd': 10**1000}]:
            with self.assertRaises(ValueError):
                ins.usage(damaged)
        raw['usage']['input_tokens'] = True
        with self.assertRaises(ValueError):
            ins.usage(raw)

    def test_unknown_tool_name_is_never_recorded(self):
        rows = []
        meter = ins.ToolMeter(rows, allowed_tools={'agent_tool': {'github_read'}})
        with self.assertRaises(ValueError):
            meter.call('agent_tool', 'synthetic_secret_123', lambda x: {}, {})
        self.assertEqual(rows, [])

    def test_import_runtime_is_bounded_safe_and_bound_to_a_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            manifest = {'schema': 'bdx-002/frozen-run-v1', 'runtime': 'reviewed-cli', 'model': 'frozen-model',
                        'sampling_sha': 'a'*64, 'tool_schemas_sha': 'b'*64, 'approval_ref': 'separate-owner-decision'}
            (p/'manifest.json').write_text(json.dumps(manifest))
            raw = {'type': 'result', 'usage': {'input_tokens': 1, 'cache_read_input_tokens': 2,
                   'cache_creation_input_tokens': 3, 'output_tokens': 4}, 'total_cost_usd': .01,
                   'result': 'synthetic-secret'}
            (p/'result.json').write_text(json.dumps(raw))
            args = ['import-runtime', '--result', str(p/'result.json'), '--manifest', str(p/'manifest.json'),
                    '--out', str(p/'out.json')]
            self.assertEqual(harness.main(args), 0)
            stored = (p/'out.json').read_text()
            self.assertNotIn('synthetic-secret', stored)
            self.assertIn('result_sha256', stored)
            (p/'out.json').unlink()
            (p/'result.json').write_text('[]')
            self.assertEqual(harness.main(args), 2)
            self.assertFalse((p/'out.json').exists())

    def test_isolation_rejects_host_context_even_when_tools_are_correct(self):
        envelope = {'bare': True, 'host_context_injected': False, 'plugins': [], 'hooks': False,
                    'tools': ['github_read'], 'context_reviewed': True, 'secrets_absent': True}
        ins.isolation(envelope, ['github_read'], hooks=False)
        for key,value in [('host_context_injected', True), ('plugins', ['unknown']),
                          ('context_reviewed', False), ('secrets_absent', False), ('tools', [])]:
            with self.assertRaises(ValueError):
                ins.isolation({**envelope, key: value}, ['github_read'], hooks=False)
