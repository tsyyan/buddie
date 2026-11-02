"""One package for every client with hooks and skills: the compact Claude Code plugin (plugin_package.build, the
same audited selection and checks) plus each other client's own manifest and hook file, all at one root.

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
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plugin_package as pp  # noqa: E402

BUILDER = 1
SOURCES = {  # repository file at the commit -> its place in the package
    ".codex-plugin/plugin.json": ".codex-plugin/plugin.json",
    "integrations/codex/hooks.json": "hooks/codex.json",
    ".agents/plugins/marketplace.json": ".agents/plugins/marketplace.json",
    "packaging/clients/gemini/gemini-extension.json": "gemini-extension.json",
    "packaging/clients/gemini/GEMINI.md": "GEMINI.md",
    "packaging/clients/copilot/plugin.json": ".github/plugin/plugin.json",
}
VERSIONED = (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", "gemini-extension.json",
             ".github/plugin/plugin.json")
NO_FILE = ("hooks/hooks.json",)  # read by three clients in three formats: never in this package


def _json(data: bytes) -> dict:
    return json.loads(data.decode("utf-8"))


def _dump(obj: dict) -> bytes:
    return (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def build(repo: Path, ref: str) -> tuple[bytes, dict, dict[str, bytes]]:
    _, base, files = pp.build(repo, ref)
    version = base["version"]
    commit = base["commit"]
    entries = {p: (m, o) for p, m, o in pp.tracked(repo, commit)}
    missing = [p for p in SOURCES if p not in entries]
    if missing:
        raise pp.PackageError(f"missing at {commit[:12]}: {', '.join(missing)}")
    blobs = pp._blobs(repo, [(p, *entries[p]) for p in SOURCES])
    for source, destination in SOURCES.items():
        files[destination] = blobs[source]
    files["hooks/claude-code.json"] = files.pop("hooks/hooks.json")
    claude = _json(files[".claude-plugin/plugin.json"])
    claude["hooks"] = "./hooks/claude-code.json"
    files[".claude-plugin/plugin.json"] = _dump(claude)
    codex = _json(files[".codex-plugin/plugin.json"])
    codex["hooks"] = "./hooks/codex.json"
    files[".codex-plugin/plugin.json"] = _dump(codex)
    for path in VERSIONED:
        manifest = _json(files[path])
        manifest["version"] = version
        files[path] = _dump(manifest)
    problems = [f"{p} must not be in the package" for p in NO_FILE if p in files]
    problems += pp._content_problems(files)
    gem = _json(files["gemini-extension.json"])
    if gem.get("contextFileName") not in files:
        problems.append(f"gemini-extension.json names {gem.get('contextFileName')}, which the package lacks")
    if problems:
        raise pp.PackageError("; ".join(problems))
    data = pp.zip_bytes(files)
    manifest = {
        "schema": "https://github.com/tsyyan/buddie#dist-manifest-v1", "name": "buddie-dist", "version": version,
        "commit": commit, "tree": base["tree"], "builder": BUILDER, "plugin_builder": base["builder"],
        "sources": SOURCES, "clients": ["claude-code", "codex", "gemini-cli", "copilot-cli"],
        "files": [{"path": p, "size": len(files[p]), "sha256": hashlib.sha256(files[p]).hexdigest()}
                  for p in sorted(files)],
        "file_count": len(files), "total_bytes": sum(map(len, files.values())),
        "package": {"path": f"buddie-dist-{version}.zip", "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest()},
    }
    return data, manifest, files


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
        (out / manifest["package"]["path"]).write_bytes(data)
        (out / "dist-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    else:
        root = Path(a.directory)
        for path, content in files.items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_bytes(content)
    print(json.dumps({k: manifest[k] for k in ("version", "commit", "file_count", "total_bytes")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
