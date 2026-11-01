"""Map declared Markdown audiences to synthetic profile facts before judging commands."""
import json
from pathlib import Path
import re
import unicodedata

from commands import extract, FENCE, table_cells, inline_rows
from facts import observation, value
from syntax import family
from shell_lists import lex
from control import has_control, complete as control_complete

DATA = json.loads(Path(__file__).with_name('section_targets.json').read_text(encoding='utf-8'))


def identify_flat(label):
    """Aliases are data; alternatives within an axis are OR, distinct axes are AND."""
    out = {}
    for row in DATA['labels']:
        if re.search(row['pattern'], label, re.I):
            for axis, values in row['targets'].items():
                out[axis] = sorted(set(out.get(axis, [])) | set(values))
    # WSL names its Linux guest, even though its expanded name contains 'Windows'.
    if out.get('runtime') == ['wsl']:
        out['os'] = ['linux']
    return out


def identify(label):
    label = unicodedata.normalize('NFKC', label).replace('\u2011', '-').replace('**', '')
    # A named broad Linux audience is not narrowed by examples in parentheses.
    if re.match(r'^\W*(?:\d\W*)?Linux\b(?:\s*$|\s*\()', label, re.I):
        return {'os': ['linux']}
    # Enumerations are unions of correlated systems, including WSL as one member.
    enumeration = re.search(r'\(([^()]*(?:Linux|macOS|WSL)[^()]*)\)', label, re.I)
    if enumeration and re.search(r',|\band\b|&', enumeration[1], re.I):
        parts = [identify_flat(s) for s in re.split(r',|\band\b|&', enumeration[1], flags=re.I)]
        if len(parts) > 1 and all(parts):
            return {'any_of': parts}
    if re.search(r'git\s*bash|msys2', label, re.I):
        target = next(r['targets'] for r in DATA['labels'] if r['id'] == 'git-bash')
        return {'any_of': [target, {'os': ['linux'], 'runtime': ['wsl']}]} if re.search(r'\bwsl\b', label, re.I) else dict(target)
    # Keep correlated alternatives (Windows / Ubuntu) separate, while aliases
    # differing in one axis (Debian/Ubuntu) can share the same constraint row.
    clauses = re.split(r'\s*(?:/|\bor\b|\band\b|&|,)\s*(?![^()]*\))', label, flags=re.I)
    targets = [identify_flat(c) for c in clauses]
    if len(targets) > 1 and all(targets):
        axes = set().union(*targets)
        differing = [a for a in axes if len({tuple(t.get(a, [])) for t in targets}) > 1]
        if len(differing) > 1:
            return {'any_of': targets}
    out = identify_flat(label)
    if 'runtime' in out and ('darwin' in out.get('os', []) or re.search(r'\blinux\b.*\bwsl\b', label, re.I)):
        out.pop('runtime')
        if re.search(r'\bmacos\b', label, re.I):
            out['os'] = sorted(set(out.get('os', [])) | {'darwin'})
    return out


def merge(parent, child):
    if 'any_of' in parent or 'any_of' in child:
        return {'any_of': [merge(p, c) for p in parent.get('any_of', [parent])
                           for c in child.get('any_of', [child])]}
    out = dict(parent)
    if child.get('runtime') == ['wsl'] and parent.get('os') == ['windows']:
        out.pop('os')  # The named WSL guest has Linux facts, despite a Windows host heading.
    for axis, values in child.items():
        out[axis] = sorted(set(out[axis]) & set(values)) if axis in out else list(values)
    return out


def identity(target):
    if 'any_of' in target:
        return json.dumps(target, sort_keys=True)
    for axis in ('runtime', 'distro', 'os', 'package_manager', 'shell'):
        if axis in target:
            fields = {axis: target[axis]}
            if axis != 'shell' and 'shell' in target:
                fields['shell'] = target['shell']
            if axis == 'os' and 'package_manager' in target:
                fields['package_manager'] = target['package_manager']
            return json.dumps(fields, sort_keys=True)
    return None


