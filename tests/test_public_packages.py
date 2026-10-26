"""Core metadata and public descriptions are checked in the built wheel/sdist bytes."""
import copy
import io
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import check_public_packages as check
import release_notes as rn

PROJECT = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']
RECORD = rn.load_release(ROOT / 'releases/2.0.2.json', '2.0.2')


def package(tmp_path, kind, change=None):
    headers = {'Name': PROJECT['name'], 'Version': RECORD['version'], 'Summary': PROJECT['description'],
               'Requires-Python': PROJECT['requires-python'], 'License-Expression': PROJECT['license']}
    urls = dict(PROJECT['urls'])
    licenses = list(PROJECT['license-files'])
    body = rn.render_package_readme(RECORD, 'pypi')
    if change == 'research': body = 'Research-only internal results.'
    elif change == 'version': headers['Version'] = '2.0.1'
    elif change == 'license': licenses.remove('PRIVACY.md')
    elif change == 'url': urls.pop('Repository')
    elif change == 'summary': headers['Summary'] = 'Unexpected metadata'
    raw = ('\n'.join(f'{k}: {v}' for k, v in headers.items()) + '\n' +
           ''.join(f'Project-URL: {k}, {v}\n' for k, v in urls.items()) +
           ''.join(f'License-File: {v}\n' for v in licenses) + '\n' + body).encode('utf-8')
    if kind == 'wheel':
        path = tmp_path / 'buddie-2.0.2-py3-none-any.whl'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('buddie-2.0.2.dist-info/METADATA', raw)
    else:
        path = tmp_path / 'buddie-2.0.2.tar.gz'
        with tarfile.open(path, 'w:gz') as archive:
            member = tarfile.TarInfo('buddie-2.0.2/PKG-INFO')
            member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))
    return path


@pytest.mark.parametrize('kind', ['wheel', 'sdist'])
def test_built_metadata_keeps_public_readme_and_project_fields(tmp_path, kind):
    assert check.problems(package(tmp_path, kind), RECORD, PROJECT) == []


@pytest.mark.parametrize('kind', ['wheel', 'sdist'])
@pytest.mark.parametrize('change', ['research', 'version', 'license', 'url', 'summary'])
def test_changed_public_description_or_metadata_is_refused(tmp_path, kind, change):
    assert check.problems(package(tmp_path, kind, change), RECORD, PROJECT)


def test_project_version_must_match_release_record(tmp_path):
    project = copy.deepcopy(PROJECT)
    project['version'] = '2.0.1'
    assert check.problems(package(tmp_path, 'wheel'), RECORD, project)
