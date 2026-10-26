"""Check built PyPI metadata after the runtime archive gate, without extraction or installation."""
from __future__ import annotations

import argparse
from email.parser import BytesParser
import tarfile
import tomllib
import zipfile
from pathlib import Path

import release_notes as rn

MAX_METADATA = 2 * 1024 * 1024


def problems(path: Path, record: dict, project: dict) -> list[str]:
    version = record['version']
    try:
        if path.name.endswith('.whl'):
            with zipfile.ZipFile(path) as archive:
                entry = archive.getinfo(f'buddie-{version}.dist-info/METADATA')
                with archive.open(entry) as stream:
                    data = stream.read(MAX_METADATA + 1)
        elif path.name.endswith('.tar.gz'):
            with tarfile.open(path, 'r:gz') as archive:
                entry = archive.getmember(f'buddie-{version}/PKG-INFO')
                if not entry.isfile():
                    return ['package metadata is not a regular file']
                with archive.extractfile(entry) as stream:
                    data = stream.read(MAX_METADATA + 1)
        else:
            return ['unsupported public package format']
        if len(data) > MAX_METADATA:
            return ['package metadata exceeds limit']
        message = BytesParser().parsebytes(data)
        want = {'Name': project['name'], 'Version': version, 'Summary': project['description'],
                'Requires-Python': project['requires-python'], 'License-Expression': project['license']}
        errors = [f'{key} differs from project metadata' for key, value in want.items()
                  if message.get_all(key) != [value]]
        if project['version'] != version:
            errors.append('project version differs from release record')
        urls = {}
        for row in message.get_all('Project-URL', []):
            key, value = row.split(',', 1)
            if key.strip() in urls:
                errors.append('duplicate project URL')
            urls[key.strip()] = value.strip()
        if urls != project['urls']:
            errors.append('project links differ from project metadata')
        if sorted(message.get_all('License-File', [])) != sorted(project['license-files']):
            errors.append('legal/privacy metadata differs from project metadata')
        body = (message.get_payload(decode=True) or b'').decode('utf-8')
        if body.strip() != rn.render_package_readme(record, 'pypi').strip():
            errors.append('package description differs from public release record')
        return errors
    except (OSError, ValueError, KeyError, tarfile.TarError, zipfile.BadZipFile) as error:
        return [f'unreadable public package metadata: {error}']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--record', type=Path, required=True)
    parser.add_argument('--project', type=Path, default=Path('pyproject.toml'))
    parser.add_argument('archives', nargs='+', type=Path)
    args = parser.parse_args()
    record = rn.load_release(args.record, args.version)
    project = tomllib.loads(args.project.read_text(encoding='utf-8'))['project']
    failed = False
    for path in args.archives:
        errors = problems(path, record, project)
        failed |= bool(errors)
        print(f'{path.name}: ' + ('; '.join(errors) if errors else 'public description and metadata OK'))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
