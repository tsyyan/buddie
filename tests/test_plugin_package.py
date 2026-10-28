"""The compact Claude Code plugin (scripts/plugin_package.py): what it selects from a commit, what it refuses, that
its bytes are the same on every rebuild, that a changed or extra file is caught, and that the package runs as a
plugin (scripts/smoke_plugin.py). Sources are synthetic Git repositories made with plumbing (blobs and index entries,
no checkout), so modes, symlinks and bytes are the same on every OS."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import plugin_package as pp  # noqa: E402
import smoke_plugin  # noqa: E402

DATE = "2026-10-01T12:00:00+00:00"


@pytest.fixture(scope="module")
def head():
    """The package of this repository's HEAD."""
    return pp.build(ROOT, "HEAD")


def git(repo: Path, *args, data: bytes = b"", env: dict | None = None) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], input=data, capture_output=True, check=True,
                          env=dict(os.environ, **(env or {}))).stdout.decode().strip()


def source(tmp: Path, files: dict[str, bytes], modes: dict[str, str] | None = None) -> Path:
    """A repository whose one commit holds exactly `files` (with `modes`), made without a working tree (one
    `git fast-import` stream: no checkout, no line-ending conversion, no file-system symlink support needed)."""
    files = dict(files)
    for original, destination in pp.DISCOVERY.items():
        if destination in files and original not in files:
            files[original] = files.pop(destination)
    if "buddie/__init__.py" in files:
        import re
        version = re.search(rb'__version__ = "([^"]+)"', files["buddie/__init__.py"]).group(1).decode()
        release_path = f"releases/{version}.json"
        if release_path not in files:
            record = json.loads((ROOT / "releases/2.0.2.json").read_text())
            record["version"] = version
            files[release_path] = json.dumps(record).encode()
        if "server.json" not in files:
            server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
            server["version"] = version
            server["packages"][0]["version"] = version
            files["server.json"] = json.dumps(server).encode()
    tmp.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(tmp)], check=True, capture_output=True)
    stream = [b"commit refs/heads/main\n", b"committer t <t@t> 1759320000 +0000\n", b"data 7\nsource\n"]
    for path, body in sorted(files.items()):
        stream += [f"M {(modes or {}).get(path, '100644')} inline {path}\ndata {len(body)}\n".encode(), body, b"\n"]
    git(tmp, "fast-import", "--quiet", data=b"".join(stream))
    git(tmp, "symbolic-ref", "HEAD", "refs/heads/main")
    return tmp


def with_version(files: dict[str, bytes], version: str) -> dict[str, bytes]:
    out = dict(files)
    out["buddie/__init__.py"] = out["buddie/__init__.py"].replace(b'__version__ = "2.0.2"',
                                                                  f'__version__ = "{version}"'.encode())
    plugin = json.loads(out[".claude-plugin/plugin.json"])
    plugin["version"] = version
    out[".claude-plugin/plugin.json"] = (json.dumps(plugin, indent=2) + "\n").encode()
    return out


# --- selection -----------------------------------------------------------------------------------------------------

def test_discovery_and_reference_are_canonical_git_bytes(head):
    files = head[2]
    for relative in ("SKILL.md", "references/reporting.md"):
        original = subprocess.run(["git", "-C", str(ROOT), "show", f"HEAD:integrations/agensi/{relative}"],
                                  check=True, capture_output=True).stdout
        assert files[f"skills/buddie-discovery/{relative}"] == original
    assert sum(b"name: buddie-discovery\n" in body for body in files.values()) == 1


def test_discovery_missing_reference_refuses_build(head, tmp_path):
    files = dict(head[2])
    files.pop("skills/buddie-discovery/references/reporting.md", None)
    with pytest.raises(pp.PackageError, match="missing required integrations/agensi/references/reporting.md"):
        pp.build(source(tmp_path / "missing-reference", files), "HEAD")


def test_discovery_competing_source_is_refused(head, tmp_path):
    files = dict(head[2])
    files["integrations/agensi/SKILL.md"] = b"canonical\n"
    files["skills/buddie-discovery/SKILL.md"] = b"competing\n"
    with pytest.raises(pp.PackageError, match="competing Discovery"):
        pp.build(source(tmp_path / "competing", files), "HEAD")


def test_discovery_case_variant_cannot_collide_after_relocation():
    entries = [(p, "100644", "0" * 40) for p in (*pp.REQUIRED, "skills/Buddie-Discovery/SKILL.md")]
    assert any("competing Discovery" in problem for problem in pp.select(entries)[1])

