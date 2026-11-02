"""Point a catalog's buddie entry at a released version: `buddie@X.Y.Z` (the uvx pin) and `/vX.Y.Z/` (links into the
tagged repository), nothing else. Used by .github/workflows/catalogs.yml on the forks behind the Cline and Kilo PRs.

    python scripts/catalog_bump.py FILE VERSION        # rewrites FILE; prints what changed
    python scripts/catalog_bump.py FILE VERSION --check

Exit 0: the file now names VERSION (changed, or already so). Exit 1: it names no buddie version at all, or a version
newer than VERSION (never downgraded). Exit 2: usage.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

VERSION = re.compile(r"^\d+\.\d+\.\d+$")
PIN = re.compile(r"(?<=buddie@)(\d+\.\d+\.\d+)\b")
TAG = re.compile(r"(?<=/v)(\d+\.\d+\.\d+)(?=/)")
CATALOGS = {  # fork, branch of the open PR, upstream, file in it
    "cline": ("tsyyan/marketplace", "add-buddie-mcp", "cline/marketplace", "registry/mcps/buddie/entry.json"),
    "kilo": ("tsyyan/kilo-marketplace", "add-buddie-mcp", "Kilo-Org/kilo-marketplace", "mcps/buddie/MCP.yaml"),
}


def _key(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def bump(text: str, version: str) -> tuple[str, list[str]]:
    """(new text, the versions it named). ValueError when it names none, or one newer than `version`."""
    found = sorted({m for rx in (PIN, TAG) for m in rx.findall(text)}, key=_key)
    if not found:
        raise ValueError("no buddie@X.Y.Z or /vX.Y.Z/ in the file")
    if _key(found[-1]) > _key(version):
        raise ValueError(f"the file names {found[-1]}, newer than {version}: not downgraded")
    return TAG.sub(version, PIN.sub(version, text)), found


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    check = "--check" in args
    args = [a for a in args if a != "--check"]
    if len(args) != 2 or not VERSION.match(args[1]):
        print(__doc__.strip().splitlines()[3], file=sys.stderr)
        return 2
    path, version = Path(args[0]), args[1]
    text = path.read_text(encoding="utf-8")
    try:
        new, found = bump(text, version)
    except ValueError as error:
        print(f"{path}: {error}", file=sys.stderr)
        return 1
    if new == text:
        print(f"{path}: already {version}")
        return 0
    if check:
        print(f"{path}: names {', '.join(found)}, not {version}")
        return 1
    path.write_text(new, encoding="utf-8")
    print(f"{path}: {', '.join(found)} -> {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
