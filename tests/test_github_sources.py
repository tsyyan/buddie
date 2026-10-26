"""Literal GitHub sources: synthetic API replies, no network."""
import base64
import copy
import hashlib

import pytest

from buddie import github_sources as gh
from buddie.verbatim.store import Store

BASE, HEAD, MERGE = 'a' * 40, 'b' * 40, 'c' * 40
ROOT = '/repos/o/r'
BLOB = f'https://github.com/o/r/blob/{HEAD}/src/a.py'
PR = 'https://github.com/o/r/pull/7'
FILE_HASH = hashlib.sha256(b'src/a.py').hexdigest()
DIFF = f'{PR}/files#diff-{FILE_HASH}'
PATCH = '@@ -1,3 +1,3 @@\n before\n-old = True\n+new = False\n after'


@pytest.fixture
def world(tmp_path):
    answers = {
        f'{ROOT}/contents/src/a.py?ref={HEAD}': {
            'type': 'file', 'path': 'src/a.py', 'encoding': 'base64',
            'content': base64.b64encode(b'if user.is_admin:\n    allow()\n').decode()},
        f'{ROOT}/pulls/7': {'body': 'A literal PR description.', 'base': {'sha': BASE}, 'head': {'sha': HEAD}},
        f'{ROOT}/compare/{BASE}...{HEAD}': {'merge_base_commit': {'sha': MERGE},
            'files': [{'filename': 'src/a.py', 'patch': PATCH, 'additions': 1, 'deletions': 1}]},
    }
    calls = []
    def get(path):
        calls.append(path)
        return copy.deepcopy(answers.get(path))
    return Store(tmp_path / 'store'), answers, calls, get


def check(world, url, quote, **kw):
    store, _, _, get = world
    return gh.Resolver(store, get, True).check({'quote': quote, 'urls': [url], **kw})


def test_pinned_file_preserves_location_and_snapshot(world):
    r = check(world, BLOB + '#L1-L2', 'if user.is_admin:\n    allow()')
    assert r['verdict'] == 'FOUND'
    assert r['github']['revision'] == HEAD
    assert r['github']['path'] == 'src/a.py'
    assert r['github']['start_line'] == 1 and r['github']['end_line'] == 2
    assert r['sha256'] and world[0].read(r['sha256'])


@pytest.mark.parametrize('quote', ['if User.is_admin:', 'if user.is_admin;', 'if user.is_admin:\n allow()',
                                  'if user.is_admin:\n\tallow()'])
def test_code_never_uses_prose_normalization(world, quote):
    assert check(world, BLOB, quote)['verdict'] == 'NOT_FOUND'


def test_crlf_is_the_only_text_normalization(world):
    r = check(world, BLOB, 'if user.is_admin:\r\n    allow()')
    assert r['verdict'] == 'FOUND' and r['github']['normalization'] == 'crlf_to_lf'


def test_fragment_restricts_file_search(world):
    assert check(world, BLOB + '#L2', 'if user.is_admin:')['verdict'] == 'NOT_FOUND'


@pytest.mark.parametrize('suffix', ['#L0', '#L2-L1', '#L1-L999', '#other'])
def test_bad_or_out_of_bounds_range_is_a_gap(world, suffix):
    assert check(world, BLOB + suffix, 'if user.is_admin:')['verdict'] == 'SOURCE_UNAVAILABLE'


def test_mutable_refs_and_unsafe_urls_are_not_fetched(world):
    for url in [BLOB.replace(HEAD, 'main'), BLOB.replace('src/a.py', '../secret'),
                BLOB.replace('github.com', 'github.com.evil'), BLOB.replace('https:', 'http:')]:
        assert check(world, url, 'if user.is_admin:')['verdict'] == 'SOURCE_UNAVAILABLE'
    assert world[2] == []


def test_pr_description_is_its_own_observation(world):
    r = check(world, PR, 'A literal PR description.')
    assert r['verdict'] == 'FOUND' and r['github']['kind'] == 'pr_body'
    world[1][f'{ROOT}/pulls/7']['body'] = 'Edited description.'
    later = check(world, PR, 'A literal PR description.')
    assert later['verdict'] == 'NOT_FOUND' and later['sha256'] != r['sha256']


