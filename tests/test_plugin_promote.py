"""Promotion of a verified candidate's compact plugin to plugin-stable (scripts/plugin_promote.py), against a local
bare repository as the remote: nothing reaches GitHub. The branch only ever moves forward, by plain pushes, to commits
whose tree is exactly the package; every other state is refused and left as it was."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import plugin_package as pp  # noqa: E402
import plugin_promote as promote_mod  # noqa: E402
import release_manifest as rm  # noqa: E402
from test_plugin_package import source, with_version  # noqa: E402

BRANCH = "refs/heads/plugin-stable"


def git(repo: Path, *args, data: bytes = b"") -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args], input=data,
                          capture_output=True, check=True).stdout.decode().strip()


@pytest.fixture(scope="module")
def package_files():
    return pp.build(ROOT, "HEAD")[2]


@pytest.fixture
def world(tmp_path, package_files, monkeypatch):
    """A source repository (one commit per version, made on demand) whose origin is an empty bare repository."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True, capture_output=True)
    made = {}
    sources = {}
    original_source_metadata = rm.source_metadata
    monkeypatch.setattr(rm, "source_metadata", lambda version, commit: original_source_metadata(version, commit, sources[commit]))

    def candidate(version: str, files: dict | None = None) -> tuple[Path, Path, str]:
        repo = source(tmp_path / f"src-{version}-{len(made)}", files or with_version(package_files, version))
        git(repo, "remote", "add", "origin", str(remote))
        commit = git(repo, "rev-parse", "HEAD")
        rc = tmp_path / f"rc-{version}-{len(made)}"
        data, manifest, _ = pp.build(repo, commit)
        pp.write(rc / "plugin", data, manifest)
        for path in rm.expected(version):
            if not path.startswith("plugin/"):
                (rc / path).parent.mkdir(parents=True, exist_ok=True)
                (rc / path).write_bytes(path.encode())
        import release_notes as rn
        record, server = original_source_metadata(version, commit, repo)
        rn.write_candidate_metadata(record, rc / "metadata", server)
        sources[commit] = repo
        assert Path(git(repo, "remote", "get-url", "--push", "origin")).resolve() == remote.resolve()
        assert git(remote, "rev-parse", "--is-bare-repository") == "true"
        assert rm.write(rc, version, commit, f"refs/tags/v{version}", "tsyyan/buddie", "1") == []
        made[version + str(len(made))] = repo
        return repo, rc, commit
    return remote, candidate


def head(remote: Path) -> str | None:
    out = git(remote, "for-each-ref", "--format=%(objectname)", BRANCH)
    return out or None


def run(repo, rc, version, commit, **kw):
    return promote_mod.promote(rc, repo, version=version, source=commit, **kw)


def test_the_first_promotion_needs_create_and_makes_exactly_the_package(world):
    remote, candidate = world
    repo, rc, commit = candidate("2.0.1")
    with pytest.raises(promote_mod.Refused, match="needs --create"):
        run(repo, rc, "2.0.1", commit)
    assert head(remote) is None
    record = run(repo, rc, "2.0.1", commit, create=True)
    assert record["action"] == "created" and record["parent"] is None and head(remote) == record["commit"]
    manifest = json.loads((rc / "plugin" / pp.MANIFEST).read_text(encoding="utf-8"))
    assert promote_mod.verify(repo, record["commit"], manifest) == []
    assert promote_mod.trailers(repo, record["commit"]) == {
        "Buddie-Version": "2.0.1", "Source-Commit": commit, "Package-SHA256": manifest["package"]["sha256"],
        "Plugin-Manifest-SHA256": record["plugin_manifest_sha256"]}
    assert record["package_sha256"] == manifest["package"]["sha256"]


def test_promoting_again_changes_nothing(world):
    remote, candidate = world
    repo, rc, commit = candidate("2.0.1")
    first = run(repo, rc, "2.0.1", commit, create=True)
    again = run(repo, rc, "2.0.1", commit)
    assert again["action"] == "already-promoted" and again["commit"] == first["commit"] == head(remote)


def test_a_retry_after_a_failed_push_makes_the_same_commit(world):
    remote, candidate = world
    repo, rc, commit = candidate("2.0.1")
    dry = run(repo, rc, "2.0.1", commit, create=True, dry_run=True)
    assert dry["action"] == "dry-run" and head(remote) is None             # nothing pushed
    assert run(repo, rc, "2.0.1", commit, create=True)["commit"] == dry["commit"]