def test_the_package_is_the_runtime_and_nothing_else(head):
    data, manifest, files = head
    tracked = {p for p, _, _ in pp.tracked(ROOT, "HEAD")}
    assert set(files) - {"RELEASE_NOTES.md"} - set(pp.DISCOVERY.values()) <= tracked
    assert not [p for p in files if p.startswith(pp.NEVER)]
    for path in pp.REQUIRED:
        assert pp.DISCOVERY.get(path, path) in files
    # every runtime file of #61's inventory is in it, unchanged; the rest is listing, legal and the icon
    sys.path.insert(0, str(ROOT / "scripts"))
    import plugin_inventory as pi
    runtime = {p for p in tracked if pi.category(p) == "runtime-required"}
    assert runtime <= set(files)
    assert set(files) - runtime == {".claude-plugin/marketplace.json", "README.md", "LICENSE", "NOTICE", "PRIVACY.md",
                                    "assets/icon.png", "RELEASE_NOTES.md", *pp.DISCOVERY.values()}
    assert manifest["file_count"] == len(files) <= pp.MAX_FILES and manifest["total_bytes"] <= pp.MAX_BYTES
    assert max(len(b) for p, b in files.items() if not p.endswith(".png")) <= pp.MAX_TEXT


def test_the_same_commit_gives_the_same_bytes(head, tmp_path):
    data, manifest, files = head
    again, manifest2, _ = pp.build(ROOT, manifest["commit"])
    assert again == data and manifest2 == manifest
    # and from another repository holding the same files: the package depends on the files, not the repository
    other = pp.build(source(tmp_path / "copy", files), "HEAD")[0]
    assert other == data
    pp.write(tmp_path / "out", data, manifest)
    assert pp.verify(tmp_path / "out", ROOT, manifest["commit"]) == []


def test_the_zip_layout_is_normalized(head):
    data, _, files = head
    z = zipfile.ZipFile(io.BytesIO(data))
    assert [i.filename for i in z.infolist()] == sorted(files)
    for info in z.infolist():
        assert info.compress_type == zipfile.ZIP_STORED and info.date_time == pp.EPOCH and not info.extra
        assert info.external_attr >> 16 == 0o100644 and info.create_system == 3
    assert pp.read_zip(data) == (files, [])


@pytest.mark.parametrize("change, why", [
    (lambda f: f.update({"buddie/data.json": b"{}"}), "unexpected file in a runtime directory: buddie/data.json"),
    (lambda f: f.update({"buddie/sub/extra.py": b"x = 1\n"}), "unexpected file in a runtime directory: buddie/sub"),
    (lambda f: f.update({"hooks/other.sh": b"echo\n"}), "unexpected file in a runtime directory: hooks/other.sh"),
    (lambda f: f.update({".claude-plugin/extra.json": b"{}"}), "unexpected file in a runtime directory: .claude-pl"),
    (lambda f: f.pop("hooks/run.sh"), "missing required hooks/run.sh"),
    (lambda f: f.pop("skills/verbatim/SKILL.md"), "missing required skills/verbatim/SKILL.md"),
    (lambda f: f.update({"buddie/big.py": b"#" * (pp.MAX_TEXT + 1)}), "over 262144 for a text file"),
    (lambda f: f.update({"buddie/latin.py": b"x = '\xe9'\n"}), "not UTF-8"),
    (lambda f: f.update({"buddie/zero.py": b"x\0"}), "holds a NUL byte"),
    (lambda f: f.update({"assets/icon.png": b"not a png"}), "not a PNG"),
])
def test_a_commit_that_cannot_be_packaged_is_refused(head, tmp_path, change, why):
    files = dict(head[2])
    change(files)
    with pytest.raises(pp.PackageError, match=why.replace("(", r"\(")):
        pp.build(source(tmp_path / "src", files), "HEAD")


def test_paths_that_collide_on_a_case_insensitive_file_system_are_refused():
    # on the entry list itself: Git on a case-insensitive file system may fold the two paths before a tree is made
    entries = [(p, "100644", "0" * 40) for p in (*pp.REQUIRED, "commands/check.md", "commands/Check.md")]
    assert any("collide on a case-insensitive" in p for p in pp.select(entries)[1])


def test_research_tests_and_scripts_are_never_read(head, tmp_path):
    files = dict(head[2])
    files.update({"tests/test_x.py": b"x", "results/E1/big.json": b"[" * (pp.MAX_TEXT * 2), "experiments/a.py": b"x",
                  "scripts/tool.py": b"x", "docs/guide.md": b"x", "assets/hero.png": b"\x89PNG\r\n\x1a\nx"})
    data, manifest, packaged = pp.build(source(tmp_path / "src", files), "HEAD")
    assert packaged == head[2] and data == head[0]


def test_symlinks_and_submodules_are_refused(head, tmp_path):
    files = dict(head[2], **{"buddie/link.py": b"cli.py"})
    with pytest.raises(pp.PackageError, match="not a regular file"):
        pp.build(source(tmp_path / "a", files, {"buddie/link.py": "120000"}), "HEAD")
    files = dict(head[2], **{"README.md": head[2]["README.md"]})
    with pytest.raises(pp.PackageError, match="symlink or submodule"):
        pp.build(source(tmp_path / "b", files, {"README.md": "120000"}), "HEAD")