def test_diff_is_pinned_to_pair_and_merge_base(world):
    r = check(world, DIFF + 'R2', 'new = False')
    assert r['verdict'] == 'FOUND'
    assert r['github']['base'] == BASE and r['github']['head'] == HEAD
    assert r['github']['merge_base'] == MERGE
    assert r['github']['kinds'] == ['added']
    assert check(world, DIFF + 'R2', 'old = True')['verdict'] == 'NOT_FOUND'
    assert check(world, DIFF + 'L2', 'old = True')['github']['kinds'] == ['deleted']


def test_explicit_diff_signs_must_match_kind(world):
    assert check(world, DIFF + 'L2', '+old = True', diff=True)['verdict'] == 'NOT_FOUND'
    assert check(world, DIFF + 'L2', '-old = True', diff=True)['verdict'] == 'FOUND'
    assert check(world, DIFF + 'R1-R2', ' before\n+new = False', diff=True)['verdict'] == 'FOUND'


def test_cross_hunk_quotes_do_not_match(world):
    f = world[1][f'{ROOT}/compare/{BASE}...{HEAD}']['files'][0]
    f.update(patch='@@ -1 +1 @@\n-old\n+first\n@@ -8 +8 @@\n-last\n+second', additions=2, deletions=2)
    assert check(world, DIFF + 'R1-R8', 'first\nsecond')['verdict'] == 'SOURCE_UNAVAILABLE'


@pytest.mark.parametrize('damage', ['missing', 'truncated', 'totals', 'malformed', 'binary', 'no_file'])
def test_incomplete_diff_is_never_a_negative_assertion(world, damage):
    response = world[1][f'{ROOT}/compare/{BASE}...{HEAD}']
    f = response['files'][0]
    if damage == 'missing': del f['patch']
    if damage == 'truncated': f['patch'] = PATCH.rsplit('\n', 1)[0]
    if damage == 'totals': f['additions'] = 99
    if damage == 'malformed': f['patch'] = 'garbage'
    if damage == 'binary': f['patch'] = None
    if damage == 'no_file': response['files'] = []
    assert check(world, DIFF + 'R2', 'anything')['verdict'] == 'SOURCE_UNAVAILABLE'


@pytest.mark.parametrize('body', [None, [], {'type': 'dir'}, {'type': 'file', 'encoding': 'base64', 'content': '%%%'}])
def test_unusable_file_response_flags(world, body):
    world[1][f'{ROOT}/contents/src/a.py?ref={HEAD}'] = body
    assert check(world, BLOB, 'something')['verdict'] == 'SOURCE_UNAVAILABLE'


def test_offline_replay_is_exactly_scoped_and_hash_checked(world):
    result = check(world, DIFF + 'R2', 'new = False')
    offline = gh.Resolver(world[0], None, False)
    assert offline.check({'quote': 'new = False', 'urls': [DIFF + 'R2']})['verdict'] == 'FOUND'
    assert offline.check({'quote': 'new = False', 'urls': [DIFF + 'L2']})['verdict'] == 'SOURCE_UNAVAILABLE'
    (world[0].snapshots / result['sha256']).write_bytes(b'forged')
    assert offline.check({'quote': 'new = False', 'urls': [DIFF + 'R2']})['verdict'] == 'SOURCE_UNAVAILABLE'


def test_multiple_sources_are_ambiguous_not_first_success(world):
    r = gh.Resolver(world[0], world[3], True).check({'quote': 'new = False', 'urls': [BLOB, DIFF + 'R2']})
    assert r['verdict'] == 'UNCERTAIN' and world[2] == []


def test_unknown_diff_location_is_not_search_all_files(world):
    for url in [PR + '/files', DIFF, DIFF + 'R2-L3', PR + '#issuecomment-123']:
        assert check(world, url, 'new = False')['verdict'] == 'SOURCE_UNAVAILABLE'


def test_partially_unobserved_diff_range_is_a_gap(world):
    assert check(world, DIFF + 'R1-R999', 'missing')['verdict'] == 'SOURCE_UNAVAILABLE'


def test_missing_description_field_is_not_an_empty_description(world):
    del world[1][f'{ROOT}/pulls/7']['body']
    assert check(world, PR, 'missing')['verdict'] == 'SOURCE_UNAVAILABLE'


def test_api_error_is_a_gap_without_an_html_fallback(world):
    def down(path):
        from buddie.effects import GitHubUnavailable
        raise GitHubUnavailable('rate limited')
    r = gh.Resolver(world[0], down, True).check({'quote': 'anything', 'urls': [BLOB]})
    assert r['verdict'] == 'SOURCE_UNAVAILABLE' and 'rate limited' in r['error']
