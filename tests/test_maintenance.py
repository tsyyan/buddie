"""Validate the review package offline; never contact GitHub or publish anything.

The proposed patch is applied only to a temporary copy. Retire or refresh that proposal
test when the separately approved workflow change lands.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAINTENANCE = ROOT / "docs" / "maintenance"


def _jobs(text):
    """Read top-level job blocks from this workflow, not a general YAML parser."""
    pairs = list(re.finditer(r"(?m)^  ([\w-]+):\s*$", text.split("jobs:\n", 1)[1]))
    body = text.split("jobs:\n", 1)[1]
    return {m[1]: body[m.end():pairs[i + 1].start() if i + 1 < len(pairs) else len(body)]
            for i, m in enumerate(pairs)}


@pytest.fixture
def proposal(tmp_path):
    workflow = ROOT / ".github/workflows/release.yml"
    patch = MAINTENANCE / "proposals/authorize-environment.patch"
    assert patch.is_file(), "the reviewable, unapplied authorization proposal is missing"
    target = tmp_path / ".github/workflows/release.yml"
    target.parent.mkdir(parents=True)
    target.write_text(workflow.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    before = workflow.read_bytes()
    result = subprocess.run(["git", "apply", "-"], cwd=tmp_path,
                            input=patch.read_text(encoding="utf-8").encode("utf-8"), capture_output=True)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert workflow.read_bytes() == before, "proposal validation modified the live workflow"
    return workflow.read_text(encoding="utf-8"), target.read_text(encoding="utf-8")


def test_proposal_changes_only_the_existing_authorization_job(proposal):
    current, proposed = proposal
    marker = "  authorize:\n"
    assert proposed == current.replace(marker, marker + "    environment: pypi\n", 1)
    old, new = _jobs(current), _jobs(proposed)
    assert set(old) == set(new)
    assert all(old[j] == new[j] for j in old if j != "authorize")
    assert "environment:" not in new["candidate"]
    assert "github.event_name == 'workflow_dispatch' && inputs.candidate != ''" in new["authorize"]
    assert "python3 scripts/release_publish.py authorize" in new["authorize"]
    assert "id-token: write" not in new["authorize"]


@pytest.mark.parametrize("stage", ["pypi", "mcp-registry", "github-release"])
def test_every_publication_route_depends_on_the_approved_authorizer(proposal, stage):
    _, proposed = proposal
    jobs = _jobs(proposed)
    assert "    environment: pypi\n" in jobs["authorize"]
    dependency = re.search(r"(?m)^    needs: (.+)$", jobs[stage])[1]
    assert "authorize" in dependency
    if stage == "pypi":
        # Default dependency success applies: no always() escape on this job.
        assert "always()" not in jobs[stage]
        assert "name: pypi" in jobs[stage]  # preserve the trusted-publisher environment
    else:
        # Recovery explicitly permits a skipped PyPI job, but cannot skip authorization success.
        assert "needs.authorize.result == 'success'" in jobs[stage]
        assert "needs.pypi.result == 'skipped'" in jobs[stage]
        assert f"inputs.only == '{stage}'" in jobs[stage]


def test_deletion_manifest_excludes_moved_and_active_branches():
    data = json.loads((MAINTENANCE / "post-merge-branches.json").read_text(encoding="utf-8"))
    manifest = json.loads((MAINTENANCE / "deletion-manifest.json").read_text(encoding="utf-8"))
    rows = {r["branch"]: r for r in data["branches"]}
    assert manifest["approved"] is False
    assert len(manifest["candidates"]) == len({r["branch"] for r in manifest["candidates"]})
    assert {r["branch"] for r in manifest["candidates"]} == {
        n for n, r in rows.items() if r["recommendation"] == "DELETE"}
    for item in manifest["candidates"]:
        row = rows[item["branch"]]
        assert re.fullmatch(r"[a-f0-9]{40}", item["sha"])
        assert row["sha"] == item["sha"]
        assert not row["moved_since_original_audit"]
        assert not row["open_pr_dependencies"]
        assert row["represented_in_main"]
        assert row["tip_ancestor_of_main"] or any(
            p["reachable_from_main"] and p["tip_matches_pr_head"] and p["tip_tree_equals_merge"]
            for p in row["merge_proofs"])
    assert rows["pre-release-maintenance-2026-10-24"]["recommendation"] == "KEEP"
    assert rows["release-candidate-2.0"]["recommendation"] == "INVESTIGATE"


def test_community_document_links_and_new_documentation_navigation():
    paths = [ROOT / "SECURITY.md", ROOT / "CONTRIBUTING.md", ROOT / "docs/README.md",
             ROOT / ".github/pull_request_template.md"]
    for file in paths:
        for target in re.findall(r"\]\(([^)\s]+)\)", file.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            assert (file.parent / target.split("#")[0]).exists(), (file, target)
    index = paths[2].read_text(encoding="utf-8")
    for guide in ("claude-code.md", "configuration.md", "distribution.md", "research.md"):
        assert f"]({guide})" in index, f"index is missing the guide added by PR #38: {guide}"
