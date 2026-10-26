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


# The one reviewed change to release.yml since the proposal: the 2.0.0 release commit pinned each action to the
# commit its tag named then (tests/test_workflow_pins.py). Each pin, back to the reference it replaced.
PINNED_SINCE_PROPOSAL = {
    "actions/checkout@11d5960a326750d5838078e36cf38b85af677262  # v4.4.0": "actions/checkout@v4",
    "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093  # v4.3.0": "actions/download-artifact@v4",
    "pypa/gh-action-pypi-publish@7245906fb61fa33a13554f9d5fb856fe61758086  # v1.14.3":
        "pypa/gh-action-pypi-publish@release/v1",
}


def unapply(text: str, patch: str) -> str:
    """`text` with the unified diff `patch` taken back out, exactly: every hunk's new lines must be where the hunk
    says, and are replaced by its old lines. AssertionError when the patch does not match `text` byte for byte."""
    lines = text.split("\n")
    hunks = re.split(r"(?m)^(?=@@ )", patch)[1:]
    for hunk in reversed(hunks):
        head, *body = hunk.rstrip("\n").split("\n")
        start = int(re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", head)[1]) - 1
        new = [b[1:] for b in body if b[:1] in (" ", "+")]
        old = [b[1:] for b in body if b[:1] in (" ", "-")]
        assert lines[start:start + len(new)] == new, f"the patch does not match the workflow at line {start + 1}"
        lines[start:start + len(new)] = old
    return "\n".join(lines)


def test_the_plugin_stable_proposal_is_the_only_other_change():
    """The compact-plugin release PR's change to release.yml is exactly proposals/plugin-stable.patch: taken back
    out, the workflow is main's at the proposal's base, which the test below then checks as before."""
    proposal = json.loads((MAINTENANCE / "proposals/plugin-stable.json").read_text(encoding="utf-8"))
    patch = (MAINTENANCE / "proposals" / proposal["patch"]).read_text(encoding="utf-8").replace("\r\n", "\n")
    assert proposal["workflow_path"] == ".github/workflows/release.yml" and "requires the owner" in proposal["status"]
    live = (ROOT / proposal["workflow_path"]).read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    live = unapply(live, (MAINTENANCE / "proposals/public-release-metadata.patch").read_text(encoding="utf-8"))
    base = unapply(live, patch)
    assert "plugin-stable" not in base and "create_branch" not in base


def test_the_reviewed_authorization_proposal_is_exactly_what_landed():
    """Removing the patch's one added line from the live workflow, and undoing the action pins of the 2.0.0 release
    commit, gives back, byte for byte (LF), the base the proposal was reviewed against; the line is there once, in
    the authorize job. Any other change to release.yml fails here, but the plugin-stable proposal, taken back out
    exactly first (test above)."""
    source = json.loads((MAINTENANCE / "proposals/source.json").read_text(encoding="utf-8"))
    patch = (MAINTENANCE / "proposals/authorize-environment.patch").read_text(encoding="utf-8")
    added = [line[1:] for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++")]
    assert added == ["    environment: pypi"]
    live = (ROOT / source["workflow_path"]).read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    live = unapply(live, (MAINTENANCE / "proposals/public-release-metadata.patch").read_text(encoding="utf-8"))
    proposal = json.loads((MAINTENANCE / "proposals/plugin-stable.json").read_text(encoding="utf-8"))
    live = unapply(live, (MAINTENANCE / "proposals" / proposal["patch"]).read_text(encoding="utf-8")
                   .replace("\r\n", "\n"))
    for pinned, floating in PINNED_SINCE_PROPOSAL.items():
        assert f"uses: {pinned}\n" in live, pinned
        live = live.replace(f"uses: {pinned}\n", f"uses: {floating}\n")
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
