"""Promote a verified release candidate's compact plugin to the distribution branch `plugin-stable` (docs/release.md,
"plugin-stable"). Run by release.yml's manually authorized `plugin-stable` stage, never by a push.

    python scripts/plugin_promote.py promote RC --repo DIR --version V --source SHA [--remote origin]
        [--branch plugin-stable] [--create] [--dry-run]      # prints the promotion record (JSON)
    python scripts/plugin_promote.py verify --repo DIR --commit SHA --manifest RC/plugin/plugin-manifest.json

The branch holds the package and nothing else: its tree is exactly the files of the candidate's verified ZIP
(plugin_package.py), so the plugin a user installs from it is the plugin the candidate tested. What it was made from
is in the commit message, as trailers: Buddie-Version, Source-Commit, Package-SHA256, Plugin-Manifest-SHA256.

Never forced, never rewritten. The new commit's parent is the branch head read before the push, and the push is a
plain one: a branch that moved meanwhile rejects it (not a fast-forward) and nothing changes. Fails closed:
  - the candidate must verify (release_manifest.py, plugin_package.py) for this version and source commit
  - no branch: refused unless --create (the first promotion is its own decision)
  - a head that is not a promotion (no trailers): refused
  - the head already this version: done if it is this package and its tree is exactly the package (idempotent,
    nothing pushed), refused otherwise
  - the head a newer version: refused (no downgrade; roll back by promoting a fixed newer version)
The commit is deterministic (fixed identity, the source commit's date, fixed parent), so a retry after a failed push
makes the same commit. `verify` checks a branch commit's tree against the manifest, byte for byte.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plugin_package as pp  # noqa: E402
import release_manifest as rm  # noqa: E402

BRANCH = "plugin-stable"
IDENTITY = ("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com")
TRAILERS = ("Buddie-Version", "Source-Commit", "Package-SHA256", "Plugin-Manifest-SHA256")
RECORD = "buddie-plugin-promotion-v1"


class Refused(RuntimeError):
    """A state this promotion must not change: a person decides."""


def git(repo: Path, *args: str, data: bytes | None = None, env: dict | None = None, check: bool = True) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args], input=data if data is not None else b"",
                         capture_output=True, env=dict(os.environ, **(env or {})))
    if check and out.returncode != 0:
        raise Refused(f"git {' '.join(args[:3])}: {out.stderr.decode(errors='replace').strip()}")
    return out.stdout.decode().strip()


def _version_key(version: str) -> tuple[int, ...]:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version or ""):
        raise Refused(f"{version!r} is not X.Y.Z")
    return tuple(int(p) for p in version.split("."))


def trailers(repo: Path, commit: str) -> dict[str, str]:
    message = git(repo, "show", "-s", "--format=%B", commit)
    found = dict(re.findall(r"^([A-Za-z0-9-]+): (.+)$", message, re.M))
    return {k: found[k] for k in TRAILERS if k in found}


def tree_files(repo: Path, commit: str) -> dict[str, tuple[str, str]]:
    """path -> (mode, sha256 of the blob's bytes) of every entry of `commit`'s tree."""
    entries = []
    for raw in git(repo, "ls-tree", "-r", "--full-tree", commit).splitlines():
        meta, path = raw.split("\t", 1)
        mode, kind, oid = meta.split()
        entries.append((path, mode, kind, oid))
    blobs = [e for e in entries if e[2] == "blob"]
    out = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch"], capture_output=True, check=True,
                         input="".join(e[3] + "\n" for e in blobs).encode()).stdout
    files, at = {}, 0
    for path, mode, _kind, _oid in blobs:
        end = out.index(b"\n", at)
        size = int(out[at:end].split()[2])
        body = out[end + 1:end + 1 + size]
        at = end + 1 + size + 1
        files[path] = (mode, hashlib.sha256(body).hexdigest())
    for path, mode, kind, _ in entries:
        if kind != "blob":
            files[path] = (mode, kind)
    return files


def verify(repo: Path, commit: str, manifest: dict) -> list[str]:
    """`commit`'s tree is exactly the manifest's files, regular (0644), byte for byte; its trailers name it."""
    problems = []
    got = tree_files(repo, commit)
    want = {f["path"]: f["sha256"] for f in manifest["files"]}
    problems += [f"the branch lacks {p}" for p in sorted(set(want) - set(got))]
    problems += [f"the branch carries {p}, which the package does not" for p in sorted(set(got) - set(want))]
    for p in sorted(set(want) & set(got)):
        mode, digest = got[p]
        if mode != "100644":
            problems.append(f"{p}: mode {mode} on the branch, not 100644")
        if digest != want[p]:
            problems.append(f"{p} on the branch is not the package's file")
    t = trailers(repo, commit)
    if t.get("Buddie-Version") != manifest["version"] or t.get("Source-Commit") != manifest["commit"] \
            or t.get("Package-SHA256") != manifest["package"]["sha256"]:
        problems.append(f"the commit's trailers {t} do not name this package")
    return problems


def _tree(repo: Path, files: dict[str, bytes]) -> str:
    """The Git tree of exactly `files` (mode 100644), written into `repo`'s object store."""
    git_dir = Path(git(repo, "rev-parse", "--git-dir"))
    index = (git_dir if git_dir.is_absolute() else repo / git_dir) / "plugin-promote.index"
    env = {"GIT_INDEX_FILE": str(index)}
    paths = sorted(files)
    with tempfile.TemporaryDirectory() as tmp:  # the bytes as they are (no filters: --no-filters), hashed at once
        for i, path in enumerate(paths):
            Path(tmp, str(i)).write_bytes(files[path])
        listing = "".join(str(Path(tmp, str(i))) + "\n" for i in range(len(paths))).encode()
        oids = git(repo, "hash-object", "-w", "--no-filters", "--stdin-paths", data=listing).split()
    if len(oids) != len(paths):
        raise Refused("could not write the package's blobs")
    try:
        if index.exists():
            index.unlink()
        info = "".join(f"100644 {oid}\t{path}\n" for oid, path in zip(oids, paths)).encode()
        git(repo, "update-index", "--add", "--index-info", data=info, env=env)
        return git(repo, "write-tree", env=env)
    finally:
        if index.exists():
            index.unlink()


def promote(rc: Path, repo: Path, *, version: str, source: str, remote: str = "origin", branch: str = BRANCH,
            create: bool = False, dry_run: bool = False) -> dict:
    problems = rm.verify(rc, version, source) + pp.verify(rc / "plugin")
    if problems:
        raise Refused("the candidate does not verify: " + "; ".join(problems))
    manifest = json.loads((rc / "plugin" / pp.MANIFEST).read_text(encoding="utf-8"))
    files, layout = pp.read_zip((rc / "plugin" / manifest["package"]["path"]).read_bytes())
    if layout:
        raise Refused("; ".join(layout))
    plugin_manifest_sha = hashlib.sha256((rc / "plugin" / pp.MANIFEST).read_bytes()).hexdigest()
    ref = f"refs/heads/{branch}"
    git(repo, "fetch", "--quiet", "--no-tags", remote, f"+{ref}:refs/remotes/{remote}/{branch}", check=False)
    listed = git(repo, "ls-remote", remote, ref)
    head = listed.split()[0] if listed else None
    tree = _tree(repo, files)
    record = {"schema": RECORD, "branch": branch, "version": version, "source_commit": source, "tree": tree,
              "package_sha256": manifest["package"]["sha256"], "plugin_manifest_sha256": plugin_manifest_sha,
              "parent": head}
    if head is None:
        if not create:
            raise Refused(f"{branch} does not exist: its first promotion needs --create")
    else:
        if git(repo, "cat-file", "-t", head, check=False) != "commit":
            raise Refused(f"{branch} names {head}, which this clone does not have after fetching it")
        t = trailers(repo, head)
        if set(t) != set(TRAILERS):
            raise Refused(f"{branch}'s head {head} is not a promotion (trailers {sorted(t)}): a person looks first")
        same = (t["Package-SHA256"], t["Buddie-Version"], t["Source-Commit"]) == (record["package_sha256"], version,
                                                                                    source)
        if same and git(repo, "rev-parse", f"{head}^{{tree}}") != tree:
            raise Refused(f"{branch}'s head {head} names this package but its tree is not it: a person looks first")
        if same:
            return dict(record, action="already-promoted", commit=head, parent=git(repo, "rev-parse", f"{head}^",
                                                                                     check=False) or None)
        if t["Buddie-Version"] == version:
            raise Refused(f"{branch} already holds {version} as package {t['Package-SHA256']} from "
                          f"{t['Source-Commit']}: a different release is never put over it")
        if _version_key(t["Buddie-Version"]) > _version_key(version):
            raise Refused(f"{branch} holds {t['Buddie-Version']}, newer than {version}: no downgrade")
    date = git(repo, "show", "-s", "--format=%cI", source)
    message = (f"buddie {version} plugin, from {source[:12]}\n\n"
               f"The compact Claude Code plugin of release candidate {version} (scripts/plugin_package.py).\n\n"
               f"Buddie-Version: {version}\nSource-Commit: {source}\n"
               f"Package-SHA256: {record['package_sha256']}\nPlugin-Manifest-SHA256: {plugin_manifest_sha}\n")
    env = {"GIT_AUTHOR_NAME": IDENTITY[0], "GIT_AUTHOR_EMAIL": IDENTITY[1], "GIT_AUTHOR_DATE": date,
           "GIT_COMMITTER_NAME": IDENTITY[0], "GIT_COMMITTER_EMAIL": IDENTITY[1], "GIT_COMMITTER_DATE": date}
    commit = git(repo, "commit-tree", tree, *(("-p", head) if head else ()), data=message.encode(), env=env)
    if problems := verify(repo, commit, manifest):
        raise Refused("the commit made is not the package: " + "; ".join(problems))
    record.update(action="dry-run" if dry_run else ("created" if head is None else "advanced"), commit=commit)
    if dry_run:
        return record
    # a plain push: no force, no +refspec. A branch that moved since `head` rejects it as not a fast-forward.
    git(repo, "push", "--quiet", remote, f"{commit}:{ref}")
    after = git(repo, "ls-remote", remote, ref).split()
    if not after or after[0] != commit:
        raise Refused(f"after the push {branch} names {after[:1]}, not {commit}")
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("promote")
    p.add_argument("rc", type=Path)
    p.add_argument("--repo", type=Path, default=Path.cwd())
    p.add_argument("--version", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--remote", default="origin")
    p.add_argument("--branch", default=BRANCH)
    p.add_argument("--create", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("--repo", type=Path, default=Path.cwd())
    v.add_argument("--commit", required=True)
    v.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "promote":
            record = promote(args.rc, args.repo, version=args.version, source=args.source, remote=args.remote,
                             branch=args.branch, create=args.create, dry_run=args.dry_run)
            print(json.dumps(record, indent=2))
            return 0
        problems = verify(args.repo, args.commit, json.loads(args.manifest.read_text(encoding="utf-8")))
        for problem in problems:
            print(f"plugin_promote: {problem}", file=sys.stderr)
        return 1 if problems else 0
    except Refused as error:
        print(f"plugin_promote: refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