def test_a_newer_version_advances_the_branch_and_keeps_its_history(world):
    remote, candidate = world
    repo1, rc1, c1 = candidate("2.0.1")
    first = run(repo1, rc1, "2.0.1", c1, create=True)
    repo2, rc2, c2 = candidate("2.1.0")
    second = run(repo2, rc2, "2.1.0", c2)
    assert second["action"] == "advanced" and second["parent"] == first["commit"] == git(remote, "rev-parse",
                                                                                         f"{second['commit']}^")
    assert head(remote) == second["commit"]
    assert git(remote, "merge-base", "--is-ancestor", first["commit"], second["commit"]) == ""


def test_the_same_version_as_another_package_is_refused(world, package_files):
    remote, candidate = world
    repo1, rc1, c1 = candidate("2.0.1")
    first = run(repo1, rc1, "2.0.1", c1, create=True)
    other = with_version(package_files, "2.0.1")
    other["README.md"] = other["README.md"] + b"\nanother build\n"
    repo2, rc2, c2 = candidate("2.0.1", other)
    with pytest.raises(promote_mod.Refused, match="a different release is never put over it"):
        run(repo2, rc2, "2.0.1", c2)
    assert head(remote) == first["commit"]


def test_a_downgrade_is_refused(world):
    remote, candidate = world
    repo1, rc1, c1 = candidate("2.1.0")
    first = run(repo1, rc1, "2.1.0", c1, create=True)
    repo2, rc2, c2 = candidate("2.0.1")
    with pytest.raises(promote_mod.Refused, match="no downgrade"):
        run(repo2, rc2, "2.0.1", c2)
    assert head(remote) == first["commit"]


def test_a_branch_head_that_is_not_a_promotion_is_refused(world, tmp_path):
    remote, candidate = world
    stray = source(tmp_path / "stray", {"README.md": b"hand-made\n"})
    git(stray, "push", "-q", str(remote), f"HEAD:{BRANCH}")
    before = head(remote)
    repo, rc, commit = candidate("2.0.1")
    with pytest.raises(promote_mod.Refused, match="is not a promotion"):
        run(repo, rc, "2.0.1", commit)
    assert head(remote) == before


def test_a_branch_that_moves_during_the_promotion_rejects_the_push(world, monkeypatch, tmp_path):
    remote, candidate = world
    repo1, rc1, c1 = candidate("2.0.1")
    run(repo1, rc1, "2.0.1", c1, create=True)
    repo2, rc2, c2 = candidate("2.1.0")
    real = promote_mod.git
    moved = {}

    def racing(repo, *args, **kw):
        if args[:1] == ("push",) and not moved:                           # someone else promotes first
            moved["commit"] = None
            monkeypatch.setattr(promote_mod, "git", real)                 # the other promotion runs unhindered
            repo3, rc3, c3 = candidate("2.2.0")
            moved["commit"] = run(repo3, rc3, "2.2.0", c3)["commit"]
        return real(repo, *args, **kw)

    monkeypatch.setattr(promote_mod, "git", racing)
    with pytest.raises(promote_mod.Refused, match="git push"):
        run(repo2, rc2, "2.1.0", c2)
    assert head(remote) == moved["commit"]                                # the other promotion stands, untouched


def test_a_candidate_that_does_not_verify_is_refused(world):
    remote, candidate = world
    repo, rc, commit = candidate("2.0.1")
    (rc / "plugin" / pp.package_name("2.0.1")).write_bytes(b"swapped")
    with pytest.raises(promote_mod.Refused, match="does not verify"):
        run(repo, rc, "2.0.1", commit, create=True)
    with pytest.raises(promote_mod.Refused, match="does not verify"):
        run(repo, rc, "2.0.1", "0" * 40, create=True)
    assert head(remote) is None


def test_verify_finds_a_branch_tree_that_is_not_the_package(world, tmp_path):
    remote, candidate = world
    repo, rc, commit = candidate("2.0.1")
    record = run(repo, rc, "2.0.1", commit, create=True)
    manifest = json.loads((rc / "plugin" / pp.MANIFEST).read_text(encoding="utf-8"))
    # a commit with the same trailers but one more file, pushed over it by hand (as a fast-forward)
    message = git(repo, "show", "-s", "--format=%B", record["commit"])
    tree = git(repo, "rev-parse", f"{record['commit']}^{{tree}}")
    extra = git(repo, "hash-object", "-w", "--stdin", data=b"leaked\n")
    entries = git(repo, "ls-tree", tree) + f"\n100644 blob {extra}\tnotes.txt"
    forged_tree = git(repo, "mktree", data=entries.encode())
    forged = git(repo, "commit-tree", forged_tree, "-p", record["commit"], data=message.encode())
    git(repo, "push", "-q", "origin", f"{forged}:{BRANCH}")
    assert "the branch carries notes.txt, which the package does not" in promote_mod.verify(repo, forged, manifest)
    with pytest.raises(promote_mod.Refused, match="its tree is not it"):
        run(repo, rc, "2.0.1", commit)
    assert head(remote) == forged                                         # refused, not repaired silently
