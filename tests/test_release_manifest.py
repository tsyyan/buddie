"""The release candidate's record (scripts/release_manifest.py) and the release workflow's gates (docs/release.md):
the files published are the files the candidate built and recorded, and nothing publishes without the manual,
confirmed run that `authorize` checks."""
from __future__ import annotations

import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import release_manifest as rm  # noqa: E402

V = "2.0.0"
SHA = "b6464a7839274297c5c110ddd1a50557f4281c42"


def bind_plugin(root: Path, version: str, commit: str, claimed: str | None = None) -> None:
    """A plugin manifest that names the candidate's ZIP, commit and version (or `claimed`), as plugin_package.py
    writes one."""
    data = (root / f"plugin/buddie-plugin-{version}.zip").read_bytes()
    (root / f"plugin/{rm.PLUGIN_MANIFEST}").write_text(json.dumps({
        "schema": rm.PLUGIN_SCHEMA, "name": "buddie", "version": claimed or version, "commit": commit,
        "package": {"path": f"buddie-plugin-{version}.zip", "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest()}}), encoding="utf-8")


def bind_metadata(root, version):
    import release_notes as rn
    record = {"schema": rn.SCHEMA, "version": version, "date": "2026-10-26", "summary": "Public release.", "changes": ["Candidate release notes."], "upgrade": "Install this version.", "permissions": "Optional credentials.", "security": "Local checks.", "limitations": "Catalog display unverified."}
    rn.write_candidate_metadata(record, root / "metadata", {"version": version, "packages": [{"version": version}]})


@pytest.fixture
def rc(tmp_path):
    for path in rm.expected(V):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes(path.encode() * 100)
    bind_plugin(tmp_path, V, SHA)
    bind_metadata(tmp_path, V)
    assert rm.write(tmp_path, V, SHA, "refs/tags/v2.0.0", "tsyyan/buddie", "1") == []
    return tmp_path


def test_the_record_names_the_commit_and_every_file_by_size_and_sha256(rc):
    record = rm.load(rc)
    assert (record["schema"], record["version"], record["commit"]) == (rm.SCHEMA, V, SHA)
    assert [f["kind"] for f in record["files"]] == list(rm.expected(V).values())
    for f in record["files"]:
        data = (rc / f["path"]).read_bytes()
        assert (f["size"], f["sha256"]) == (len(data), hashlib.sha256(data).hexdigest())
    # SHA256SUMS in the format `sha256sum -c` reads
    lines = (rc / rm.SUMS).read_bytes().decode().splitlines()
    assert lines == [f"{f['sha256']}  {f['path']}" for f in record["files"]]
    assert rm.verify(rc, V, SHA) == []


def test_a_changed_missing_or_extra_file_is_refused(rc):
    wheel = rc / f"dist/buddie-{V}-py3-none-any.whl"
    wheel.write_bytes(b"rebuilt")
    assert any("not the file the candidate recorded" in p for p in rm.verify(rc, V, SHA))
    wheel.unlink()
    assert any("missing" in p for p in rm.verify(rc, V, SHA))
    (rc / "dist" / "other.whl").write_bytes(b"x")
    assert any("unexpected dist/other.whl" in p for p in rm.verify(rc, V, SHA))


def test_another_version_or_commit_is_refused(rc):
    assert any("not 2.0.1" in p for p in rm.verify(rc, "2.0.1", SHA))
    assert any("built from" in p for p in rm.verify(rc, V, "0" * 40))
    assert any("not a full commit id" in p for p in rm.verify(rc, V, "b6464a7"))


def test_sums_that_disagree_with_the_record_are_refused(rc):
    (rc / rm.SUMS).write_text("0" * 64 + f"  dist/buddie-{V}.tar.gz\n", encoding="utf-8")
    assert any("SHA256SUMS disagrees" in p for p in rm.verify(rc, V, SHA))


def test_write_refuses_an_incomplete_candidate(tmp_path):
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / f"buddie-{V}.tar.gz").write_bytes(b"x")
    problems = rm.write(tmp_path, V, SHA)
    assert f"missing dist/buddie-{V}-py3-none-any.whl" in problems and f"missing bundle/buddie-{V}.mcpb" in problems
    assert not (tmp_path / rm.MANIFEST).exists()


def test_pypi_must_serve_exactly_the_candidates_wheel_and_sdist(rc):
    files = {Path(f["path"]).name: f["sha256"] for f in rm.load(rc)["files"]}
    urls = [{"filename": n, "digests": {"sha256": h}} for n, h in files.items() if n.endswith((".whl", ".tar.gz"))]
    assert rm.pypi(rc, {"urls": urls}) == []
    assert rm.pypi(rc, {"urls": urls[:1]}) == [f"PyPI has no buddie-{V}.tar.gz"]
    urls[0]["digests"]["sha256"] = "f" * 64
    assert any("is not the candidate's" in p for p in rm.pypi(rc, {"urls": urls}))


def _jobs(path: str) -> dict[str, str]:
    text = (ROOT / ".github" / "workflows" / path).read_text(encoding="utf-8")
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"(?m)^  ([a-z-]+):\n", body)
    return dict(zip(parts[1::2], parts[2::2]))


def test_a_tag_push_builds_a_candidate_and_publishes_nothing():
    release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    jobs = _jobs("release.yml")
    assert set(jobs) == {"candidate", "authorize", "pypi", "mcp-registry", "github-release", "plugin-stable"}
    assert "uses: ./.github/workflows/release-candidate.yml" in jobs["candidate"]
    assert "if: github.event_name == 'workflow_dispatch' && inputs.candidate != ''" in jobs["authorize"]
    for name in ("pypi", "mcp-registry", "github-release"):
        job = jobs[name]
        # every publishing job needs authorize, and only runs when it succeeded
        assert re.search(r"needs: (authorize|\[authorize, pypi\])", job), name
        assert "always()" not in job or "needs.authorize.result == 'success'" in job, name
        # it publishes the candidate's artifact from the named run, never a build of its own
        assert "run-id: ${{ inputs.candidate }}" in job and "python -m build" not in job, name
        assert "release_manifest.py" in job, name
    assert "environment:\n      name: pypi" in jobs["pypi"] and "id-token: write" in jobs["pypi"]
    # the decisions are release_publish.py's (tests/test_release_publish.py), given the run's own facts
    assert "release_publish.py authorize rc" in jobs["authorize"] and '--confirm "$CONFIRM"' in jobs["authorize"]
    assert 'merge-base --is-ancestor "$GITHUB_SHA" origin/main' in jobs["authorize"]
    assert "release_publish.py pypi-plan" in jobs["pypi"] and "steps.plan.outputs.plan == 'upload'" in jobs["pypi"]
    assert jobs["mcp-registry"].count("release_publish.py registry-check") == 2   # before skipping, after publishing
    assert "release_publish.py github-release" in jobs["github-release"] and "gh release" not in jobs["github-release"]
    # the publisher binary is checked against its release's SHA-256
    assert "sha256sum -c" in jobs["mcp-registry"]
    assert "push:\n    tags:" in release


def test_the_candidate_workflow_reads_and_publishes_nothing():
    text = (ROOT / ".github/workflows/release-candidate.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read\n" in text
    assert not re.search(r"id-token|contents: write|pypi-publish|mcp-publisher|gh release", text)
    ci = _jobs("ci.yml")
    assert "uses: ./.github/workflows/release-candidate.yml" in ci["release-candidate"]


# --- the documented check of a published release's files (docs/release.md) ---------------------------------------

def _documented_steps(version: str, commit: str) -> list[str]:
    doc = (ROOT / "docs/release.md").read_text(encoding="utf-8")
    block = doc.split("<!-- release-check: begin -->", 1)[1].split("<!-- release-check: end -->", 1)[0]
    steps = re.findall(r"```bash\n(.+?)\n```", block)
    return [s.replace("X.Y.Z", version).replace("COMMIT", commit) for s in steps]


def _sha256sum_check(folder: Path) -> list[str]:
    """`sha256sum -c SHA256SUMS`, as coreutils reads the file: every listed path must exist with that digest."""
    failed = []
    for line in (folder / rm.SUMS).read_text(encoding="utf-8").splitlines():
        digest, path = line.split("  ", 1)
        target = folder / path
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            failed.append(path)
    return failed


def _release_download(rc: Path, into: Path) -> None:
    """What `gh release download` leaves: the release's assets, flat."""
    into.mkdir()
    for f in rm.load(rc)["files"]:
        shutil.copy(rc / f["path"], into / Path(f["path"]).name)
    for name in (rm.MANIFEST, rm.SUMS):
        shutil.copy(rc / name, into / name)


def test_the_documented_release_check_works_on_a_flat_download(rc, tmp_path):
    """The steps in docs/release.md, "Checking a published release's files", run as written on a release's flat
    assets: the files go back where the manifest says, the sums check, and the manifest check passes. Before the
    move, the sums check fails, which is why the move is there."""
    steps = _documented_steps(V, SHA)
    assert steps[0] == f"gh release download v{V} --repo tsyyan/buddie --dir buddie-{V}"
    _release_download(rc, tmp_path / f"buddie-{V}")
    assert len(_sha256sum_check(tmp_path / f"buddie-{V}")) == len(rm.expected(V))  # the flat layout, unmoved
    cwd = tmp_path
    for step in steps[1:]:
        if step.startswith("cd "):
            cwd = cwd / step[3:]
        elif step.startswith("mkdir"):
            for part in step.split(" && "):
                words = shlex.split(part)
                if words[0] == "mkdir":
                    for d in words[2:]:
                        (cwd / d).mkdir(parents=True, exist_ok=True)
                else:
                    assert words[0] == "mv" and words[-1].endswith("/")
                    for name in words[1:-1]:
                        (cwd / name).rename(cwd / words[-1] / name)
        elif step == "sha256sum -c SHA256SUMS":
            assert _sha256sum_check(cwd) == []
            if shutil.which("sha256sum"):  # the real tool reads the same layout
                real = subprocess.run(["sha256sum", "-c", rm.SUMS], cwd=cwd, capture_output=True, text=True,
                                      stdin=subprocess.DEVNULL)
                assert real.returncode == 0, real.stdout + real.stderr
        else:
            words = shlex.split(step)
            assert words[:2] == ["python3", "../buddie/scripts/release_manifest.py"]
            assert rm.main(words[2:3] + [str(cwd)] + words[4:]) == 0
    # the moves put each file exactly where the manifest says, and nothing else is left in dist/ or bundle/
    assert rm.verify(cwd, V, SHA) == []


def test_the_documented_moves_name_every_file_a_release_carries():
    steps = _documented_steps(V, SHA)
    move = next(s for s in steps if s.startswith("mkdir"))
    for path in rm.expected(V):
        folder, name = path.split("/")
        assert re.search(rf"mv [^&]*\b{re.escape(name)}\b[^&]* {folder}/", move), path


# --- the compact plugin in the candidate (scripts/plugin_package.py) -----------------------------------------------

def test_the_plugin_schema_is_the_builders():
    import plugin_package as pp
    assert rm.PLUGIN_SCHEMA == pp.SCHEMA and rm.PLUGIN_MANIFEST == pp.MANIFEST
    assert f"plugin/{pp.package_name(V)}" in rm.expected(V)


def _rewrite_record(rc):
    """Re-record every file as it is now: a consistent record of a tampered candidate."""
    for name in (rm.MANIFEST, rm.SUMS):
        (rc / name).unlink()
    assert rm.write(rc, V, SHA, "refs/tags/v2.0.0", "tsyyan/buddie", "1") == []


def test_a_plugin_built_from_another_commit_or_version_is_refused(rc):
    bind_plugin(rc, V, "0" * 40)
    _rewrite_record(rc)
    assert any("the plugin was built from" in p for p in rm.verify(rc, V, SHA))
    bind_plugin(rc, V, SHA, claimed="9.9.9")
    _rewrite_record(rc)
    assert any("the plugin is version '9.9.9'" in p for p in rm.verify(rc, V, SHA))


def test_a_swapped_plugin_zip_is_refused_even_when_the_record_is_rewritten(rc):
    (rc / f"plugin/buddie-plugin-{V}.zip").write_bytes(b"another package")
    _rewrite_record(rc)                              # every file hashes as recorded now
    assert "the plugin manifest does not name the recorded ZIP (size, sha256)" in rm.verify(rc, V, SHA)


def test_an_extra_file_in_plugin_is_refused(rc):
    (rc / "plugin" / "notes.txt").write_text("x", encoding="utf-8")
    assert "unexpected plugin/notes.txt" in rm.verify(rc, V, SHA)


def test_notes_cannot_be_rewritten_with_checksums(rc):
    (rc / "metadata/release-notes.md").write_text("changed", encoding="utf-8")
    _rewrite_record(rc)
    assert any("release-notes.md" in p for p in rm.verify(rc, V, SHA))

def test_foreign_registry_payload_is_refused(rc):
    p=rc / "metadata/server.json"
    server=json.loads(p.read_text()); server["version"]="9.9.9"; p.write_text(json.dumps(server))
    _rewrite_record(rc)
    assert any("Registry" in p for p in rm.verify(rc,V,SHA))
