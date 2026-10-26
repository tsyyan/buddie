"""Adversarial archive checks exercise the CLI without extracting attacker paths."""
import io
import stat
import struct
import subprocess
import sys
import tarfile
import zipfile
import warnings
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/check_runtime_archive.py'
# A real source fixture; validity is tested separately from each malicious mutation.
RUNTIME = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / 'buddie').rglob('*.py'))
LEGAL = ['README.md', 'LICENSE', 'NOTICE', 'PRIVACY.md']
DIST = 'buddie-2.0.1.dist-info/'


def names(kind):
    if kind == 'wheel':
        return RUNTIME + [DIST + p for p in ['METADATA', 'WHEEL', 'entry_points.txt', 'top_level.txt',
                                            'RECORD', 'licenses/LICENSE', 'licenses/NOTICE', 'licenses/PRIVACY.md']]
    if kind == 'sdist':
        return RUNTIME + LEGAL + ['CHANGELOG.md', 'run.py', 'pyproject.toml', 'MANIFEST.in', 'PKG-INFO',
                                 'setup.cfg'] + ['buddie.egg-info/' + p for p in ['PKG-INFO', 'SOURCES.txt',
                                 'dependency_links.txt', 'entry_points.txt', 'requires.txt', 'top_level.txt']]
    if kind == 'mcpb':
        return RUNTIME + LEGAL + ['manifest.json', 'run.py', 'assets/icon.png']
    return RUNTIME + LEGAL + ['.claude-plugin/plugin.json', '.claude-plugin/marketplace.json', '.mcp.json',
                             'run.py', 'hooks/hooks.json', 'hooks/run.sh', 'assets/icon.png',
                             'skills/buddie/SKILL.md', 'skills/verbatim/SKILL.md',
                             'commands/check.md', 'commands/init.md', 'commands/status.md']


def write(tmp_path, kind, entries, special=None):
    suffix = {'wheel': '.whl', 'sdist': '.tar.gz', 'mcpb': '.mcpb', 'plugin': '.zip'}[kind]
    path = tmp_path / ('buddie-2.0.1' + suffix)
    if kind == 'sdist':
        with tarfile.open(path, 'w:gz') as archive:
            for name in entries:
                info = tarfile.TarInfo('buddie-2.0.1/' + name)
                if name.endswith('/'):
                    info.type = tarfile.DIRTYPE
                elif special and name == special[0]:
                    info.type = special[1]
                    info.linkname = 'buddie/__init__.py'
                else:
                    info.size = 1
                archive.addfile(info, io.BytesIO(b'x') if info.isfile() else None)
    else:
        with zipfile.ZipFile(path, 'w') as archive:
            for name in entries:
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = ((stat.S_IFDIR if name.endswith('/') else stat.S_IFREG) | 0o644) << 16
                if special and name == special[0]:
                    info.external_attr = special[1] << 16
                with warnings.catch_warnings():
                    warnings.filterwarnings('ignore', message='Duplicate name:')
                    archive.writestr(info, b'' if name.endswith('/') else b'x')
    return path


def check(path):
    return subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True)


@pytest.mark.parametrize('kind', ['wheel', 'sdist', 'mcpb', 'plugin'])
def test_approved_archives_and_required_files(tmp_path, kind):
    fixture = names(kind)
    result = check(write(tmp_path, kind, fixture))
    assert result.returncode == 0, result.stderr
    for missing in fixture:
        result = check(write(tmp_path, kind, [n for n in fixture if n != missing]))
        assert result.returncode == 1, (kind, missing, result.stdout, result.stderr)
        assert 'missing required' in result.stderr


@pytest.mark.parametrize('kind', ['wheel', 'sdist', 'mcpb', 'plugin'])
@pytest.mark.parametrize('extra', ['buddie/secret.py', 'buddie/verbatim/experiment.py', 'tests/test_x.py',
    'experiments/result.json', 'private/evidence.txt', 'unknown/', 'buddie/unapproved/',
    '../escape', '/absolute', 'C:/escape', 'buddie\\escape.py', 'buddie//mcp.py', './README.md',
    'buddie/../README.md', 'buddie/CON', 'buddie/file.', 'buddie/a:b', 'buddie/\x01bad',
    'BUDDIE/mcp.py', 'buddie/VERBATIM/other.py', 'README.md/child', 'buddie/mcp.py/child'])
