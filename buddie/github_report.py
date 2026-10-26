"""Code citations from Markdown. Conservative source binding; not a general CommonMark parser.

Inline code uses the prose reader's same-sentence binding. Fences use adjacent citation paragraphs only.
Unlinked code examples are outside this adapter's scope. Multiple bound URLs remain an explicit gap.
"""
from __future__ import annotations

import re

from buddie.github_sources import is_github
from buddie.verbatim import report

INLINE = re.compile(r'(?<!`)(`+)(?!`)([^\n]*?)(?<!`)\1(?!`)')
OPEN = re.compile(r'^ {0,3}(`{3,}|~{3,})([^\n]*)$')


def _fences(text: str):
    # Split only LF: splitlines() also consumes lone CR and Unicode separators.
    lines = text.split('\n')
    lengths = [len(line) + (i < len(lines) - 1) for i, line in enumerate(lines)]
    i, offset = 0, 0
    while i < len(lines):
        line = lines[i].removesuffix('\r') if i < len(lines) - 1 else lines[i]
        match = OPEN.fullmatch(line)
        if not match:
            offset += lengths[i]; i += 1
            continue
        marker, language = match[1], match[2].strip()
        start, first = offset, i
        offset += lengths[i]; i += 1
        body = []
        while i < len(lines):
            current = lines[i].removesuffix('\r') if i < len(lines) - 1 else lines[i]
            offset += lengths[i]; i += 1
            if re.fullmatch(r' {0,3}' + re.escape(marker[0]) + '{' + str(len(marker)) + r',}\s*', current):
                yield start, offset, first + 2, '\n'.join(body), language
                break
            body.append(current)
        # An unclosed fence is code too; never look for citations inside it.
        else:
            yield start, offset, first + 2, '\n'.join(body), language


def _defs(text: str) -> dict:
    out = {}
    for key, value in report.DEF.findall(text):
        if m := report.URL.search(value):
            out[key.lower()] = m.group()
    return out


def _urls(block: str, defs: dict) -> list[str]:
    return report._unique(u for _, _, u in report._links(block, defs) if u)


def _citation_only(block: str, defs: dict) -> bool:
    chars = list(block)
    for a, b, _ in report._links(block, defs):
        chars[a:b] = ' ' * (b - a)
    return not ''.join(chars).strip(' \t\r\n.,;:()[]*_')


def code_claims(text: str) -> list[dict]:
    fences = list(_fences(text))
    masked = list(text)
    for a, b, *_ in fences:
        for i in range(a, b):
            if masked[i] not in '\r\n': masked[i] = ' '
    body = ''.join(masked)
    defs = _defs(body)
    claims = []
    for line, block, _ in report._blocks(body, literal=True):
        links = report._links(block, defs)
        for m in INLINE.finditer(block):
            if any(a <= m.start() < b for a, b, _ in links):
                continue  # link labels and targets are not code citations
            external = [(a, b, u) for a, b, u in links if b <= m.start() or a >= m.end()]
            urls, binding = report._own_links(block, external, m.start(), m.end())
            if binding == 'previous':
                before = [(a, b, u) for a, b, u in external if b <= m.start()]
                cluster = [before[-1]]
                for prior in reversed(before[:-1]):
                    if not report.BETWEEN_LINKS.fullmatch(block[prior[1]:cluster[0][0]]):
                        break
                    cluster.insert(0, prior)
                urls = report._unique(u for _, _, u in cluster if u)
            if urls and any(is_github(u) for u in urls):
                number = line + block[:m.start()].count('\n')
                claims.append({'id': f'G{number}.{len(claims) + 1}', 'line': number, 'quote': m[2],
                               'urls': urls, 'attributed': True, 'code': True})
    for a, b, line, code, language in fences:
        before = body[:a].rstrip('\r\n')
        after = body[b:].lstrip('\r\n')
        previous = re.split(r'\n\s*\n', before)[-1] if before else ''
        following = re.split(r'\n\s*\n', after)[0] if after else ''
        # A heading is a scope boundary, even when it happens to contain a source link.
        boundaries = list(re.finditer(r'^ {0,3}(?:#{1,6}(?:[ \t]|$).*|(?:=+|-+)\s*)$', previous, re.M))
        if boundaries:
            previous = previous[boundaries[-1].end():]
        urls = _urls(previous, defs)
        next_urls = _urls(following, defs) if _citation_only(following, defs) else []
        urls = report._unique(urls + next_urls)
        if urls and any(is_github(u) for u in urls):
            claims.append({'id': f'G{line}.{len(claims) + 1}', 'line': line, 'quote': code, 'urls': urls,
                           'attributed': True, 'code': True, 'block': True, 'diff': language == 'diff'})
    return sorted(claims, key=lambda c: c['line'])
