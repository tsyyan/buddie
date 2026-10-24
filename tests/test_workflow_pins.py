"""The workflows that build and publish a release run actions at full commit SHAs, never at a tag or branch someone
could move (docs/release.md). The comment beside each SHA names the release it is, for a reader and for updates."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELEASE_PATH = ["release.yml", "release-candidate.yml"]
USES = re.compile(r"(?m)^\s*(?:-\s+)?uses:\s*(\S+)(.*)$")


@pytest.mark.parametrize("name", RELEASE_PATH)
def test_every_action_on_the_release_path_is_pinned_to_a_commit(name):
    text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
    found = USES.findall(text)
    assert found, name
    for ref, rest in found:
        if ref.startswith("./"):
            assert (ROOT / ref).is_file(), ref  # a reusable workflow of this repository, at this commit
            continue
        action, _, at = ref.partition("@")
        assert re.fullmatch(r"[0-9a-f]{40}", at), f"{name}: {ref} is not pinned to a full commit SHA"
        assert re.fullmatch(r"\s+# v\d+\.\d+\.\d+", rest), f"{name}: {ref} has no '# vX.Y.Z' release comment"


def test_one_action_is_pinned_to_one_commit_across_the_release_path():
    seen: dict[str, set[str]] = {}
    for name in RELEASE_PATH:
        for ref, rest in USES.findall((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")):
            if not ref.startswith("./"):
                action, _, at = ref.partition("@")
                seen.setdefault(action, set()).add(f"{at}{rest.strip()}")
    assert {a: s for a, s in seen.items() if len(s) > 1} == {}
    assert "pypa/gh-action-pypi-publish" in seen