def test_rejects_unapproved_and_unsafe_members(tmp_path, kind, extra):
    result = check(write(tmp_path, kind, names(kind) + [extra]))
    assert result.returncode == 1, (kind, extra, result.stdout, result.stderr)


@pytest.mark.parametrize('kind', ['wheel', 'sdist', 'mcpb', 'plugin'])
def test_rejects_duplicates_and_links(tmp_path, kind):
    fixture = names(kind)
    result = check(write(tmp_path, kind, fixture + ['buddie/mcp.py']))
    assert result.returncode == 1
    for mode in ([tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE] if kind == 'sdist'
                 else [stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o644]):
        result = check(write(tmp_path, kind, fixture, ('buddie/mcp.py', mode)))
        assert result.returncode == 1
        assert 'non-regular' in result.stderr


@pytest.mark.parametrize('kind', ['wheel', 'sdist', 'mcpb'])
def test_only_approved_parent_directories(tmp_path, kind):
    parents = ['buddie/', 'buddie/verbatim/']
    result = check(write(tmp_path, kind, names(kind) + parents))
    assert result.returncode == 0, result.stderr
    result = check(write(tmp_path, kind, names(kind) + ['BUDDIE/']))
    assert result.returncode == 1
    assert 'collision' in result.stderr


def test_corrupt_unsupported_and_multiple_sdist_roots(tmp_path):
    for name in ['bad.whl', 'bad.mcpb', 'bad.tar.gz', 'bad.rar']:
        path = tmp_path / name
        path.write_bytes(b'bad')
        assert check(path).returncode == 1
    path = write(tmp_path, 'sdist', names('sdist'))
    with tarfile.open(tmp_path / 'roots.tar.gz', 'w:gz') as archive:
        for name in ['buddie-2.0.1/README.md', 'buddie-2.0.2/LICENSE']:
            archive.addfile(tarfile.TarInfo(name))
    assert check(tmp_path / 'roots.tar.gz').returncode == 1



def test_clean_install_gate_refuses_unapproved_archives_before_install(tmp_path):
    write(tmp_path, 'wheel', names('wheel') + ['buddie/private.py'])
    write(tmp_path, 'sdist', names('sdist'))
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/check_clean_archives.py'), str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert 'unexpected member: buddie/private.py' in result.stderr
    assert 'Successfully installed' not in result.stdout



@pytest.mark.parametrize('extra', [b'\x0d\x00\x04\x00link', b'\x75\x78\x02\x00xx'])
def test_zip_refuses_unreviewed_extra_fields_that_can_encode_links(tmp_path, extra):
    path = tmp_path / 'test.mcpb'
    with zipfile.ZipFile(path, 'w') as archive:
        for name in names('mcpb'):
            info = zipfile.ZipInfo(name)
            if name == 'buddie/mcp.py':
                info.extra = extra
            archive.writestr(info, b'x')
    result = check(path)
    assert result.returncode == 1
    assert 'non-regular' in result.stderr


def test_archive_size_limits(tmp_path):
    path = write(tmp_path, 'mcpb', names('mcpb'))
    with zipfile.ZipFile(path, 'a') as archive:
        with pytest.warns(UserWarning, match='Duplicate name:'):
            archive.writestr('buddie/mcp.py', b'x' * (2 * 1024 * 1024 + 1))
    result = check(path)
    assert result.returncode == 1
    assert 'size bounds' in result.stderr


@pytest.mark.parametrize('kind', ['wheel', 'mcpb', 'plugin'])
def test_zip_local_header_paths_must_match_approved_directory(tmp_path, kind):
    path = write(tmp_path, kind, names(kind))
    original = b'buddie/__init__.py'
    alternate = b'../' + b'x' * (len(original) - 3)
    data = path.read_bytes()
    # Change only the first local filename, leaving the approved central-directory entry intact.
    assert data[:4] == b'PK\x03\x04'
    assert data[30:30 + len(original)] == original
    path.write_bytes(data[:30] + alternate + data[30 + len(original):])
    result = check(path)
    assert result.returncode == 1, result.stdout


