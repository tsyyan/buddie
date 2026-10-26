"""An ordinary report, through verify/CLI/MCP and the existing receipts."""
import hashlib
import json

import pytest

from buddie import core, effects, github_report, mcp, receipts, remote
from buddie.verify import assessment, check_quotes, verify
from test_github_sources import BLOB, DIFF, HEAD, PR, ROOT, world


def pred(world, text, **kw):
    return verify(text, store=world[0], github=world[3], numbers='off', mandate=False, **kw)['predicate']


def test_inline_and_fenced_code_are_extracted_with_exact_lines():
    text = f'In [source]({BLOB}#L1), `if user.is_admin:`.\n\n[source]({BLOB}#L1-L2)\n\n```python\nif user.is_admin:\n    allow()\n```\n'
    claims = github_report.code_claims(text)
    assert [c['quote'] for c in claims] == ['if user.is_admin:', 'if user.is_admin:\n    allow()']
    assert [c['line'] for c in claims] == [1, 6]
    assert claims[1]['block'] is True


def test_unlinked_examples_and_embedded_code_links_are_not_citations():
    assert github_report.code_claims('Use `example()` in your code.\n\n```\nhttps://github.com/o/r/pull/7\n```') == []


def test_fence_can_use_following_standalone_citation():
    text = f'```python\nallow()\n```\n\n[source]({BLOB})'
    assert github_report.code_claims(text)[0]['urls'] == [BLOB]


def test_fence_does_not_inherit_a_distant_source():
    text = f'[source]({BLOB})\n\nUnrelated paragraph.\n\n```\nallow()\n```'
    assert github_report.code_claims(text) == []


def test_full_report_uses_existing_outcome_and_locations(world):
    p = pred(world, f'[source]({BLOB}#L1-L2)\n\n```python\nif user.is_admin:\n    allow()\n```')
    assert p['outcome'] == 'PASS'
    assert len(p['quotes']) == 1 and p['quotes'][0]['github']['revision'] == HEAD
    assert p['quotes'][0]['github']['start_line'] == 1
    assert p['summary']['quotes'] == {'FOUND': 1}


def test_wrong_indent_in_a_one_line_fence_fails(world):
    p = pred(world, f'[source]({BLOB})\n\n```python\n allow()\n```')
    assert p['outcome'] == 'FAIL'


def test_short_inline_code_is_not_dropped(world):
    p = pred(world, f'`allow()` ([source]({BLOB})).')
    assert p['outcome'] == 'PASS' and len(p['quotes']) == 1


def test_github_prose_citation_is_strict(world):
    assert pred(world, f'They wrote “A literal PR description.” ([source]({PR})).')['outcome'] == 'PASS'
    assert pred(world, f'They wrote “a literal pr description.” ([source]({PR})).')['outcome'] == 'FAIL'


def test_bare_pr_links_do_not_search_code(world):
    assert pred(world, f'`if user.is_admin:` ([PR]({PR})).')['outcome'] == 'FAIL'


def test_ambiguous_fence_is_a_gap(world):
    p = pred(world, f'[one]({BLOB}) [two]({PR})\n\n```\nallow()\n```')
    assert p['outcome'] == 'GAPS' and p['quotes'][0]['doubts'] == ['ambiguous_github_source']


def test_diff_fences_check_added_vs_deleted(world):
    assert pred(world, f'[diff]({DIFF}L2)\n\n```diff\n+old = True\n```')['outcome'] == 'FAIL'
    assert pred(world, f'[diff]({DIFF}L2)\n\n```diff\n-old = True\n```')['outcome'] == 'PASS'


def test_disabled_fetch_and_github_do_not_read_api(world):
    report = f'`if user.is_admin:` ([source]({BLOB})).'
    assert pred(world, report, fetch=False)['outcome'] == 'GAPS'
    assert world[2] == []
    p = verify(report, store=world[0], github=None, numbers='off')['predicate']
    assert p['outcome'] == 'GAPS' and world[2] == []
    assert pred(world, report)['outcome'] == 'PASS'
    world[2].clear()
    assert pred(world, report, fetch=False)['outcome'] == 'PASS' and world[2] == []


def test_callback_origin_does_not_become_observed(world):
    a = assessment(f'`allow()` ([source]({BLOB})).', store=world[0], github=world[3], numbers='off')
    f = a.findings[0]
    assert f.evidence[0].provenance is core.Provenance.CALLER_SUPPLIED
    assert f.evidence[0].digest and f.evidence[0].kind == 'github_api'
    rendered = receipts.render(a, 'v1')
    assert rendered['predicate']['verification']['outcome'] == 'PASS'
    assert receipts.problems(rendered) == []


