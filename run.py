"""Launcher for the plugin and the Claude Desktop bundle: runs buddie from a clone or a plugin cache without pip
install (buddie has no dependencies; its quote module is buddie/verbatim)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from buddie.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
