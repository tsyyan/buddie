"""The compact Claude Code plugin (docs/release.md, "Compact plugin"): the runtime files of one commit, selected by an
audited allowlist, as deterministic ZIP bytes and a manifest of what they hold.

    python scripts/plugin_package.py build --ref SHA --out DIR [--tree DIR]   # DIR gets the ZIP and its manifest
    python scripts/plugin_package.py verify DIR [--ref SHA]                  # the ZIP is exactly its manifest
    python scripts/plugin_package.py unpack ZIP DIR                          # the plugin tree, after verify

The source is the repository's own commit and nothing else. Files are read as Git blobs (`git cat-file`), never from
the working tree, so line-ending conversion, untracked or ignored files, caches and local edits cannot enter. There
is no second source tree: the package is derived from the commit each time, and a rebuild from the same commit gives
the same bytes (`verify --ref`).

Selection (ALLOW): exact paths, and directories whose every tracked file must match the directory's rule. A tracked
file in an allowed directory that matches no rule fails the build instead of being left out, so a new file there is
reviewed, not silently shipped or dropped. Everything else (tests, experiments, results, docs, scripts, CI, examples,
evals, integrations, private evidence) is outside the allowlist and never read.

Refused: symlinks, submodules and other non-regular Git modes; missing required files; a file over its size limit
(256 KiB for text, 1 MiB for the icon); text that is not UTF-8 or holds NUL; paths that are not plain relative POSIX
paths or collide case-insensitively; more than MAX_FILES files or MAX_BYTES bytes; a version in plugin.json that is not
buddie.__version__; a manifest reference (icon, MCP launcher, hook launcher) to a file the package lacks.

The ZIP: entries in path order, STORED (no compression: deflate output depends on the zlib build, stored bytes do
not), timestamp 1980-01-01 00:00:00, Unix mode 0644 for every file, no directory entries, no extra fields, no comment.
Standard library only.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import io
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "buddie-plugin-package-v1"
MANIFEST = "plugin-manifest.json"
NAME = "buddie"
BUILDER = 4  # 3: canonical Discovery blobs relocated; 4: the package's marketplace comes from packaging/plugin
DISCOVERY = {
    "integrations/agensi/SKILL.md": "skills/buddie-discovery/SKILL.md",
    "integrations/agensi/references/reporting.md": "skills/buddie-discovery/references/reporting.md",
}
# The repository root's .claude-plugin/marketplace.json is the public channel: it points Claude Code at the released
# plugin on `plugin-stable`. The package root is its own marketplace (source "./"), so the package carries the one
# from packaging/plugin instead, relocated byte for byte; the root's file never enters the package.
MARKETPLACE = {"packaging/plugin/marketplace.json": ".claude-plugin/marketplace.json"}
RELOCATIONS = {**DISCOVERY, **MARKETPLACE}
CHANNEL = ".claude-plugin/marketplace.json"  # the repository channel, outside the package

# the audited runtime: what the Claude Code plugin loads, starts or shows, and the files a reader of it needs
EXACT = (
    ".claude-plugin/plugin.json",      # plugin manifest and Directory listing fields
    *MARKETPLACE,                      # makes the package root installable as a marketplace (source "./")
    ".mcp.json",                       # the local MCP server
    "run.py",                          # the launcher (MCP and hooks)
    "hooks/hooks.json", "hooks/run.sh",
    "assets/icon.png",                 # plugin.json "icon"
    "README.md", "LICENSE", "NOTICE", "PRIVACY.md",
    *DISCOVERY,
)
DIRECTORIES = {                        # directory -> the patterns its tracked files must match (relative names)
    "buddie": ("*.py",),
    "buddie/verbatim": ("*.py",),
    "skills": ("*/SKILL.md",),
    "commands": ("*.md",),
}
REQUIRED = EXACT + ("buddie/__init__.py", "buddie/cli.py", "buddie/mcp.py", "buddie/hook.py",
                    "skills/buddie/SKILL.md", "skills/verbatim/SKILL.md")
NEVER = ("tests/", "experiments/", "results/", "evals/", "docs/", "scripts/", ".github/", "examples/",
         "integrations/", ".codex-plugin/", "PROVENANCE.json")  # asserted absent from every package
IMAGES = {".png"}
MAX_TEXT, MAX_IMAGE = 256 * 1024, 1024 * 1024
MAX_FILES, MAX_BYTES = 128, 2 * 1024 * 1024
EPOCH = (1980, 1, 1, 0, 0, 0)
PLAIN = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$")


class PackageError(ValueError):
    """The commit cannot be packaged as it is, or a package is not what its manifest says."""


def _git(repo: Path, *args: str, data: bytes = b"") -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, input=data).stdout


def tracked(repo: Path, commit: str) -> list[tuple[str, str, str]]:
    """(path, mode, blob id) of every entry of `commit`'s tree."""
    out = []
    for raw in _git(repo, "ls-tree", "-rz", "--full-tree", commit).split(b"\0"):
        if raw:
            meta, path = raw.split(b"\t", 1)
            mode, _kind, oid = meta.decode().split()
            out.append((path.decode("utf-8"), mode, oid))
    return out