def matches(target, profile):
    if 'any_of' in target:
        return any(matches(t, profile) for t in target['any_of'])
    platform = profile['document']['collector']['platform']
    for axis, wanted in target.items():
        if not wanted:
            return False
        if axis == 'os' and platform not in wanted:
            return False
        if axis == 'distro' and value(profile, 'system.os', 'distribution_id') not in wanted:
            return False
        if axis == 'runtime' and value(profile, 'system.os', 'runtime_context') not in wanted:
            return False
        if axis == 'observed_shell' and not any(observation(profile, 'system.shell', name).get('status') == 'observed' for name in wanted):
            return False
        if axis == 'package_manager' and not any(
                observation(profile, 'software.package_managers', name).get('status') == 'observed' for name in wanted):
            return False
        if axis == 'shell':
            available = {family(profile['shell'])}
            for name in ('bash', 'zsh', 'pwsh', 'powershell', 'cmd'):
                if observation(profile, 'system.shell', name).get('status') == 'observed':
                    available.add('powershell' if name == 'pwsh' else family(name))
            if any(observation(profile, 'system.shell', n).get('status') == 'observed' for n in ('git_bash', 'git-bash', 'msys2')):
                available.add('posix')
            if not available.intersection(wanted):
                return False
    return True


def label(line):
    text = line.strip()
    heading = re.match(r'^(#{1,6})\s+(.+?)(?:\s+#+)?$', text)
    if heading:
        return len(heading[1]), heading[2], ''
    text = re.sub(r'^(?:[-*+]\s+|\d+[.)]\s+)', '', text)
    bold = re.match(r'^(?:\*\*|__)(.+?)(?:\*\*|__)\s*[:–—-]?\s*(.*)$', text)
    if bold:
        return 0, bold[1].rstrip(':'), bold[2]
    colon = re.match(r'^([^:`]{1,100}):\s*(.*)$', text)
    if colon:
        return 0, colon[1], colon[2]
    return None