def test_provenance_of_actual_get_and_offline_replay(world, monkeypatch):
    import io
    import urllib.request
    class Answer(io.BytesIO):
        def __init__(self, url, data):
            super().__init__(json.dumps(data).encode()); self.url = url
        def geturl(self): return self.url
    def urlopen(request, timeout):
        return Answer(request.full_url, world[1][request.full_url.removeprefix(effects.DEFAULT_API)])
    monkeypatch.setattr(urllib.request, 'urlopen', urlopen)
    text = f'`allow()` ([source]({BLOB})).'
    a = assessment(text, store=world[0], github=effects.github_get, numbers='off')
    assert a.findings[0].evidence[0].provenance is core.Provenance.COLLECTOR_OBSERVED
    replay = assessment(text, store=world[0], fetch=False, github=effects.github_get, numbers='off')
    assert replay.findings[0].evidence[0].provenance is core.Provenance.UNKNOWN


def test_remote_wrapper_accepts_only_public_citation_endpoints(world):
    world[1][ROOT] = {'private': False, 'full_name': 'o/r'}
    world[1][f'{ROOT}/pulls/7']['base']['repo'] = world[1][ROOT]
    get = remote.public_github(world[3])
    text = f'`allow()` ([source]({BLOB})).'
    p = verify(text, store=world[0], github=get, numbers='off')['predicate']
    assert p['outcome'] == 'PASS'
    world[2].clear()
    world[1][ROOT]['private'] = True
    p = verify(text, store=world[0], github=remote.public_github(world[3]), numbers='off')['predicate']
    assert p['outcome'] == 'GAPS' and world[2] == [ROOT]


def test_remote_diff_and_description_support(world):
    world[1][ROOT] = {'private': False, 'full_name': 'o/r'}
    world[1][f'{ROOT}/pulls/7']['base']['repo'] = world[1][ROOT]
    for text in [f'`new = False` ([source]({DIFF}R2)).', f'“A literal PR description.” ([source]({PR})).']:
        p = verify(text, store=world[0], github=remote.public_github(world[3]), numbers='off')['predicate']
        assert p['outcome'] == 'PASS'


def test_cli_and_stdio_mcp_use_the_adapter(world, tmp_path, monkeypatch, capsys):
    from buddie.cli import main
    monkeypatch.setattr(effects, 'github_get', world[3])
    monkeypatch.setenv('VERBATIM_STORE', str(world[0].root))
    text = f'`allow()` ([source]({BLOB})).'
    report = tmp_path / 'report.md'; report.write_text(text, encoding='utf-8')
    assert main(['verify', str(report), '--numbers', 'off']) == 0
    assert 'buddie PASS' in capsys.readouterr().out
    receipt, error, _ = mcp.verify_report({'text': text, 'numbers': 'off'})
    assert not error and receipt['predicate']['quotes'][0]['github']['revision'] == HEAD


def test_excluded_quote_count_includes_code(world):
    a = assessment(f'`allow()` ([source]({BLOB})).', store=world[0], github=world[3], quotes=False)
    r = receipts.render(a, 'v1')
    quote_excluded = [e for e in r['predicate']['scope']['excluded'] if e['check'] == 'quote']
    assert quote_excluded[0]['detected'] == 1


def test_short_github_quote_is_not_also_counted_as_skipped(world):
    p = pred(world, f'“allow()” ([source]({BLOB})).')
    assert p['outcome'] == 'PASS' and p['summary']['short_quotes_skipped'] == 0


def test_remote_rejects_encoded_traversal_before_any_request(world):
    get = remote.public_github(world[3])
    for path in [f'{ROOT}/contents/%2e%2e/secrets?ref={HEAD}',
                 f'{ROOT}/contents/a%3fref=main?ref={HEAD}', f'{ROOT}/contents/a.py?ref=main',
                 f'{ROOT}/git/trees/{HEAD}']:
        assert get(path) is None
    assert world[2] == []


def test_a_custom_store_cannot_forge_collected_github_evidence(world, monkeypatch):
    from buddie.verbatim.store import Store
    # A custom store can alter serialized evidence, so even an own GET cannot attest to what it saved.
    class CustomStore(Store):
        pass
    monkeypatch.setattr(effects, 'own_get', lambda get: True)
    a = assessment(f'`allow()` ([source]({BLOB})).', store=CustomStore(world[0].root),
                   github=world[3], numbers='off')
    assert a.findings[0].evidence[0].provenance is not core.Provenance.COLLECTOR_OBSERVED