# runtime roots: every tracked file under one is either selected or refuses the build (assets/ is not one: only
# its icon is runtime, the README's branding images stay in the repository)
STRICT_ROOTS = ("buddie/", "skills/", "commands/", "hooks/", ".claude-plugin/")


def _rule(path: str) -> str | None:
    """The DIRECTORIES entry whose rule governs `path`: its own directory, or `skills` for anything below it."""
    parent = str(PurePosixPath(path).parent)
    if parent in DIRECTORIES:
        return parent
    return "skills" if path.startswith("skills/") else None


def select(entries: list[tuple[str, str, str]]) -> tuple[list[tuple[str, str, str]], list[str]]:
    """The allowlisted entries, and every reason the selection is refused."""
    problems, chosen = [], []
    for path, mode, oid in entries:
        if path.casefold().startswith("skills/buddie-discovery/"):
            problems.append(f"competing Discovery source: {path}; use integrations/agensi")
        directory = _rule(path)
        if path == CHANNEL:
            continue
        if path in EXACT:
            chosen.append((path, mode, oid))
        elif directory is not None and any(fnmatch.fnmatchcase(path[len(directory) + 1:], pat)
                                           for pat in DIRECTORIES[directory]):
            chosen.append((path, mode, oid))
        elif path.startswith(STRICT_ROOTS):
            problems.append(f"unexpected file in a runtime directory: {path}")
    for path, mode, _ in chosen:
        if mode not in ("100644", "100755"):
            problems.append(f"{path}: Git mode {mode} is not a regular file (symlink or submodule)")
        if not PLAIN.match(path) or path.startswith(".") and not path.startswith((".claude-plugin/", ".mcp.json")):
            problems.append(f"{path}: not a plain relative path")
    names = [p for p, _, _ in chosen]
    present = set(names)
    problems += [f"missing required {p}" for p in REQUIRED if p not in present]
    folded = {}
    for p in names:
        if p.lower() in folded:
            problems.append(f"{p} and {folded[p.lower()]} collide on a case-insensitive file system")
        folded[p.lower()] = p
    return sorted(chosen), problems


def _blobs(repo: Path, chosen) -> dict[str, bytes]:
    stream = io.BytesIO(_git(repo, "cat-file", "--batch", data="".join(oid + "\n" for _, _, oid in chosen).encode()))
    out = {}
    for path, _, _ in chosen:
        header = stream.readline().decode().split()
        out[path] = stream.read(int(header[2]))
        if stream.read(1) != b"\n":
            raise PackageError(f"{path}: unreadable blob")
    return out


def _content_problems(files: dict[str, bytes]) -> list[str]:
    problems = []
    for path, body in files.items():
        if PurePosixPath(path).suffix.lower() in IMAGES:
            if len(body) > MAX_IMAGE:
                problems.append(f"{path}: {len(body)} bytes, over {MAX_IMAGE} for an image")
            if not body.startswith(b"\x89PNG\r\n\x1a\n"):
                problems.append(f"{path}: not a PNG")
            continue
        if len(body) > MAX_TEXT:
            problems.append(f"{path}: {len(body)} bytes, over {MAX_TEXT} for a text file")
        try:
            body.decode("utf-8")
        except UnicodeDecodeError:
            problems.append(f"{path}: not UTF-8 text")
        if b"\0" in body:
            problems.append(f"{path}: holds a NUL byte")
    if len(files) > MAX_FILES:
        problems.append(f"{len(files)} files, over {MAX_FILES}")
    if sum(map(len, files.values())) > MAX_BYTES:
        problems.append(f"{sum(map(len, files.values()))} bytes, over {MAX_BYTES}")
    return problems


def _version(files: dict[str, bytes]) -> str:
    m = re.search(rb'^__version__\s*=\s*"([^"]+)"', files["buddie/__init__.py"], re.M)
    if not m:
        raise PackageError("buddie/__init__.py has no __version__")
    return m.group(1).decode()


