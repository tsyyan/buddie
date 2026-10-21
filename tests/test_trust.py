"""The repository under check is untrusted: checking its anchors runs none of its code and reads no file outside it
(audit R1, R2)."""
from __future__ import annotations

import hashlib
import io
import os

import pytest

from buddie import anchors, cli, hook, mcp
from buddie.verify import verify

SECRET = b"not for the report\n"
SHA = hashlib.sha256(SECRET).hexdigest()
HELLO = hashlib.sha256(b"hello\n").hexdigest()


@pytest.fixture
def tree(tmp_path):
    """tmp/outside/secret.txt next to tmp/repo/{data.txt, sub/inner.txt}."""
    (tmp_path / "outside").mkdir()
    secret = tmp_path / "outside" / "secret.txt"
    secret.write_bytes(SECRET)
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    (repo / "data.txt").write_bytes(b"hello\n")
    (repo / "sub" / "inner.txt").write_bytes(b"hello\n")
    return repo, secret


def symlink(link, target):
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as e:  # Windows without developer mode
        pytest.skip(f"no symlinks here: {e}")


def status(anchor, repo):
    return anchors.check_text(f"`⚓ {anchor}`", [repo])[0]


# R1: fact= never runs the repository's code

FACTS_PY = """\
from pathlib import Path
Path(__file__).with_name("ran").write_text("the checker ran repository code")
FACTS = {"x.count": None}
def fact(name):
    return 3
"""


@pytest.fixture
def facts_repo(tree):
    repo, _ = tree
    (repo / "tools").mkdir()
    (repo / "tools" / "anchors.py").write_text(FACTS_PY, encoding="utf-8")
    return repo, repo / "tools" / "ran"


def test_a_fact_anchor_runs_no_repository_code(facts_repo):
    repo, ran = facts_repo
    got = status("x.count=3", repo)
    assert got["status"] == "UNCHECKABLE" and "tools/anchors.py" in got["why"]
    assert not ran.exists()


def test_no_entry_point_runs_repository_code(facts_repo, tmp_path, monkeypatch, capsys):
    repo, ran = facts_repo
    text = "Counted. `⚓ x.count=3`\n"
    assert verify(text, repos=[repo], quotes=False)["predicate"]["outcome"] == "GAPS"
    report = tmp_path / "r.md"
    report.write_text(text, encoding="utf-8")
    assert cli.main(["verify", str(report), "--repo", str(repo), "--anchors-only", "--no-github"]) == 0
    capsys.readouterr()
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "verify_report", "arguments": {"text": text, "repos": [str(repo)]}}}
    assert mcp.handle(msg)["result"]["structuredContent"]["predicate"]["outcome"] == "GAPS"
    monkeypatch.setenv("BUDDIE_LOG", str(tmp_path / "hook.jsonl"))
    monkeypatch.setenv("BUDDIE_REPOS", str(repo))
    monkeypatch.setenv("BUDDIE_FETCH", "0")
    monkeypatch.setenv("BUDDIE_GITHUB", "0")
    event = {"hook_event_name": "Stop", "session_id": "s", "cwd": str(repo), "last_assistant_message": text}
    assert hook.run(event, io.StringIO(), io.StringIO()) == 0
    assert not ran.exists()


# R2: a file anchor reads only a regular file inside the repo

def test_a_file_inside_the_repo_still_holds_or_breaks(tree):
    repo, _ = tree
    assert status(f"data.txt#{HELLO[:12]}", repo)["status"] == "HOLDS"
    assert status(f"sub/inner.txt#{HELLO[:12]}", repo)["status"] == "HOLDS"
    assert status(f"./sub/inner.txt#{HELLO[:12]}", repo)["status"] == "HOLDS"
    assert status(f"data.txt#{'0' * 12}", repo)["status"] == "BROKEN"


@pytest.mark.parametrize("path", ["../outside/secret.txt", "sub/../../outside/secret.txt", "..\\outside\\secret.txt",
                                  "sub/..\\../outside/secret.txt", "ABSOLUTE"])
@pytest.mark.parametrize("sha", [SHA[:12], "0" * 12])
def test_a_path_out_of_the_repo_is_not_read(tree, path, sha):
    repo, secret = tree
    path = secret.as_posix() if path == "ABSOLUTE" else path
    got = status(f"{path}#{sha}", repo)
    # a right hash would HOLD and a wrong one would print the secret's hash: neither may happen
    assert got["status"] == "UNCHECKABLE" and SHA[:12] not in got["why"]


def test_a_symlink_out_of_the_repo_is_not_followed(tree):
    repo, secret = tree
    symlink(repo / "link.txt", secret)
    symlink(repo / "linkdir", secret.parent)
    for anchor in (f"link.txt#{SHA[:12]}", f"link.txt#{'0' * 12}", f"linkdir/secret.txt#{SHA[:12]}"):
        got = status(anchor, repo)
        assert got["status"] == "UNCHECKABLE" and "outside" in got["why"] and SHA[:12] not in got["why"]


def test_a_symlink_inside_the_repo_is_followed(tree):
    repo, _ = tree
    symlink(repo / "alias.txt", repo / "sub" / "inner.txt")
    symlink(repo / "subalias", repo / "sub")
    assert status(f"alias.txt#{HELLO[:12]}", repo)["status"] == "HOLDS"
    assert status(f"subalias/inner.txt#{HELLO[:12]}", repo)["status"] == "HOLDS"


def test_a_missing_file_or_a_directory_is_unchecked(tree):
    repo, _ = tree
    assert status(f"gone.txt#{HELLO[:12]}", repo)["status"] == "UNCHECKABLE"
    assert status(f"sub#{HELLO[:12]}", repo)["status"] == "UNCHECKABLE"


def test_an_unchecked_path_never_passes(tree, tmp_path):
    repo, secret = tree
    for anchor in (f"../outside/secret.txt#{SHA[:12]}", f"{secret.as_posix()}#{SHA[:12]}"):
        pred = verify(f"Done. `⚓ {anchor}`\n", repos=[repo], quotes=False)["predicate"]
        assert pred["outcome"] == "GAPS" and pred["blocking"] == []


def test_a_hard_link_to_a_file_outside_is_not_read(tree):
    repo, secret = tree
    try:
        os.link(secret, repo / "hard.txt")
    except OSError as e:
        pytest.skip(f"no hard links here: {e}")
    got = status(f"hard.txt#{SHA[:12]}", repo)
    assert got["status"] == "UNCHECKABLE" and SHA[:12] not in got["why"]
