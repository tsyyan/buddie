"""The release candidate's record (docs/release.md): which commit its files were built from, their sizes and SHA-256,
and the check that PyPI serves exactly those files (the GitHub Release: release_publish.py).

    python scripts/release_manifest.py write DIR --version V --commit SHA [--ref REF] [--repository O/R] [--run-id N]
    python scripts/release_manifest.py verify DIR --version V --commit SHA
    python scripts/release_manifest.py pypi DIR PYPI_JSON        # PyPI's /pypi/buddie/V/json against the record

DIR holds `dist/` (the wheel and the sdist), `bundle/` (the Claude Desktop bundle) and `plugin/` (the compact Claude
Code plugin and its manifest, scripts/plugin_package.py); `write` adds `release-manifest.json` and `SHA256SUMS` (the
`sha256sum -c` format) to it. Besides each file's bytes, `verify` checks that the plugin's own manifest names the
candidate's commit and version and the recorded ZIP by size and SHA-256, so a plugin built from another commit, or
a ZIP swapped with its manifest, is refused even when every file hashes as recorded. Exit 0 when everything agrees, 1 with
each disagreement on stderr. Standard library only: it runs before anything is installed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SCHEMA = "buddie-release-candidate-v1"
MANIFEST = "release-manifest.json"
SUMS = "SHA256SUMS"
NAME = "buddie"
SHA = re.compile(r"^[0-9a-f]{40}$")


def expected(version: str) -> dict[str, str]:
    """Each file a candidate of `version` consists of, by its path in DIR, and its kind."""
    return {f"dist/{NAME}-{version}-py3-none-any.whl": "wheel", f"dist/{NAME}-{version}.tar.gz": "sdist",
            f"bundle/{NAME}-{version}.mcpb": "mcpb", f"plugin/{NAME}-plugin-{version}.zip": "plugin",
            f"plugin/{PLUGIN_MANIFEST}": "plugin-manifest"}


PLUGIN_SCHEMA = "buddie-plugin-package-v1"
PLUGIN_MANIFEST = "plugin-manifest.json"
KINDS = ("dist", "bundle", "plugin")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _present(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for d in KINDS if (root / d).is_dir()
            for p in (root / d).iterdir() if p.is_file()}


def write(root: Path, version: str, commit: str, ref: str = "", repository: str = "", run_id: str = "") -> list[str]:
    problems = _inputs(version, commit)
    want = expected(version)
    present = _present(root)
    problems += [f"missing {p}" for p in sorted(set(want) - present)]
    problems += [f"unexpected {p}" for p in sorted(present - set(want))]
    if problems:
        return problems
    files = [{"path": p, "kind": k, "size": (root / p).stat().st_size, "sha256": _sha256(root / p)}
             for p, k in want.items()]
    record = {"schema": SCHEMA, "name": NAME, "version": version, "commit": commit, "ref": ref,
              "repository": repository, "run_id": run_id, "files": files}
    (root / MANIFEST).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    (root / SUMS).write_text("".join(f"{f['sha256']}  {f['path']}\n" for f in files), encoding="utf-8",
                             newline="\n")
    return []


def _inputs(version: str, commit: str) -> list[str]:
    problems = []
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        problems.append(f"version {version!r} is not X.Y.Z")
    if not SHA.match(commit):
        problems.append(f"commit {commit!r} is not a full commit id")
    return problems


def load(root: Path) -> dict:
    return json.loads((root / MANIFEST).read_text(encoding="utf-8"))


def verify(root: Path, version: str, commit: str) -> list[str]:
    """The record is for `version` built from `commit`, and DIR holds exactly its files, byte for byte."""
    problems = _inputs(version, commit)
    try:
        record = load(root)
    except (OSError, ValueError) as error:
        return problems + [f"{MANIFEST}: {error}"]
    if record.get("schema") != SCHEMA:
        problems.append(f"schema {record.get('schema')!r}, expected {SCHEMA}")
    if record.get("version") != version:
        problems.append(f"the candidate is version {record.get('version')!r}, not {version}")
    if record.get("commit") != commit:
        problems.append(f"the candidate was built from {record.get('commit')!r}, not {commit}")
    files = {f.get("path"): f for f in record.get("files", [])}
    if set(files) != set(expected(version)):
        problems.append(f"the record lists {sorted(files)}, expected {sorted(expected(version))}")
    for path, f in sorted(files.items()):
        p = root / str(path)
        if not p.is_file():
            problems.append(f"missing {path}")
        elif p.stat().st_size != f.get("size") or _sha256(p) != f.get("sha256"):
            problems.append(f"{path} is not the file the candidate recorded")
    problems += [f"unexpected {p}" for p in sorted(_present(root) - set(files))]
    if not problems:
        problems += plugin_binding(root, version, commit, files)
    try:
        sums = (root / SUMS).read_text(encoding="utf-8")
    except OSError as error:
        problems.append(f"{SUMS}: {error}")
    else:
        if sums != "".join(f"{f.get('sha256')}  {f.get('path')}\n" for f in record.get("files", [])):
            problems.append(f"{SUMS} disagrees with {MANIFEST}")
    return problems


def plugin_binding(root: Path, version: str, commit: str, files: dict) -> list[str]:
    """The plugin manifest is the builder's, for this commit and version, and names the recorded ZIP exactly."""
    zip_path, man_path = f"plugin/{NAME}-plugin-{version}.zip", f"plugin/{PLUGIN_MANIFEST}"
    try:
        plugin = json.loads((root / man_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [f"{man_path}: {error}"]
    package = plugin.get("package") or {}
    checks = [
        (plugin.get("schema") == PLUGIN_SCHEMA, f"{man_path} is not a {PLUGIN_SCHEMA} manifest"),
        (plugin.get("version") == version, f"the plugin is version {plugin.get('version')!r}, not {version}"),
        (plugin.get("commit") == commit, f"the plugin was built from {plugin.get('commit')!r}, not {commit}"),
        (package.get("path") == Path(zip_path).name, f"the plugin manifest names {package.get('path')!r}"),
        ((package.get("size"), package.get("sha256")) == (files[zip_path].get("size"), files[zip_path].get("sha256")),
         "the plugin manifest does not name the recorded ZIP (size, sha256)"),
    ]
    return [why for ok, why in checks if not ok]


def pypi(root: Path, release: dict) -> list[str]:
    """PyPI's files for the version (its JSON API's `urls`) are the candidate's wheel and sdist, by SHA-256."""
    want = {Path(f["path"]).name: f["sha256"] for f in load(root)["files"] if f["kind"] in ("wheel", "sdist")}
    got = {u.get("filename"): (u.get("digests") or {}).get("sha256") for u in release.get("urls", [])}
    problems = [f"PyPI has no {n}" for n in sorted(set(want) - set(got))]
    problems += [f"PyPI has {n}, which the candidate does not" for n in sorted(set(got) - set(want))]
    problems += [f"PyPI's {n} is not the candidate's (sha256 {got[n]})" for n in sorted(set(want) & set(got))
                 if got[n] != want[n]]
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("write", "verify"):
        p = sub.add_parser(name)
        p.add_argument("dir", type=Path)
        p.add_argument("--version", required=True)
        p.add_argument("--commit", required=True)
        if name == "write":
            for opt in ("--ref", "--repository", "--run-id"):
                p.add_argument(opt, default="")
    for name in ("pypi",):
        p = sub.add_parser(name)
        p.add_argument("dir", type=Path)
        p.add_argument("json", type=Path)
    args = parser.parse_args(argv)
    if args.command == "write":
        problems = write(args.dir, args.version, args.commit, args.ref, args.repository, args.run_id)
    elif args.command == "verify":
        problems = verify(args.dir, args.version, args.commit)
    else:
        problems = pypi(args.dir, json.loads(args.json.read_text(encoding="utf-8")))
    for problem in problems:
        print(f"release_manifest: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