def test_zip_payload_corruption_is_rejected_before_install(tmp_path):
    path = write(tmp_path, 'mcpb', names('mcpb'))
    data = bytearray(path.read_bytes())
    data[30 + len(b'buddie/__init__.py')] ^= 1
    path.write_bytes(data)
    assert check(path).returncode == 1


def test_zip_local_only_unix_extra_is_rejected(tmp_path):
    path = tmp_path / 'local-extra.mcpb'
    extra = b'\x0d\x00\x04\x00link'
    with zipfile.ZipFile(path, 'w') as archive:
        for index, name in enumerate(names('mcpb')):
            info = zipfile.ZipInfo(name)
            info.extra = extra if index == 0 else b''
            archive.writestr(info, b'x')
    data = bytearray(path.read_bytes())
    central = data.index(b'PK\x01\x02')
    filename_length, extra_length = struct.unpack_from('<HH', data, central + 28)
    assert extra_length == len(extra)
    extra_at = central + 46 + filename_length
    del data[extra_at:extra_at + extra_length]
    struct.pack_into('<H', data, central + 30, 0)
    end = data.rfind(b'PK\x05\x06')
    central_size = struct.unpack_from('<I', data, end + 12)[0]
    struct.pack_into('<I', data, end + 12, central_size - extra_length)
    path.write_bytes(data)
    with zipfile.ZipFile(path) as archive:
        assert archive.infolist()[0].extra == b''
        assert archive.testzip() is None  # otherwise valid ZIP; the extra exists only locally
    assert check(path).returncode == 1


def test_zip_understated_decompressed_size_is_rejected(tmp_path):
    path = tmp_path / 'understated.mcpb'
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for index, name in enumerate(names('mcpb')):
            archive.writestr(name, b'x' * (2 * 1024 * 1024 + 1) if index == 0 else b'x')
    data = bytearray(path.read_bytes())
    central = data.index(b'PK\x01\x02')
    struct.pack_into('<I', data, 14, zlib.crc32(b'x'))
    struct.pack_into('<I', data, 22, 1)
    struct.pack_into('<I', data, central + 16, zlib.crc32(b'x'))
    struct.pack_into('<I', data, central + 24, 1)
    path.write_bytes(data)
    with zipfile.ZipFile(path) as archive:
        assert archive.read(archive.infolist()[0]) == b'x'  # stdlib truncates the real stream
    assert check(path).returncode == 1


@pytest.mark.parametrize('compression', [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_zip_unaudited_compression_is_rejected(tmp_path, compression):
    path = tmp_path / 'compression.mcpb'
    with zipfile.ZipFile(path, 'w', compression=compression) as archive:
        for name in names('mcpb'):
            archive.writestr(name, b'x')
    assert check(path).returncode == 1


def test_zip_hidden_local_member_is_rejected(tmp_path):
    path = tmp_path / 'hidden.mcpb'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('../hidden-evidence.txt', b'private')
        for name in names('mcpb'):
            archive.writestr(name, b'x')
    data = bytearray(path.read_bytes())
    central = data.index(b'PK\x01\x02')
    filename_length, extra_length, comment_length = struct.unpack_from('<HHH', data, central + 28)
    removed = 46 + filename_length + extra_length + comment_length
    del data[central:central + removed]
    end = data.rfind(b'PK\x05\x06')
    count = struct.unpack_from('<H', data, end + 8)[0] - 1
    struct.pack_into('<HH', data, end + 8, count, count)
    size = struct.unpack_from('<I', data, end + 12)[0]
    struct.pack_into('<I', data, end + 12, size - removed)
    path.write_bytes(data)
    with zipfile.ZipFile(path) as archive:
        assert '../hidden-evidence.txt' not in archive.namelist()
        assert archive.testzip() is None
    assert check(path).returncode == 1


def test_zip_trailing_payload_is_rejected(tmp_path):
    path = write(tmp_path, 'mcpb', names('mcpb'))
    path.write_bytes(path.read_bytes() + b'private trailing payload')
    assert check(path).returncode == 1


def test_zip_streaming_data_descriptors_remain_supported(tmp_path):
    class Streaming(io.BytesIO):
        def seek(self, *args):
            raise io.UnsupportedOperation('stream')
    stream = Streaming()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names('mcpb'):
            archive.writestr(name, b'x')
    path = tmp_path / 'streaming.mcpb'
    path.write_bytes(stream.getvalue())
    assert check(path).returncode == 0
