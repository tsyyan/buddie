"""Inventory a committed Claude plugin root; no working-tree files, filters or downloads.

python scripts/plugin_inventory.py --ref HEAD > inventory.json
--check exits 1 for reproduced file-inspection holds. This is not Anthropic's scanner.
The Directory source is the repository root, so every tracked file is reported, not an invented allowlist.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
from collections import Counter
from pathlib import Path, PurePosixPath


def category(path: str) -> str:
    if path == "run.py" or path == ".mcp.json" or path == ".claude-plugin/plugin.json" or path.startswith(
            ("buddie/", "hooks/", "skills/", "commands/")):
        return "runtime-required"
    if path.startswith(("results/", "experiments/")) or path == "PROVENANCE.json":
        return "experimental-results"
    if path.startswith(("tests/", "evals/")):
        return "tests"
    if path.startswith("assets/"):
        return "assets"
    if path.startswith(("docs/", "examples/")) or path in (
            "README.md", "PRIVACY.md", "LICENSE", "NOTICE", "CHANGELOG.md", "CONTRIBUTING.md", "CITATION.cff"):
        return "documentation"
    return "development-only"


def inventory(repo: Path, ref: str) -> dict:
    def git(*args, input=b""):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, input=input).stdout
    sha = git("rev-parse", "--verify", ref + "^{commit}").decode().strip()
    entries = []
    for raw in git("ls-tree", "-rz", "--full-tree", sha).split(b"\0"):
        if not raw:
            continue
        meta, path = raw.split(b"\t", 1)
        mode, kind, oid = meta.decode().split()
        entries.append((path.decode("utf-8"), mode, kind, oid))
    # Read exact Git blob bytes in one process. Git checkout conversion, local .git files and caches are irrelevant.
    blobs = [e for e in entries if e[2] == "blob"]
    stream = io.BytesIO(git("cat-file", "--batch", input="".join(e[3] + "\n" for e in blobs).encode()))
    bodies = {}
    for path, _, _, _ in blobs:
        header = stream.readline().decode().split()
        bodies[path] = stream.read(int(header[2]))
        assert stream.read(1) == b"\n"
    files, holds = [], []
    images_fonts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".woff", ".woff2", ".ttf", ".otf"}
    for path, mode, kind, _ in sorted(entries):
        body = bodies.get(path, b"")
        files.append({"path": path, "category": category(path), "bytes": len(body), "mode": mode,
                      "sha256": hashlib.sha256(body).hexdigest() if kind == "blob" else None})
        if mode not in ("100644", "100755"):
            holds.append({"path": path, "reason": "not a regular file"})
        if PurePosixPath(path).suffix.lower() not in images_fonts:
            if len(body) > 256 * 1024:
                holds.append({"path": path, "reason": "non-image/font over 256 KiB"})
            try:
                body.decode("utf-8")
                if b"\0" in body:
                    raise ValueError()
            except (UnicodeDecodeError, ValueError):
                holds.append({"path": path, "reason": "non-text file outside image/font extensions"})
    if len(files) > 512:
        holds.append({"path": ".", "reason": "over 512 files"})
    return {"commit": sha, "plugin_root": ".", "surface": "all committed files (Claude Code git source / Directory root)",
            "file_count": len(files), "total_bytes": sum(f["bytes"] for f in files),
            "categories": dict(sorted(Counter(f["category"] for f in files).items())),
            "inspection_holds": holds, "files": files}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = inventory(args.repo, args.ref)
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return int(args.check and bool(result["inspection_holds"]))


if __name__ == "__main__":
    raise SystemExit(main())