def test_versions_and_launcher_references_must_agree(head, tmp_path):
    files = dict(head[2])
    plugin = json.loads(files[".claude-plugin/plugin.json"])
    files[".claude-plugin/plugin.json"] = json.dumps(dict(plugin, version="9.9.9")).encode()
    with pytest.raises(pp.PackageError, match="plugin.json is version 9.9.9"):
        pp.build(source(tmp_path / "a", files), "HEAD")
    files = dict(head[2])
    files["hooks/hooks.json"] = files["hooks/hooks.json"].replace(b"hooks/run.sh", b"hooks/gone.sh")
    with pytest.raises(pp.PackageError, match="names hooks/gone.sh"):
        pp.build(source(tmp_path / "b", files), "HEAD")
    assert pp.build(source(tmp_path / "c", with_version(head[2], "2.1.0")), "HEAD")[1]["version"] == "2.1.0"


# --- verification of a built package ------------------------------------------------------------------------------

def _rezip(files: dict[str, bytes], **info) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for path in sorted(files):
            zi = zipfile.ZipInfo(path, date_time=pp.EPOCH)
            zi.create_system, zi.external_attr = 3, 0o100644 << 16
            for k, v in info.get(path, {}).items():
                setattr(zi, k, v)
            z.writestr(zi, files[path])
    return out.getvalue()


@pytest.mark.parametrize("tamper, why", [
    (lambda d, f: d[:-30] + bytes(30), "not the one its manifest records"),
    (lambda d, f: _rezip(dict(f, **{"tests/evil.py": b"x"})), "carries tests/evil.py"),
    (lambda d, f: _rezip({k: v for k, v in f.items() if k != "run.py"}), "lacks run.py"),
    (lambda d, f: _rezip(dict(f, **{"run.py": f["run.py"] + b"\n"})), "run.py is not the file the manifest records"),
    (lambda d, f: _rezip(f, **{"run.py": {"external_attr": 0o120777 << 16}}), "run.py: a symlink"),
    (lambda d, f: _rezip(f, **{"run.py": {"external_attr": 0o100755 << 16}}), "mode 0o100755"),
    (lambda d, f: _rezip(f, **{"run.py": {"compress_type": zipfile.ZIP_DEFLATED}}), "not stored at the fixed time"),
    (lambda d, f: _rezip(dict(f, **{"../escape.py": b"x"})), "not a plain relative path"),
])
def test_a_changed_or_extra_file_is_refused(head, tmp_path, tamper, why):
    data, manifest, files = head
    pp.write(tmp_path, tamper(data, files), manifest)
    problems = pp.verify(tmp_path)
    assert any(why in p for p in problems), problems


def test_a_manifest_or_directory_that_disagrees_is_refused(head, tmp_path):
    data, manifest, _ = head
    pp.write(tmp_path / "a", data, dict(manifest, files=manifest["files"][1:]))
    assert any("which its manifest does not" in p for p in pp.verify(tmp_path / "a"))
    pp.write(tmp_path / "b", data, manifest)
    (tmp_path / "b" / "extra.txt").write_text("x", encoding="utf-8")
    assert any("expected only" in p for p in pp.verify(tmp_path / "b"))
    pp.write(tmp_path / "c", data, dict(manifest, commit="0" * 40))
    assert any("the manifest is for" in p for p in pp.verify(tmp_path / "c", ROOT, "HEAD"))


def test_unpack_refuses_a_bad_zip_and_a_used_directory(head, tmp_path):
    data, _, files = head
    with pytest.raises(pp.PackageError):
        pp.unpack(_rezip(dict(files, **{"../x": b"x"})), tmp_path / "a")
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "keep").write_text("x", encoding="utf-8")
    with pytest.raises(pp.PackageError, match="not empty"):
        pp.unpack(data, tmp_path / "b")


# --- the package as a plugin ---------------------------------------------------------------------------------------

def test_the_unpacked_package_runs_as_a_plugin(head, tmp_path):
    data, manifest, _ = head
    tree = tmp_path / "plugin with spaces"
    pp.unpack(data, tree)
    (tmp_path / "plugin-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert smoke_plugin.check_files(tree, manifest) == []
    assert smoke_plugin.check_config(tree) == []
    from buddie import mcp
    assert smoke_plugin.check_mcp(tree, manifest, sys.executable, [t["name"] for t in mcp.TOOLS]) == []
    hooks = smoke_plugin.check_hooks(tree)
    assert hooks == [] or hooks == ["no sh on PATH: the hooks (sh run.sh) cannot be checked here"]
    (tree / "tests").mkdir()
    (tree / "tests" / "x.py").write_text("x", encoding="utf-8")
    assert "unexpected tests/x.py" in smoke_plugin.check_files(tree, manifest)


def test_the_candidate_workflow_builds_validates_and_installs_the_plugin_without_publishing():
    text = (ROOT / ".github/workflows/release-candidate.yml").read_text(encoding="utf-8")
    for needed in ("plugin_package.py build --ref \"$GITHUB_SHA\"", "plugin_package.py verify rc/plugin --ref",
                   "plugin validate --strict", "--profile directory", "plugin install buddie@buddie",
                   "smoke_plugin.py"):
        assert needed in text, needed
    assert "plugin-stable" not in text and "git push" not in text
