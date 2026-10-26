import importlib.util
import json

from bdx import ROOT, cli


def audit_module():
    spec = importlib.util.spec_from_file_location('audit_smoke', ROOT / 'evaluation/audit_smoke.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_stored_smoke_is_reconciled_without_any_model_call():
    report = audit_module().audit()
    assert report['n'] == 9
    assert report['all_checks']
    assert report['manual']['A']['unsupported'] == 3
    assert report['manual']['B']['unsupported'] == 0
    assert report['manual']['C']['unsupported'] == 1
    assert report['manual']['B']['applicable'] == 3
    assert abs(report['cost_usd'] - 0.2372618) < 1e-9

