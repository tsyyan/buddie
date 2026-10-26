"""Synthetic adapter contract smoke; no network, model, or empirical efficiency result."""
import copy
import sys
import tempfile
from pathlib import Path

from instrumentation import ToolMeter

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
SHA = 'a' * 40
SLUG = 'example/research-fixture'
ROOT = '/repos/' + SLUG


def fixtures():
    return {
        ROOT + '/pulls/7': {'state': 'open', 'draft': False, 'merged': False, 'body': 'Fixture description.',
                           'head': {'sha': SHA}, 'base': {'sha': 'b' * 40}},
        ROOT + '/commits/' + SHA: {'sha': SHA, 'commit': {'message': 'Fix bounded fixture parser'}},
        ROOT + '/commits/' + SHA + '/check-runs?filter=latest&per_page=100&page=1': {
            'total_count': 1, 'check_runs': [{'name': 'test', 'head_sha': SHA, 'status': 'completed', 'conclusion': 'success'}]},
        ROOT + '/commits/' + SHA + '/status': {'sha': SHA, 'statuses': []},
    }


def smoke():
    from buddie.verify import verify
    data = fixtures()
    rows = []
    meter = ToolMeter(rows, allowed_tools={'agent_tool': {'github_pr', 'buddie_verify'}, 'github_http': {'get'}})
    def github(path):
        return meter.call('github_http', 'get', lambda request: copy.deepcopy(data.get(request['path'])), {'path': path})
    # Each adapter gets the same source map. This fixed script tests plumbing, not agent decisions.
    direct = meter.call('agent_tool', 'github_pr', lambda args: github(ROOT + '/pulls/7'), {'pr': 7})
    with tempfile.TemporaryDirectory() as store:
        receipts = {}
        for task,text in [
            ('PR_CI', f'⚓ `pr:{SLUG}#7=open@{SHA}` ⚓ `ci:{SLUG}@{SHA}=success`'),
            ('FALSE_MERGE', f'⚓ `pr:{SLUG}#7=merged`')]:
            receipts[task] = meter.call('agent_tool', 'buddie_verify',
                lambda args: verify(args['text'], store=store, fetch=False, github=github,
                                    mandate=False, quotes=False, numbers='off'), {'text': text})
    return {'mode': 'synthetic_adapter_smoke_not_model_trial', 'direct_pr_state': direct['state'],
            'receipt_outcomes': {k:v['predicate']['outcome'] for k,v in receipts.items()},
            'metrics': rows, 'usage': None, 'cost_usd': None}
