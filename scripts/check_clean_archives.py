"""Install each checked wheel/sdist into its own clean venv, then smoke outside the checkout."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import venv
from pathlib import Path

from check_runtime_archive import problems

ROOT = Path(__file__).resolve().parents[1]


def main(directory: Path) -> None:
    archives = sorted(p for p in directory.iterdir() if p.name.endswith(('.whl', '.tar.gz')))
    if len(archives) != 2 or sum(p.suffix == '.whl' for p in archives) != 1:
        raise ValueError('expected exactly one wheel and one sdist')
    for archive in archives:
        archive = archive.resolve()
        errors = problems(archive)
        if errors:
            raise ValueError('; '.join(errors))
    for archive in archives:
        archive = archive.resolve()
        with tempfile.TemporaryDirectory(prefix='buddie-clean-') as tmp:
            target = Path(tmp) / 'venv'
            venv.EnvBuilder(with_pip=True).create(target)
            python = target / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
            subprocess.run([str(python), '-m', 'pip', 'install', '--no-deps', str(archive)],
                           cwd=tmp, check=True, stdin=subprocess.DEVNULL)
            # Take the expected version from the artifact filename, never the development checkout.
            version = archive.name.removeprefix('buddie-').removesuffix('.tar.gz').split('-')[0]
            subprocess.run([sys.executable, str(ROOT / 'scripts/smoke_install.py'), str(python), version],
                           cwd=tmp, check=True, stdin=subprocess.DEVNULL)


if __name__ == '__main__':
    main(Path(sys.argv[1]))
