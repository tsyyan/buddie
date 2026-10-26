"""Fast release payload budgets, executed *after* release_manifest verify.

No unpacking, network requests, model calls or builds. This is an early size
regression gate, NOT a substitute for the archive/security validation that
precedes it. Budget changes require code review.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Deliberate initial ceilings: several times the actual v2.0.1 wheel/sdist/MCPB
# sizes (266231 / 268422 / 333422 bytes); the compact Claude ZIP measured
# 904599 bytes in its reproducible v2.0.1 packaging review.
# These are compressed DISTRIBUTION sizes, not extracted payload budgets.
MIB = 1024 * 1024
MAX_SIZE = {"wheel": 1 * MIB, "sdist": 1 * MIB, "mcpb": 2 * MIB, "plugin": 2 * MIB}
MAX_TOTAL = 6 * MIB


def check(files: list[dict]) -> list[str]:
    problems: list[str] = []
    found: dict[str, dict] = {}
    for item in files:
        if not isinstance(item, dict):
            problems.append("malformed manifest file record")
            continue
        kind = item.get("kind")
        if kind not in MAX_SIZE:
            continue  # plugin-manifest.json is a control file, not an archive
        if kind in found:
            problems.append(f"duplicate {kind} artifact")
        found[kind] = item

    for kind in MAX_SIZE:
        if kind not in found:
            problems.append(f"missing {kind} artifact")
    total = 0
    for kind, item in sorted(found.items()):
        n = item.get("size")
        if type(n) is not int or n < 0:
            problems.append(f"{kind}: invalid size {n!r}")
            continue
        total += n
        if n > MAX_SIZE[kind]:
            problems.append(f"{kind}: {n} bytes exceeds {MAX_SIZE[kind]} byte budget")
    if total > MAX_TOTAL:
        problems.append(f"distribution payload: {total} bytes exceeds {MAX_TOTAL} byte budget")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check compressed release artifact size budgets")
    parser.add_argument("root", type=Path, help="Verified release candidate directory")
    args = parser.parse_args(argv)
    try:
        manifest = json.loads((args.root / "release-manifest.json").read_text(encoding="utf-8"))
        files = manifest["files"]
        if not isinstance(files, list):
            raise ValueError("files is not an array")
    except (OSError, KeyError, ValueError, TypeError) as exc:
        print(f"release payload gate: invalid manifest: {exc}", file=sys.stderr)
        return 1
    problems = check(files)
    if problems:
        for msg in problems:
            print(f"release payload gate: {msg}", file=sys.stderr)
        return 1
    for kind in MAX_SIZE:
        size = next(f["size"] for f in files if f.get("kind") == kind)
        print(f"{kind}: {size:,} / {MAX_SIZE[kind]:,} bytes")
    print("release payload budgets: PASS (manifest integrity checked separately)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
