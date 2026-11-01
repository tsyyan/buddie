"""Map declared Markdown audiences to synthetic profile facts before judging commands."""
import json
from pathlib import Path
import re

from commands import extract, FENCE
from facts import observation, value
from syntax import family

DATA = json.loads(Path(__file__).with_name('section_targets.json').read_text(encoding='utf-8'))


def identify(label):
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


def merge(parent, child):
    out = dict(parent)
    for axis, values in child.items():
        out[axis] = sorted(set(out[axis]) & set(values)) if axis in out else list(values)
    return out


def identity(target):
    for axis in ('runtime', 'distro', 'os', 'package_manager', 'shell'):
        if axis in target:
            fields = {axis: target[axis]}
            if axis != 'shell' and 'shell' in target:
                fields['shell'] = target['shell']
            return json.dumps(fields, sort_keys=True)
    return None


def matches(target, profile):
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
        if axis == 'package_manager' and not any(
                observation(profile, 'software.package_managers', name).get('status') == 'observed' for name in wanted):
            return False
        if axis == 'shell':
            available = {family(profile['shell'])}
            for name in ('bash', 'zsh', 'pwsh', 'powershell', 'cmd'):
                if observation(profile, 'system.shell', name).get('status') == 'observed':
                    available.add('powershell' if name == 'pwsh' else family(name))
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
    opened, block, block_context = None, [], None

    def context():
        return flat if flat is not None else stack[-1][1:] if stack else ({}, '', None)

    def flush(lines, ctx, tag=None):
        target, name, group = ctx
        labelled = group is not None
        commands = extract('\n'.join(lines))
        block_target = DATA['block_tags'].get(tag, {})
        combined = merge(target, block_target)
        if commands:
            if group is None and block_target:
                group = identity(block_target)
            for command in commands:
                if command['shell'] == 'unknown' and len(target.get('shell', [])) == 1:
                    command['shell'] = target['shell'][0]
            sections.append(dict(label=name or tag or 'shared', targets=combined, group=group, labelled=labelled,
                                 commands=commands))

    for line in answer.splitlines():
        fence = FENCE.match(line)
        if opened:
            block.append(line)
            if fence and fence[1][0] == opened[0][0] and len(fence[1]) >= len(opened[0]) and not fence[2]:
                flush(block, block_context, opened[1])
                opened, block = None, []
            continue
        if fence:
            flush(buffer, context())
            buffer = []
            opened, block, block_context = (fence[1], fence[2].lower()), [line], context()
            continue
        found = label(line)
        if found:
            level, title, rest = found
            target = identify(title)
            if level or target:
                flush(buffer, context())
                buffer = []
                if level:
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
                if target:
                    declared.append(combined)
                if rest:
                    buffer.append(rest)
                continue
        buffer.append(line)
    if opened:
        flush(block, block_context, opened[1])
    flush(buffer, context())
    return sections, declared


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
    hedged = len(groups) > 1 or any(len(t.get('os', [])) > 1 for t in labels)
    commands = []
    for part in parts:
        part['applies'] = applicable and matches(part['targets'], profile)
        if part['applies']:
            commands.extend(dict(c, section=part['label']) for c in part['commands'])
    return dict(sections=parts, has_sections=has_sections, applicable=applicable,
                targeting='HEDGED' if hedged else 'TARGETED', commands=commands,
                commands_total=sum(len(p['commands']) for p in parts), commands_for_profile=len(commands))
