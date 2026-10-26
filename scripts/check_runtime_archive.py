"""Fail closed on unapproved runtime archive members, without extraction or execution.

This checks file selection and archive structure, not confidentiality of allowed source text.
Manifest validation, provenance verification and installed runtime smoke checks are separate gates.
"""
from __future__ import annotations

import argparse
import re
import stat
import struct
import sys
import tarfile
import zipfile
import zlib
from pathlib import Path

# Explicit audited files. New runtime modules require a deliberate policy review.
RUNTIME = frozenset('''
buddie/__init__.py buddie/__main__.py buddie/anchors.py buddie/chains.py
buddie/cli.py buddie/config.py buddie/context.py buddie/core.py buddie/decisions.py
buddie/diagnostics.py buddie/effects.py buddie/environment.py buddie/event.py
buddie/evidence.py buddie/feedback.py buddie/findings.py buddie/freshness.py
buddie/github_report.py buddie/github_sources.py buddie/hook.py buddie/journal.py
buddie/logbook.py buddie/mandate.py buddie/mcp.py buddie/modules.py buddie/patterns.py
buddie/policy.py buddie/probes.py buddie/profiles.py buddie/promises.py buddie/receipts.py
buddie/remote.py buddie/repair.py buddie/resolved.py buddie/runner.py buddie/stores.py
buddie/suggest.py buddie/summary.py buddie/trace.py buddie/verify.py buddie/winacl.py
buddie/verbatim/__init__.py buddie/verbatim/__main__.py buddie/verbatim/access.py
buddie/verbatim/check.py buddie/verbatim/cli.py buddie/verbatim/numbers.py
buddie/verbatim/report.py buddie/verbatim/store.py buddie/verbatim/textlayer.py
'''.split())
LEGAL = {'README.md', 'LICENSE', 'NOTICE', 'PRIVACY.md'}
SDIST = (LEGAL - {'README.md'}) | {'packaging/README.md', 'run.py', 'pyproject.toml', 'MANIFEST.in', 'PKG-INFO', 'setup.cfg'}
EGG = {'PKG-INFO', 'SOURCES.txt', 'dependency_links.txt', 'entry_points.txt', 'requires.txt', 'top_level.txt'}
DIST = {'METADATA', 'WHEEL', 'entry_points.txt', 'top_level.txt', 'RECORD',
        'licenses/LICENSE', 'licenses/NOTICE', 'licenses/PRIVACY.md'}
MCPB = LEGAL | {'RELEASE_NOTES.md', 'manifest.json', 'run.py', 'assets/icon.png'}
PLUGIN = LEGAL | {'RELEASE_NOTES.md', '.claude-plugin/plugin.json', '.claude-plugin/marketplace.json', '.mcp.json', 'run.py',
                  'hooks/hooks.json', 'hooks/run.sh', 'assets/icon.png', 'skills/buddie/SKILL.md',
                  'skills/verbatim/SKILL.md', 'commands/check.md', 'commands/init.md', 'commands/status.md'}
VERSION = r'\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?(?:\.post\d+)?(?:\.dev\d+)?'
PLAIN = re.compile(r'[A-Za-z0-9_-][A-Za-z0-9._-]*|\.[A-Za-z0-9_-][A-Za-z0-9._-]*')
RESERVED = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{p}{n}' for p in ('COM', 'LPT') for n in range(1, 10)}
MAX_MEMBERS, MAX_FILE, MAX_BYTES = 256, 2 * 1024 * 1024, 8 * 1024 * 1024
LOCAL_HEADER = struct.Struct('<4s5H3I2H')


def policy(kind: str, prefix: str = '') -> tuple[set[str], set[str]]:
    """Allowed and mandatory files, relative to the archive's single source root."""
    if kind == 'wheel':
        required = set(RUNTIME) | {prefix + '/' + p for p in DIST}
        return required, required
    if kind == 'sdist':
        required = set(RUNTIME) | SDIST | {'buddie.egg-info/' + p for p in EGG}
        return required, required
    required = set(RUNTIME) | (MCPB if kind == 'mcpb' else PLUGIN)
    return required | ({'SECURITY.md'} if kind == 'mcpb' else set()), required