def test_an_inline_url_is_not_its_own_source():
    assert github_report.code_claims(f'Use `{PR}` as an example URL.') == []


def test_quotation_marks_around_inline_code_do_not_add_an_empty_claim(world):
    p = pred(world, f'“`allow()`” ([source]({BLOB})).')
    assert p['outcome'] == 'PASS' and len(p['quotes']) == 1
    assert p['summary']['short_quotes_skipped'] == 0


def test_adjacent_preceding_inline_sources_are_ambiguous(world):
    p = pred(world, f'[one]({PR}) [two]({BLOB}) `allow()`')
    assert p['outcome'] == 'GAPS'
    assert p['quotes'][0]['doubts'] == ['ambiguous_github_source']


def test_lone_cr_in_a_fence_is_preserved_and_cannot_match_lf(world):
    import base64
    world[1][f'{ROOT}/contents/src/a.py?ref={HEAD}']['content'] = base64.b64encode(b'a\nb').decode()
    p = pred(world, f'[source]({BLOB})\n\n```python\na\rb\n```')
    assert p['outcome'] == 'FAIL'
    assert p['quotes'][0]['quote'] == 'a\rb'


def test_a_heading_without_blank_lines_ends_fence_source_scope():
    text = f'[source]({BLOB})\n# Unrelated\n```python\nallow()\n```'
    assert github_report.code_claims(text) == []


def test_remote_cannot_replay_a_locally_saved_private_source(world, monkeypatch):
    text = f'`allow()` ([source]({BLOB})).'
    assert pred(world, text)['outcome'] == 'PASS'
    monkeypatch.setenv('VERBATIM_STORE', str(world[0].root))
    monkeypatch.setattr(effects, 'github_get', world[3])
    receipt, error = remote.verify_report({'text': text, 'fetch': False, 'github': False, 'numbers': 'off'})
    assert not error and receipt['predicate']['outcome'] == 'GAPS'
    assert 'github' not in receipt['predicate']['quotes'][0]


def test_literal_prose_does_not_change_lone_cr(world):
    import base64
    world[1][f'{ROOT}/contents/src/a.py?ref={HEAD}']['content'] = base64.b64encode(b'alpha\nbeta').decode()
    p = pred(world, f'“alpha\rbeta” ([source]({BLOB})).')
    assert p['outcome'] == 'FAIL' and p['quotes'][0]['quote'] == 'alpha\rbeta'


@pytest.mark.parametrize('literal', ['allow() ', '\tallow()', 'allow()\t'])
def test_literal_prose_keeps_boundary_whitespace(world, literal):
    p = pred(world, f'“{literal}” ([source]({BLOB})).')
    assert p['outcome'] == 'FAIL'
    assert p['quotes'][0]['quote'] == literal


def test_private_bundle_is_not_a_generic_number_source(world, monkeypatch):
    secret = 'The secret budget has 12345 dollars allocated to submarine project. '
    world[1][f'{ROOT}/pulls/7']['body'] = secret + 'Ordinary context detail. ' * 30
    assert pred(world, f'“{secret.strip()}” ([source]({PR})).')['outcome'] == 'PASS'
    monkeypatch.setenv('VERBATIM_STORE', str(world[0].root))
    receipt, error = remote.verify_report({'text': f'{secret.rstrip().removesuffix(chr(46))} ([source]({PR})).',
                                         'fetch': False, 'github': False})
    assert not error and receipt['predicate']['outcome'] == 'GAPS'
    assert all(r['verdict'] == 'SOURCE_UNAVAILABLE' for r in receipt['predicate']['numbers'])
    assert '12345 dollars' not in json.dumps(receipt['predicate']['numbers'][0].get('match'))


@pytest.mark.parametrize('reference', ['url', 'digest', 'prefix'])
def test_remote_source_text_cannot_disclose_a_saved_bundle(world, monkeypatch, reference):
    p = pred(world, f'“A literal PR description.” ([source]({PR})).')
    sha = p['quotes'][0]['sha256']
    monkeypatch.setenv('VERBATIM_STORE', str(world[0].root))
    ref = {'url': PR, 'digest': sha, 'prefix': sha[:12]}[reference]
    result, error = remote.source_text({'ref': ref})
    assert error
    assert 'A literal PR description.' not in json.dumps(result)


@pytest.mark.parametrize('heading', [f'# `allow()` ([source]({BLOB}))',
                                    f'`allow()` ([source]({BLOB}))\n---'])
def test_heading_code_is_outside_citation_scope(heading):
    assert github_report.code_claims(heading) == []
