"""Validate the review package offline; never contact GitHub or publish anything.

The authorization proposal (docs/maintenance/proposals) has landed: the test below proves the live workflow is the
reviewed base plus exactly the proposed line. What the gate then does for every run mode is
tests/test_release_authorization.py's.
"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAINTENANCE = ROOT / "docs" / "maintenance"


def test_the_reviewed_authorization_proposal_is_exactly_what_landed():
    """Removing the patch's one added line from the live workflow gives back, byte for byte (LF), the base the
    proposal was reviewed against; the line is there once, in the authorize job."""
    source = json.loads((MAINTENANCE / "proposals/source.json").read_text(encoding="utf-8"))
    patch = (MAINTENANCE / "proposals/authorize-environment.patch").read_text(encoding="utf-8")
    added = [line[1:] for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++")]
    assert added == ["    environment: pypi"]
    live = (ROOT / source["workflow_path"]).read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    marker = "  authorize:\n"
    assert live.count(marker + added[0] + "\n") == 1
    base = live.replace(marker + added[0] + "\n", marker, 1)
    assert hashlib.sha256(base.encode("utf-8")).hexdigest() == source["workflow_sha256_lf"]


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
