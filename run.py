"""Launcher for the plugin: works from a lab checkout or a plugin cache without pip install.

verbatim is found as an installed package, else at $BUDDIE_VERBATIM, else in vendor/ (a symlink to
components/verbatim/verbatim, followed when the plugin is copied), else next to this component in lab.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
try:
    import verbatim  # noqa: F401
except ImportError:
    for candidate in (os.environ.get("BUDDIE_VERBATIM"), ROOT / "vendor", ROOT.parent / "verbatim"):
        if candidate and (Path(candidate) / "verbatim" / "__init__.py").is_file():
            sys.path.insert(0, str(candidate))
            break

from buddie.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
