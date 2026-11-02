"""One package for every client with hooks and skills (plugin_package.py builder 5, the release's plugin), as a ZIP or
as a directory tree: each client's own manifest and hook file, all at one root.

  client       reads                                   hooks
  Claude Code  .claude-plugin/plugin.json              hooks/claude-code.json (named by plugin.json "hooks")
  Codex        .codex-plugin/plugin.json,              hooks/codex.json (named by its plugin.json)
               .agents/plugins/marketplace.json
  Gemini CLI   gemini-extension.json, GEMINI.md        none: Gemini reads hooks/hooks.json, so the package has none
  Copilot CLI  .github/plugin/plugin.json              none yet (its hook events are not tested here)

Why no hooks/hooks.json: Claude Code, Gemini CLI and Copilot CLI each read a file at that path, in three formats, and
`SessionStart` exists in two of them. Each client's hooks are named by its own manifest instead.

Every version in every manifest is the package's (buddie/__init__.py), written here: the client manifests under
packaging/clients/ carry 0.0.0 and are never released as they are.

    python scripts/dist_package.py build --ref REF --out DIR     # DIR/buddie-dist-X.Y.Z.zip + dist-manifest.json
    python scripts/dist_package.py tree --ref REF DIR            # the same files as a directory (dist-next)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plugin_package as pp  # noqa: E402

# The transform lives in plugin_package.py since builder 5: the release's plugin is this package.
SOURCES = pp.CLIENTS
VERSIONED = (".claude-plugin/plugin.json", *pp.VERSIONED)


def build(repo: Path, ref: str) -> tuple[bytes, dict, dict[str, bytes]]:
    return pp.build(repo, ref)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--ref", default="HEAD")
    b.add_argument("--repo", default=".")
    b.add_argument("--out", required=True)
    t = sub.add_parser("tree")
    t.add_argument("--ref", default="HEAD")
    t.add_argument("--repo", default=".")
    t.add_argument("directory")
    a = ap.parse_args(argv)
    try:
        data, manifest, files = build(Path(a.repo), a.ref)
    except pp.PackageError as error:
        print(f"dist_package: {error}", file=sys.stderr)
        return 1
    if a.cmd == "build":
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        pp.write(out, data, manifest)
    else:
        root = Path(a.directory)
        for path, content in files.items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_bytes(content)
    print(json.dumps({k: manifest[k] for k in ("version", "commit", "file_count", "total_bytes")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
