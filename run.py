"""Launcher for the plugin: works from a clone or a plugin cache without pip install.

verbatim is found as an installed package, else next to this file (this repository), else at $BUDDIE_VERBATIM, else
in vendor/ or one level up (the layouts of the old lab checkout).
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
