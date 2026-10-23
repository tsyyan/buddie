"""The release candidate's record (scripts/release_manifest.py) and the release workflow's gates (docs/release.md):
the files published are the files the candidate built and recorded, and nothing publishes without the manual,
confirmed run that `authorize` checks."""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import release_manifest as rm  # noqa: E402

V = "2.0.0"
SHA = "b6464a7839274297c5c110ddd1a50557f4281c42"


@pytest.fixture
def rc(tmp_path):
    for path in rm.expected(V):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes(path.encode() * 100)
    assert rm.write(tmp_path, V, SHA, "refs/tags/v2.0.0", "tsyyan/buddie", "1") == []
    return tmp_path


def test_the_record_names_the_commit_and_every_file_by_size_and_sha256(rc):
    record = rm.load(rc)
    assert (record["schema"], record["version"], record["commit"]) == (rm.SCHEMA, V, SHA)
    assert [f["kind"] for f in record["files"]] == ["wheel", "sdist", "mcpb"]
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
    urls = [{"filename": n, "digests": {"sha256": h}} for n, h in files.items() if not n.endswith(".mcpb")]
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
    assert set(jobs) == {"candidate", "authorize", "pypi", "mcp-registry", "github-release"}
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
