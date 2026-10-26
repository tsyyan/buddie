"""Analyze metric-only traces after separate execution approval. No inference from bytes to tokens."""
import statistics
import math
import re

TOKEN_KEYS = ('input_tokens', 'cache_read_tokens', 'cache_creation_tokens', 'output_tokens')
CASES = {'PR_CI', 'COMMIT', 'DIFF', 'FALSE_MERGE', 'RELEASE'}


def identity(r):
    for field in ('manifest_sha', 'fixture_sha', 'sampling_sha'):
        if not isinstance(r.get(field), str) or not re.fullmatch('[0-9a-f]{64}', r[field]):
            raise ValueError('frozen trace identity required')
    if r.get('case') not in CASES or r.get('arm') not in ('A_direct', 'B_core', 'B_citations'):
        raise ValueError('unknown analysis stratum')
    if type(r.get('correct_completed')) is not bool or type(r.get('hooks')) is not bool:
        raise ValueError('adjudication and hook condition required')
    if type(r.get('correction_turns')) is not int or not 0 <= r['correction_turns'] <= 10000:
        raise ValueError('invalid correction count')
    counters = r.get('usage') or {}
    if not isinstance(counters, dict):
        raise ValueError('invalid usage shape')
    numeric = [r.get('wall_clock_s'), *(counters.get(k) for k in (*TOKEN_KEYS, 'cost_usd'))]
    for event in r['tools']:
        if event['boundary'] not in ('agent_tool', 'github_http', 'hook'):
            raise ValueError('invalid tool boundary')
        if type(event.get('request_bytes')) is not int or event.get('duration_s') is None:
            raise ValueError('missing measured tool metric')
        numeric.extend(event.get(k) for k in ('duration_s', 'request_bytes', 'response_bytes'))
    for value in numeric:
        if value is not None and (type(value) not in (int, float) or not 0 <= value <= 2**63-1 or not math.isfinite(value)):
            raise ValueError('invalid trace metric')
    return (r['manifest_sha'], r['fixture_sha'], r['sampling_sha'], r['variant'],
            r['model'], r['runtime'], r['buddie_sha'], r['cache'], r['hooks'])


def summarize(runs):
    """Keep incompatible versions/caches/hooks apart. Missing resources remain missing.

    Each trace supplies blinded/adjudicated correct_completed, not a model's self-label.
    Wall time is actual end-to-end time; tool rows have the ToolMeter schema.
    """
    groups = {}
    for r in runs:
        key = (r['arm'], *identity(r))
        groups.setdefault(key, []).append(r)
    result = []
    for key, rows in groups.items():
        correct = sum(r['correct_completed'] for r in rows)
        costs = [(r.get('usage') or {}).get('cost_usd') for r in rows]
        cost_complete = all(v is not None for v in costs)
        # Failed/incorrect tasks remain in the numerator of spend per correct completion.
        total_cost = sum(costs) if cost_complete else None
        walls = [r['wall_clock_s'] for r in rows if r.get('wall_clock_s') is not None]
        tokens = {k: sum(r['usage'][k] for r in rows) if all((r.get('usage') or {}).get(k) is not None for r in rows) else None
                  for k in TOKEN_KEYS}
        boundaries = {}
        for boundary in ('agent_tool', 'github_http', 'hook'):
            events = [e for r in rows for e in r['tools'] if e['boundary'] == boundary]
            boundaries[boundary] = {'calls': len(events), 'request_bytes': sum(e['request_bytes'] for e in events),
                'response_bytes': sum(e['response_bytes'] for e in events) if all(e['response_bytes'] is not None for e in events) else None}
        result.append({'stratum': key, 'n': len(rows), 'correct_completed': correct,
                       'accuracy': correct / len(rows), 'total_cost_usd': total_cost,
                       'cost_per_correct_completed': total_cost / correct if total_cost is not None and correct else None,
                       'wall_clock_median_s': statistics.median(walls) if walls else None,
                       'wall_clock_n': len(walls), 'tokens': tokens, 'boundaries': boundaries,
                       'correction_turns': sum(r['correction_turns'] for r in rows)})
    return result


def paired_differences(runs, b_arm='B_core'):
    pairs = {}
    for r in runs:
        if r['arm'] not in ('A_direct', b_arm):
            continue
        key = (r['case'], r['repetition'], *identity(r))
        pair = pairs.setdefault(key, {})
        if r['arm'] in pair:
            raise ValueError('duplicate arm in paired task')
        pair[r['arm']] = r
    out = []
    for key,pair in pairs.items():
        if set(pair) != {'A_direct', b_arm}:
            out.append({'pair': key, 'complete': False})
            continue
        a,b = pair['A_direct'], pair[b_arm]
        def delta(x,y):
            return y - x if x is not None and y is not None else None
        out.append({'pair': key, 'complete': True, 'both_correct': a['correct_completed'] and b['correct_completed'],
                    'wall_clock_B_minus_A_s': delta(a.get('wall_clock_s'), b.get('wall_clock_s')),
                    'cost_B_minus_A_usd': delta((a.get('usage') or {}).get('cost_usd'), (b.get('usage') or {}).get('cost_usd')),
                    'tokens_B_minus_A': {k: delta((a.get('usage') or {}).get(k), (b.get('usage') or {}).get(k)) for k in TOKEN_KEYS}})
    return out