def unsafe(name: str) -> bool:
    return (len(name) > 240 or any(not PLAIN.fullmatch(p) or p in {'.', '..'} or p.endswith('.')
            or p.split('.')[0].upper() in RESERVED for p in name.split('/')))


def verify_zip_streams(path: Path) -> None:
    """Verify local metadata and complete STORED/DEFLATE streams without trusting claimed output sizes."""
    with zipfile.ZipFile(path) as archive, path.open('rb') as raw:
        members = archive.infolist()
        raw.seek(0, 2)
        length = raw.tell()
        raw.seek(max(0, length - 22))
        end = raw.read(22)
        if len(end) != 22:
            raise ValueError('truncated ZIP end record')
        signature, disk, start_disk, disk_count, total_count, central_size, central_offset, comment = struct.unpack('<4s4H2IH', end)
        if (signature != b'PK\x05\x06' or disk or start_disk or comment or archive.comment
                or disk_count != len(members) or total_count != len(members)
                or central_offset != archive.start_dir or central_offset + central_size != length - 22):
            raise ValueError('unreviewed ZIP prefix, trailer, comment or end record')
        cursor = 0
        for member in sorted(members, key=lambda m: m.header_offset):
            if member.header_offset != cursor:
                raise ValueError('ZIP carries unindexed local data or a prefix')
            if member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise ValueError('unaudited ZIP compression')
            if member.compress_size > MAX_FILE * 2 + 1024:
                raise ValueError('compressed member exceeds runtime bounds')
            raw.seek(member.header_offset)
            header = raw.read(LOCAL_HEADER.size)
            if len(header) != LOCAL_HEADER.size:
                raise ValueError('truncated ZIP local header')
            signature, _version, flags, method, _time, _date, crc, compressed, size, name_len, extra_len = LOCAL_HEADER.unpack(header)
            if signature != b'PK\x03\x04' or extra_len:
                raise ValueError('unreviewed ZIP local header or extra fields')
            if flags != member.flag_bits or method != member.compress_type:
                raise ValueError('ZIP local flags/compression disagree with directory')
            if not flags & 8 and (crc, compressed, size) != (member.CRC, member.compress_size, member.file_size):
                raise ValueError('ZIP local sizes/CRC disagree with directory')
            # ZipFile.open checks local filename agreement and overlapping data ranges without reading payload.
            with archive.open(member):
                pass
            raw.seek(member.header_offset + LOCAL_HEADER.size + name_len)
            decoder = zlib.decompressobj(-15) if method == zipfile.ZIP_DEFLATED else None
            remaining, count, actual_crc = member.compress_size, 0, 0
            while remaining:
                block = raw.read(min(64 * 1024, remaining))
                if not block:
                    raise ValueError('truncated ZIP payload')
                remaining -= len(block)
                output = decoder.decompress(block, member.file_size + 1 - count) if decoder else block
                count += len(output)
                if count > member.file_size:
                    raise ValueError('ZIP payload exceeds declared size')
                actual_crc = zlib.crc32(output, actual_crc)
                if decoder and (decoder.unused_data or decoder.unconsumed_tail):
                    raise ValueError('ZIP payload has trailing or excess data')
            if decoder and not decoder.eof:
                raise ValueError('ZIP compressed stream is incomplete')
            if count != member.file_size or actual_crc != member.CRC:
                raise ValueError('ZIP payload size/CRC mismatch')
            if flags & 8:
                descriptor = raw.read(4)
                if descriptor == b'PK\x07\x08':
                    descriptor = raw.read(12)
                else:
                    descriptor += raw.read(8)
                if len(descriptor) != 12 or struct.unpack('<3I', descriptor) != (member.CRC, member.compress_size, member.file_size):
                    raise ValueError('ZIP data descriptor disagrees with directory')
            cursor = raw.tell()
        if cursor != archive.start_dir:
            raise ValueError('ZIP carries unindexed data before its directory')


