"""Strict GitHub citation sources. The bundle hash identifies canonical JSON API evidence, not HTTP bytes.

No source text is executed. Unsupported/partial sources are gaps; literal mismatches require complete evidence.
"""
from __future__ import annotations

import base64
import binascii
import contextvars
import hashlib
import json
import re
from urllib.parse import quote, unquote, urlsplit

from buddie import effects
from buddie.verbatim.store import canonical_url, check_time

SHA = r'[0-9a-f]{40}'
NAME = r'[A-Za-z0-9_.-]{1,100}'
REPO = re.compile(rf'^/({NAME})/({NAME})/(.+)$')
FILE = re.compile(rf'blob/({SHA})/(.+)')
PR = re.compile(r'pull/([1-9][0-9]{0,8})(/files)?')
RANGE = re.compile(r'L([1-9][0-9]*)(?:-L([1-9][0-9]*))?')
DIFF = re.compile(r'diff-([0-9a-f]{64})([LR])([1-9][0-9]*)(?:-([LR])([1-9][0-9]*))?')
HUNK = re.compile(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)')
SCHEMA = 'buddie-github-source-v1'
MAX_LINES = 200_000
# A public server cannot trust an arbitrary saved bundle to have passed its public-repository check.
SAVED_SOURCES = contextvars.ContextVar('github_saved_sources', default=True)


class Unavailable(ValueError):
    pass


def is_github(url: str) -> bool:
    try:
        return (urlsplit(url).hostname or '').lower() == 'github.com'
    except ValueError:
        return False


def _path(path: str) -> str:
    path = unquote(path)
    if any(p in ('', '.', '..') for p in path.split('/')) or any(c in path for c in '\\?#\x00\r\n'):
        raise Unavailable('unsupported repository path')
    return path


def _identity(url: str) -> dict:
    u = urlsplit(url)
    if u.scheme != 'https' or u.netloc.lower() != 'github.com' or u.query:
        raise Unavailable('only canonical https://github.com source URLs are supported')
    m = REPO.fullmatch(u.path)
    if not m or m[1] in ('.', '..') or m[2] in ('.', '..'):
        raise Unavailable('unsupported GitHub source URL')
    info = {'repo': f'{m[1]}/{m[2]}'}
    if f := FILE.fullmatch(m[3]):
        info.update(kind='file', revision=f[1], path=_path(f[2]))
        if u.fragment:
            r = RANGE.fullmatch(u.fragment)
            if not r:
                raise Unavailable('unsupported file line range')
            info.update(start=int(r[1]), end=int(r[2] or r[1]))
    elif p := PR.fullmatch(m[3]):
        info.update(kind='diff' if p[2] else 'pr_body', pr=int(p[1]))
        if p[2]:
            d = DIFF.fullmatch(u.fragment)
            if not d or d[4] and d[4] != d[2]:
                raise Unavailable('diff citations need a filename hash and a same-side line range')
            info.update(file_hash=d[1], side=d[2], start=int(d[3]), end=int(d[5] or d[3]))
        elif u.fragment:
            raise Unavailable('PR comments and other PR fragments are not description sources')
    else:
        raise Unavailable('unsupported GitHub source; files require a full commit SHA')
    if info.get('end', 1) < info.get('start', 1):
        raise Unavailable('reversed line range')
    return info