def _reference_problems(files: dict[str, bytes], version: str) -> list[str]:
    """plugin.json, .mcp.json and hooks.json name only files the package has; versions agree."""
    problems = []
    plugin = json.loads(files[".claude-plugin/plugin.json"])
    if plugin.get("version") != version:
        problems.append(f".claude-plugin/plugin.json is version {plugin.get('version')}, buddie {version}")
    if plugin.get("name") != NAME:
        problems.append(f"plugin name {plugin.get('name')!r} is not {NAME}")
    icon = str(plugin.get("icon", "")).removeprefix("./")
    if icon and icon not in files:
        problems.append(f"plugin.json icon {icon} is not in the package")
    market = json.loads(files[".claude-plugin/marketplace.json"])
    sources = [p.get("source") for p in market.get("plugins", [])]
    if sources != ["./"]:
        problems.append(f"marketplace.json must list one plugin at source './', not {sources}")
    root = "${CLAUDE_PLUGIN_ROOT}/"
    named = []
    for server in json.loads(files[".mcp.json"]).get("mcpServers", {}).values():
        named += [a[len(root):] for a in server.get("args", []) if isinstance(a, str) and a.startswith(root)]
    for groups in json.loads(files["hooks/hooks.json"]).get("hooks", {}).values():
        for group in groups:
            for hook in group.get("hooks", []):
                named += re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9._/-]+)", hook.get("command", ""))
    problems += [f"a launcher names {p}, which is not in the package" for p in sorted(set(named)) if p not in files]
    return problems


