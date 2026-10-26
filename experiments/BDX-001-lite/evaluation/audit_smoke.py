"""Audit stored evidence only. No backend invocation, network or token estimation.

Run from repository root: python experiments/BDX-001-lite/evaluation/audit_smoke.py
Historical fixture hashes used raw OS line endings; report LF/CRLF reconstruction explicitly.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'harness'), str(ROOT / 'evaluation')]
from bdx import cli, fixtures
import context_cost
import evaluate


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def audit():
    batch = ROOT / 'results/smoke'
    plan = load(batch / 'plan.json')
    labels = load(batch / 'manual_labels.json')['runs']
    saved = {r['run_id']: r for r in load(batch / 'evaluations.json')['rows']}
    expected = {r['run_id'] for r in plan['runs']}
    rows = []
    for path in sorted((batch / 'runs').glob('*.json')):
        r = load(path)
        events = [json.loads(line) for line in (batch / 'events' / (path.stem + '.jsonl')).read_text(encoding='utf-8').splitlines()]
        result = [e for e in events if e.get('type') == 'result'][-1]
        calls = [c for c in r['tool_calls'] if c.get('counted')]
        hashes = {}
        for name, digest in r['fixtures']['sha256'].items():
            raw = (fixtures.RAW / name).read_bytes()
            lf = raw.replace(b'\r\n', b'\n')
            variants = {'exact_worktree': raw, 'LF': lf, 'CRLF': lf.replace(b'\n', b'\r\n')}
            hashes[name] = next((k for k,v in variants.items() if hashlib.sha256(v).hexdigest() == digest), None)
        verdict = evaluate.judge(r['scenario'], r['final_text'])
        checks = {
            'planned': r['run_id'] in expected,
            'status': r['status'] == 'ok' and r['exit_code'] == 0,
            'usage_equals_runtime_result': r['usage'] == result['usage'],
            'cost_equals_runtime_result': r['cost_usd'] == result['total_cost_usd'],
            'answer_equals_runtime_result': r['final_text'] == result['result'],
            'call_metrics': len(calls) == r['diagnostic_iterations'] and
                sum(c['response_bytes'] for c in calls) == r['response_bytes_total'],
            'fixture_hash_reconstructable': all(hashes.values()),
            'auto_verdict_reproduces': verdict == saved[r['run_id']]['verdict'],
            'auto_label_reproduces': evaluate.label(verdict, r['condition'], r['status']) == saved[r['run_id']]['label'],
            'confound_recorded': r['isolation']['ok'] and r['isolation']['host_context_injected'],
        }
        rows.append({'run_id': r['run_id'], 'checks': checks, 'fixture_hash_match': hashes,
                     'usage': r['usage'], 'cost_usd': r['cost_usd'], 'duration_s': r['duration_s'],
                     'calls': len(calls), 'response_bytes': r['response_bytes_total'],
                     'auto_label': saved[r['run_id']]['label'], 'manual': labels[r['run_id']]})
    complete = {r['run_id'] for r in rows} == expected == set(labels) == set(saved)
    static_equal = context_cost.measure() == load(ROOT / 'results/static/context_cost.json')
    manual = {}
    for condition in 'ABC':
        subset = [r for r in rows if f'-{condition}-' in r['run_id']]
        manual[condition] = {'n': len(subset), 'unsupported': sum(r['manual']['unsupported'] for r in subset),
                             'applicable': sum(r['manual']['label'] == 'APPLICABLE' for r in subset)}
    return {'schema': 'bdx-001-lite/audit-v1', 'n': len(rows), 'complete': complete,
            'all_checks': complete and static_equal and all(all(r['checks'].values()) for r in rows),
            'static_bytes_reproduce': static_equal, 'manual': manual,
            'cost_usd': sum(r['cost_usd'] for r in rows), 'rows': rows,
            'limits': 'Runtime result counters, not independent provider billing; wall time is recorded historical time; all runs confounded; raw fixture hashes need declared EOL reconstruction.'}


if __name__ == '__main__':
    report = audit()
    print(json.dumps(report, ensure_ascii=False, indent=1))
    raise SystemExit(0 if report['all_checks'] else 1)