def _sha(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(SHA, value):
        raise Unavailable('missing full commit identity')
    return value


def _patch(file: dict) -> list[list[dict]]:
    """Validate every hunk and totals before allowing a positive OR negative match."""
    patch = file.get('patch')
    if not isinstance(patch, str) or not patch:
        raise Unavailable('patch unavailable (binary, too large or omitted)')
    lines = patch.replace('\r\n', '\n').split('\n')
    if len(lines) > MAX_LINES:
        raise Unavailable('patch line limit exceeded')
    groups, group = [], None
    old = new = used_old = used_new = old_count = new_count = 0
    additions = deletions = 0
    prev_old = prev_new = -1
    for line in lines:
        check_time()
        if m := HUNK.fullmatch(line):
            if group is not None and (used_old != old_count or used_new != new_count):
                raise Unavailable('truncated hunk')
            old, new = int(m[1]), int(m[3])
            if old < prev_old or new < prev_new:
                raise Unavailable('overlapping or unordered hunks')
            old_count, new_count = int(m[2] or 1), int(m[4] or 1)
            used_old = used_new = 0
            group = []
            groups.append(group)
        elif line == '\\ No newline at end of file':
            if group is None or not group:
                raise Unavailable('misplaced no-newline marker')
        elif group is not None and line[:1] in (' ', '+', '-'):
            kind = {' ': 'context', '+': 'added', '-': 'deleted'}[line[0]]
            group.append({'text': line[1:], 'kind': kind, 'L': old if kind != 'added' else None,
                          'R': new if kind != 'deleted' else None})
            if kind != 'added': old += 1; used_old += 1
            if kind != 'deleted': new += 1; used_new += 1
            additions += kind == 'added'
            deletions += kind == 'deleted'
            if used_old > old_count or used_new > new_count:
                raise Unavailable('hunk exceeds declared line counts')
            prev_old, prev_new = old, new
        else:
            raise Unavailable('malformed patch')
    if group is None or used_old != old_count or used_new != new_count:
        raise Unavailable('truncated hunk')
    if type(file.get('additions')) is not int or type(file.get('deletions')) is not int \
            or additions != file['additions'] or deletions != file['deletions']:
        raise Unavailable('patch totals disagree with file metadata')
    return groups


class Resolver:
    def __init__(self, store, github, fetch: bool):
        self.store, self.github, self.fetch = store, github, fetch
        self.cache = {}
        self.api_cache = {}
        # Digests observed by this resolver only; never persisted as trusted origin.
        self.fresh = set()

    def _get(self, path: str):
        if path not in self.api_cache:
            check_time()
            data = self.github(path)
            if data is None:
                raise Unavailable('GitHub source unavailable')
            # Freeze the callback result: a reused mutable dict cannot change evidence after it was judged.
            self.api_cache[path] = json.loads(json.dumps(data, ensure_ascii=False))
        return self.api_cache[path]

    def _collect(self, info: dict) -> dict:
        root = f"/repos/{info['repo']}"
        if info['kind'] == 'file':
            data = self._get(f"{root}/contents/{quote(info['path'], safe='/')}?ref={info['revision']}")
            return {'file': data}
        pr = self._get(f"{root}/pulls/{info['pr']}")
        if not isinstance(pr, dict):
            raise Unavailable('invalid PR response')
        if info['kind'] == 'pr_body':
            return {'pr': pr}
        base, head = _sha(pr.get('base', {}).get('sha')), _sha(pr.get('head', {}).get('sha'))
        comparison = self._get(f'{root}/compare/{base}...{head}')
        return {'pr': pr, 'comparison': comparison}

    def _source(self, url: str, info: dict) -> tuple[dict, dict]:
        if url in self.cache:
            self.store.read(self.cache[url][0]['sha256'])
            return self.cache[url]
        if self.fetch and self.github is not None:
            bundle = {'schema': SCHEMA, 'url': url, 'identity': info, 'responses': self._collect(info)}
            data = json.dumps(bundle, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            entry = self.store.add(url, data, content_type='application/json', github_source=url,
                                   via='github_api', provenance='github_api')
            self.fresh.add(entry['sha256'])
        else:
            if not SAVED_SOURCES.get():
                raise Unavailable('saved GitHub sources cannot be replayed on the public server; request a live check')
            entries = self.store.index().get(canonical_url(url), [])
            entry = next((e for e in reversed(entries) if e.get('github_source') == url), None)
            if not entry or not entry.get('sha256'):
                raise Unavailable('no saved GitHub evidence for this exact citation; fetching is off')
            bundle = json.loads(self.store.read(entry['sha256']).decode('utf-8'))
            if bundle.get('schema') != SCHEMA or bundle.get('url') != url or bundle.get('identity') != info:
                raise Unavailable('saved evidence scope does not match the citation')
        self.cache[url] = (entry, bundle['responses'])
        return self.cache[url]

    def check(self, claim: dict) -> dict:
        urls = list(dict.fromkeys(claim.get('urls', [])))
        if len(urls) != 1:
            return dict(claim, verdict='UNCERTAIN', doubts=['ambiguous_github_source'])
        url = urls[0]
        try:
            info = _identity(url)
            entry, responses = self._source(url, info)
            metadata, groups = self._segments(info, responses)
            literal = claim['quote'].replace('\r\n', '\n')
            wanted = None
            if claim.get('diff'):
                if info['kind'] != 'diff':
                    raise Unavailable('a diff fence requires a diff source')
                raw_lines = literal.split('\n')
                if any(line[:1] not in ('+', '-', ' ') for line in raw_lines):
                    raise Unavailable('diff fence must contain literal prefixed patch lines only')
                wanted = [{'text': line[1:], 'kind': {'+': 'added', '-': 'deleted', ' ': 'context'}[line[0]]}
                          for line in raw_lines]
            matches = []
            for group in groups:
                check_time()
                if wanted is not None:
                    for i in range(len(group) - len(wanted) + 1):
                        chunk = group[i:i + len(wanted)]
                        if all(a['text'] == b['text'] and a['kind'] == b['kind'] for a, b in zip(chunk, wanted)):
                            matches.append((chunk[0]['number'], chunk[-1]['number'], [a['kind'] for a in chunk]))
                else:
                    joined = '\n'.join(line['text'] for line in group)
                    at = joined.find(literal) if literal else -1
                    if claim.get('block'):
                        # A fenced excerpt quotes whole lines, including its indentation.
                        at = next((m.start() for m in re.finditer(re.escape(literal), joined)
                                   if (m.start() == 0 or joined[m.start() - 1] == '\n')
                                   and (m.end() == len(joined) or joined[m.end()] == '\n')), -1) if literal else -1
                    if at >= 0:
                        first = joined[:at].count('\n')
                        last = first + literal.count('\n')
                        matches.append((group[first]['number'], group[last]['number'],
                                        [a['kind'] for a in group[first:last + 1]]))
            if matches:
                a, b, kinds = matches[0]
                metadata.update(start_line=a, end_line=b, kinds=kinds)
            metadata['normalization'] = 'crlf_to_lf'
            metadata['collection'] = 'live' if entry['sha256'] in self.fresh else 'stored'
            return dict(claim, verdict='FOUND' if matches else 'NOT_FOUND', url=url, sha256=entry['sha256'],
                        fetched_at=entry.get('fetched_at'), via='github_api', provenance='github_api', github=metadata)
        except (Unavailable, effects.GitHubUnavailable, ValueError, TypeError, KeyError, AttributeError,
                OSError, UnicodeError, binascii.Error) as error:
            return dict(claim, verdict='SOURCE_UNAVAILABLE', url=url, error=str(error)[:240])

    def _segments(self, info: dict, responses: dict) -> tuple[dict, list[list[dict]]]:
        metadata = dict(info)
        if info['kind'] == 'file':
            data = responses['file']
            if not isinstance(data, dict) or data.get('type') != 'file' or data.get('encoding') != 'base64' \
                    or data.get('path') != info['path'] or not isinstance(data.get('content'), str):
                raise Unavailable('file content unavailable or unsupported')
            raw = base64.b64decode(''.join(data['content'].split()), validate=True)
            text = raw.decode('utf-8')
            if '\x00' in text:
                raise Unavailable('binary source')
        elif info['kind'] == 'pr_body':
            text = responses['pr']['body']
            if text is None:
                text = ''  # GitHub uses null for an empty description
            if not isinstance(text, str):
                raise Unavailable('invalid description body')
        else:
            pr, comparison = responses['pr'], responses['comparison']
            metadata.update(base=_sha(pr['base']['sha']), head=_sha(pr['head']['sha']),
                            merge_base=_sha(comparison['merge_base_commit']['sha']))
            files = comparison.get('files')
            if not isinstance(files, list):
                raise Unavailable('compare files unavailable')
            selected = [f for f in files if isinstance(f, dict) and isinstance(f.get('filename'), str)
                        and hashlib.sha256(f['filename'].encode('utf-8')).hexdigest() == info['file_hash']]
            if len(selected) != 1:
                raise Unavailable('addressed file unavailable in compare response (possibly truncated)')
            file = selected[0]
            metadata['path'] = file['filename']
            groups = []
            for hunk in _patch(file):
                group = []
                for line in hunk:
                    number = line[info['side']]
                    if number is not None and info['start'] <= number <= info['end']:
                        group.append(dict(line, number=number))
                if group:
                    groups.append(group)
            if sum(len(g) for g in groups) != info['end'] - info['start'] + 1:
                raise Unavailable('addressed diff range is not completely available')
            return metadata, groups
        lines = text.replace('\r\n', '\n').split('\n')
        if len(lines) > MAX_LINES:
            raise Unavailable('source line limit exceeded')
        start, end = info.get('start', 1), info.get('end', len(lines))
        if start > len(lines) or end > len(lines):
            raise Unavailable('line range outside source')
        return metadata, [[{'text': t, 'number': i, 'kind': 'text'}
                           for i, t in enumerate(lines, 1) if start <= i <= end]]