def zip_bytes(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as z:
        for path in sorted(files):
            info = zipfile.ZipInfo(path, date_time=EPOCH)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3                     # Unix, so the mode below is read
            info.external_attr = (0o100644 & 0xFFFF) << 16
            z.writestr(info, files[path])
    return out.getvalue()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def package_name(version: str) -> str:
    return f"{NAME}-plugin-{version}.zip"


def build(repo: Path, ref: str) -> tuple[bytes, dict, dict[str, bytes]]:
    """(ZIP bytes, manifest, files) for `ref`; PackageError with every reason it cannot be packaged."""
    commit = _git(repo, "rev-parse", "--verify", ref + "^{commit}").decode().strip()
    tree = _git(repo, "rev-parse", "--verify", commit + "^{tree}").decode().strip()
    chosen, problems = select(tracked(repo, commit))
    if problems:
        raise PackageError("; ".join(problems))
    files = _blobs(repo, chosen)
    for original, destination in RELOCATIONS.items():
        files[destination] = files.pop(original)
    version = _version(files)
    import release_notes as rn
    release_path = f"releases/{version}.json"
    entries = [e for e in tracked(repo, commit) if e[0] == release_path]
    if len(entries) != 1 or entries[0][1] not in ("100644", "100755"):
        raise PackageError(f"missing or nonregular public release record {release_path}")
    try:
        record = rn.parse_release(_blobs(repo, entries)[release_path].decode("utf-8"), version)
        files["README.md"] = rn.render_package_readme(record, "claude").encode("utf-8")
        files["RELEASE_NOTES.md"] = rn.render_markdown(record).encode("utf-8")
    except ValueError as error:
        raise PackageError(str(error)) from error
    problems = _content_problems(files) + _reference_problems(files, version)
    problems += [f"{p} is never part of the package" for p in files if p.startswith(NEVER)]
    if problems:
        raise PackageError("; ".join(problems))
    data = zip_bytes(files)
    manifest = {
        "schema": SCHEMA, "name": NAME, "version": version, "commit": commit, "tree": tree, "builder": BUILDER,
        "selection": {"exact": list(EXACT), "directories": {d: list(p) for d, p in DIRECTORIES.items()},
                      "relocations": RELOCATIONS},
        "files": [{"path": p, "size": len(files[p]), "sha256": _sha256(files[p])} for p in sorted(files)],
        "file_count": len(files), "total_bytes": sum(map(len, files.values())),
        "package": {"path": package_name(version), "size": len(data), "sha256": _sha256(data),
                    "format": "zip, stored, sorted, 1980-01-01, mode 0644"},
    }
    return data, manifest, files


def write(out: Path, data: bytes, manifest: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / manifest["package"]["path"]).write_bytes(data)
    (out / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")


def read_zip(data: bytes) -> tuple[dict[str, bytes], list[str]]:
    """The files of a package ZIP, and every way its layout is not the builder's."""
    problems, files = [], {}
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        return {}, [f"not a ZIP: {error}"]
    if z.comment:
        problems.append("the ZIP has a comment")
    names = [i.filename for i in z.infolist()]
    if names != sorted(set(names)):
        problems.append("entries are not unique and in path order")
    for info in z.infolist():
        path = info.filename
        mode = info.external_attr >> 16
        if info.is_dir() or path.endswith("/"):
            problems.append(f"{path}: a directory entry")
            continue
        if not PLAIN.match(path) or ".." in PurePosixPath(path).parts:
            problems.append(f"{path}: not a plain relative path")
        if mode & 0o170000 == 0o120000:
            problems.append(f"{path}: a symlink")
        if mode != 0o100644 or info.create_system != 3:
            problems.append(f"{path}: mode {oct(mode)} / system {info.create_system}, not 0o100644 / Unix")
        if info.compress_type != zipfile.ZIP_STORED or info.date_time != EPOCH or info.extra:
            problems.append(f"{path}: not stored at the fixed time without extra fields")
        files[path] = z.read(info)
    return files, problems


def verify(directory: Path, repo: Path | None = None, ref: str | None = None) -> list[str]:
    """The ZIP in `directory` is byte for byte its manifest's, holds exactly the manifest's files, and (with `ref`)
    is what the builder makes from that commit now."""
    try:
        manifest = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [f"{MANIFEST}: {error}"]
    problems = []
    if manifest.get("schema") != SCHEMA:
        problems.append(f"schema {manifest.get('schema')!r}")
    pkg = manifest.get("package") or {}
    present = sorted(p.name for p in directory.iterdir() if p.is_file() and p.name != MANIFEST)
    if present != [pkg.get("path")]:
        problems.append(f"the directory holds {present}, expected only {pkg.get('path')} and {MANIFEST}")
    try:
        data = (directory / str(pkg.get("path"))).read_bytes()
    except OSError as error:
        return problems + [f"package: {error}"]
    if len(data) != pkg.get("size") or _sha256(data) != pkg.get("sha256"):
        problems.append("the package is not the one its manifest records")
    files, layout = read_zip(data)
    problems += layout
    want = {f["path"]: f for f in manifest.get("files", [])}
    problems += [f"the package lacks {p}" for p in sorted(set(want) - set(files))]
    problems += [f"the package carries {p}, which its manifest does not" for p in sorted(set(files) - set(want))]
    for p in sorted(set(want) & set(files)):
        if len(files[p]) != want[p].get("size") or _sha256(files[p]) != want[p].get("sha256"):
            problems.append(f"{p} is not the file the manifest records")
    problems += [f"{p} is never part of the package" for p in files if p.startswith(NEVER)]
    if ref is not None:
        try:
            again, rebuilt, _ = build(repo or ROOT, ref)
        except PackageError as error:
            return problems + [f"rebuild: {error}"]
        if rebuilt["commit"] != manifest.get("commit"):
            problems.append(f"the manifest is for {manifest.get('commit')}, the rebuild for {rebuilt['commit']}")
        if again != data:
            problems.append("a rebuild from the same commit does not give the same bytes")
        if rebuilt != manifest:
            problems.append("a rebuild from the same commit does not give the same manifest")
    return problems


def unpack(data: bytes, target: Path) -> None:
    files, problems = read_zip(data)
    if problems:
        raise PackageError("; ".join(problems))
    if target.exists() and any(target.iterdir()):
        raise PackageError(f"{target} is not empty")
    for path, body in files.items():
        dest = target / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--ref", required=True)
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--tree", type=Path, help="also unpack the package here (an empty or new directory)")
    b.add_argument("--repo", type=Path, default=ROOT)
    v = sub.add_parser("verify")
    v.add_argument("dir", type=Path)
    v.add_argument("--ref")
    v.add_argument("--repo", type=Path, default=ROOT)
    u = sub.add_parser("unpack")
    u.add_argument("zip", type=Path)
    u.add_argument("dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            data, manifest, _ = build(args.repo, args.ref)
            write(args.out, data, manifest)
            if args.tree:
                unpack(data, args.tree)
            print(f"{manifest['package']['path']}: {manifest['file_count']} files, {manifest['total_bytes']} bytes, "
                  f"sha256 {manifest['package']['sha256']}, commit {manifest['commit']}")
            return 0
        if args.command == "verify":
            problems = verify(args.dir, args.repo, args.ref)
            for p in problems:
                print(f"plugin_package: {p}", file=sys.stderr)
            return 1 if problems else 0
        unpack(args.zip.read_bytes(), args.dir)
        return 0
    except (PackageError, subprocess.CalledProcessError) as error:
        print(f"plugin_package: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