def partition(answer):
    """Headings scope by depth; unrecognized child headings inherit, peers end that scope."""
    sections, declared, stack, flat, buffer = [], [], [], None, []
    prose, command_groups, flat_depth = set(), set(), 2
    scopes = {}
    opened, block, block_context = None, [], None
    previous_text, output_block = '', False

    def context():
        return flat if flat is not None else stack[-1][1:] if stack else ({}, '', None)

    def append_commands(commands, ctx, block_target, tag, scope_id=None):
        target, name, group = ctx
        labelled = group is not None
        combined = merge(target, block_target)
        if commands:
            command_groups.add(group)
            if group is None and block_target:
                group = identity(block_target)
            for command in commands:
                if command['shell'] == 'unknown' and len(target.get('shell', [])) == 1:
                    command['shell'] = target['shell'][0]
            sections.append(dict(label=name or tag or 'shared', targets=combined, group=group, labelled=labelled,
                                 scope=scopes.get(id(target), 'shared') if scope_id is None else scope_id, commands=commands))
    def flush(lines, ctx, tag=None):
        target, name, group = ctx
        if tag is not None:
            # System labels in shell comments constrain only subsequent commands in
            # this fence; ordinary comments remain part of the intact syntax unit.
            active, chunk = target, []
            marker = FENCE.match(lines[0])[1] if lines and FENCE.match(lines[0]) else '```'
            body = lines[1:-1] if lines and FENCE.match(lines[-1]) else lines[1:]
            def emit():
                append_commands(extract(marker + tag + '\n' + '\n'.join(chunk) + '\n' + marker),
                                (active, name, group), DATA['block_tags'].get(tag, {}), tag,
                                scopes.get(id(target), 'shared') if active == target else (scopes.get(id(target), 'shared'), identity(active)))
            for line in body:
                comment = re.match(r'^\s*#\s*(.+)$', line)
                audience = identify(comment[1]) if comment else {}
                prefix = '\n'.join(chunk)
                tokens = lex(prefix, tag or 'sh')
                intact = (not tokens or tokens[-1].closed) and (not has_control(prefix) or control_complete(prefix))
                if audience and intact:
                    emit()
                    chunk = []
                    active = merge(target, audience)
                else:
                    chunk.append(line)
            emit()
            return
        command_columns, audience_column = set(), None
        for line_index, line in enumerate(lines):
            cells = table_cells(line)
            entries = [(line, False, target)]
            if cells is not None:
                headers = {i for i, c in enumerate(cells) if re.fullmatch(r'(?:activation\s+)?commands?', c.strip('* '), re.I)}
                if headers:
                    command_columns = headers
                    audience_column = next((i for i, c in enumerate(cells) if re.fullmatch(r'(?:OS|system|shell(?:\s*/\s*prompt)?)', c.strip('* '), re.I)), None)
                    continue
                if line_index + 1 < len(lines) and re.fullmatch(r'\s*\|?[\s:|-]+\|?\s*', lines[line_index + 1]):
                    command_columns, audience_column = set(), None
                    continue
                row_target = identify(cells[audience_column]) if audience_column is not None and audience_column < len(cells) else {}
                entries = [(cell, i in command_columns, merge(target, row_target)) for i, cell in enumerate(cells)]
            for text, force, enclosing in entries:
                for command in inline_rows(text, force):
                    audience = identify(command.pop('audience') or '')
                    local = merge(enclosing, audience)
                    local_group = identity(local) if audience else group
                    append_commands([command], (local, name, local_group), {}, None,
                                    scopes.get(id(target), 'shared'))
        if group is not None and any(line.strip() for line in lines):
            prose.add(group)

    for line in answer.splitlines():
        fence = FENCE.match(line)
        if opened:
            block.append(line)
            if fence and fence[1][0] == opened[0][0] and len(fence[1]) >= len(opened[0]) and not fence[2]:
                if not output_block:
                    flush(block, block_context, opened[1])
                opened, block = None, []
            continue
        if fence:
            output_block = not fence[2] and bool(re.search(r'(?i)(?:typical|expected|example|sample) output|output (?:will|would|should) look|you should see (?:output|something)', previous_text))
            previous_text = ''
            flush(buffer, context())
            buffer = []
            opened, block, block_context = (fence[1], fence[2].lower()), [line], context()
            continue
        if line.strip():
            previous_text = line.strip()
        found = label(line)
        if found:
            level, title, rest = found
            target = identify(re.sub(r'`+[^`]*`+', '', title))
            if level or target:
                flush(buffer, context())
                buffer = []
                if level:
                    if flat is not None and not target and level > flat_depth:
                        if '`' in title:
                            buffer.append(title)
                        continue
                    flat = None
                    while stack and stack[-1][0] >= level:
                        stack.pop()
                    parent = stack[-1][1:] if stack else ({}, '', None)
                    combined = merge(parent[0], target) if target else parent[0]
                    ctx = (combined, title if target else parent[1], identity(combined) if target else parent[2])
                    stack.append((level, *ctx))
                else:
                    parent = stack[-1][1:] if stack else ({}, '', None)
                    combined = merge(parent[0], target)
                    flat = (combined, title, identity(combined))
                    flat_depth = max(2, stack[-1][0] + 1) if stack else 2
                if target:
                    scopes[id(combined)] = len(declared)
                    declared.append(dict(targets=combined, group=identity(combined), label=title))
                # Headings can themselves contain an instruction to run code.
                if '`' in title:
                    buffer.append(title)
                if rest:
                    buffer.append(rest)
                continue
        buffer.append(line)
    if opened:
        if not output_block:
            flush(block, block_context, opened[1])
    flush(buffer, context())
    for entry in declared:
        if entry['group'] in prose and entry['group'] not in command_groups:
            sections.append(dict(label=entry['label'], targets=entry['targets'], group=entry['group'],
                                 labelled=True, commands=[]))
    return sections, [entry['targets'] for entry in declared]


def select(answer, profile):
    parts, labels = partition(answer)
    has_sections = bool(labels) or any(p['targets'] for p in parts)
    labelled = [p for p in parts if p['labelled']]
    applicable = (any(matches(p['targets'], profile) for p in labelled) if labels and labelled else
                  any(matches(t, profile) for t in labels) if labels else
                  any(matches(p['targets'], profile) for p in parts if p['targets']) if has_sections else True)
    groups = {p['group'] for p in parts if p['group']}
    if not groups:
        groups = {identity(t) for t in labels}
    hedged = len(groups) > 1 or any(len(t.get('os', [])) > 1 or len(t.get('any_of', [])) > 1 for t in labels)
    commands = []
    for part in parts:
        part['applies'] = applicable and matches(part['targets'], profile)
        if part['applies']:
            commands.extend(dict(c, section=part['label'], section_id=part.get('scope', 'shared')) for c in part['commands'])
    return dict(sections=parts, has_sections=has_sections, applicable=applicable,
                targeting='HEDGED' if hedged else 'TARGETED', commands=commands,
                commands_total=sum(len(p['commands']) for p in parts), commands_for_profile=len(commands))