def problems(path: Path) -> list[str]:
    kind = ('sdist' if path.name.endswith('.tar.gz') else
            {'.whl': 'wheel', '.mcpb': 'mcpb', '.zip': 'plugin'}.get(path.suffix))
    if kind is None:
        return ['unsupported archive format']
    errors = []
    try:
        if kind == 'sdist':
            with tarfile.open(path, 'r:gz') as archive:
                members = [(m.name, m.isdir(), m.isfile() or m.isdir(), m.size) for m in archive.getmembers()]
        else:
            with zipfile.ZipFile(path) as archive:
                members = [(m.orig_filename, m.is_dir(),
                            stat.S_IFMT(m.external_attr >> 16) in {0, stat.S_IFREG, stat.S_IFDIR}
                            and (stat.S_IFMT(m.external_attr >> 16) != stat.S_IFDIR or m.is_dir())
                            and not m.extra and not (m.flag_bits & 1), m.file_size) for m in archive.infolist()]
        if len(members) > MAX_MEMBERS or sum(m[3] for m in members) > MAX_BYTES:
            return ['archive exceeds runtime size/member bounds']
        roots = {n.split('/')[0] for n, _, _, _ in members}
        prefix = ''
        if kind == 'sdist':
            if len(roots) != 1 or not re.fullmatch('buddie-' + VERSION, next(iter(roots), '')):
                return ['sdist must have exactly one versioned buddie root']
            prefix = next(iter(roots))
        elif kind == 'wheel':
            metadata = {n.split('/')[0] for n, _, _, _ in members if '.dist-info/' in n}
            if len(metadata) != 1 or not re.fullmatch('buddie-' + VERSION + r'\.dist-info',
                                                     next(iter(metadata), '')):
                return ['wheel must have exactly one versioned buddie metadata directory']
            prefix = next(iter(metadata))
        allowed, required = policy(kind, prefix)
        directories = {p.rsplit('/', i)[0] for p in allowed for i in range(1, p.count('/') + 1)}
        if kind == 'sdist':
            directories.add('')  # the single sdist root
        seen, components, present = set(), {}, set()
        for original, directory, regular, size in members:
            name = original[:-1] if directory and original.endswith('/') else original
            if unsafe(name):
                errors.append(f'unsafe path: {original!r}')
                continue
            if name.casefold() in seen:
                errors.append(f'duplicate path: {original}')
            seen.add(name.casefold())
            parts = name.split('/')
            for i in range(1, len(parts) + 1):
                component = '/'.join(parts[:i])
                folded = component.casefold()
                node_type = 'directory' if directory or i < len(parts) else 'file'
                if folded in components and components[folded] != (component, node_type):
                    errors.append(f'path component collision: {original}')
                components[folded] = component, node_type
            if not regular:
                errors.append(f'non-regular member: {original}')
                continue
            if size > MAX_FILE or (directory and size):
                errors.append(f'member exceeds runtime size bounds: {original}')
            if kind == 'sdist':
                name = name[len(prefix):].removeprefix('/')
            if directory:
                if kind == 'plugin' or name not in directories:
                    errors.append(f'unexpected directory: {original}')
            elif name not in allowed:
                errors.append(f'unexpected member: {original}')
            else:
                present.add(name)
        errors.extend(f'missing required {p}' for p in sorted(required - present))
        if kind != 'sdist' and not errors:
            # Check local headers and CRCs too: approved central-directory paths alone do not
            # prove every ZIP reader will see the same paths. Bounds were checked before reading.
            verify_zip_streams(path)
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile, OverflowError,
            RuntimeError, NotImplementedError, EOFError, zlib.error) as error:
        errors.append(f'unreadable archive: {error}')
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archives', nargs='+', type=Path)
    args = parser.parse_args()
    failed = False
    for path in args.archives:
        errors = problems(path)
        for error in errors:
            print(f'{path.name}: {error}', file=sys.stderr)
        if not errors:
            print(f'{path.name}: runtime file selection OK')
        failed |= bool(errors)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
