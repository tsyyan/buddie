"""PR #33: environment snapshots (buddie/environment.py). What buddie observes itself is kept apart from what a caller
says, a fact it cannot observe is unavailable and never filled in, and nothing a repository's agent-writable config
names is run while it is observed."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from buddie import environment as env
from buddie import runner

ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-10-23T00:00:00Z"
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
SECRETS = {"GITHUB_TOKEN": "ghp_s3cr3t-env", "BUDDIE_GITHUB_TOKEN": "ghp_s3cr3t-buddie",
           "CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN": "ghp_s3cr3t-plugin", "AWS_SECRET_ACCESS_KEY": "aws-s3cr3t"}


def clock():
    return NOW


def collect(root, names=(), **kw):
    return env.collect(root, names, clock=clock, **kw)


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """git for setting up a test repo, with nothing of this machine's git config."""
    e = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "WINDIR") if k in os.environ}
    e.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "commit.gpgsign=false",
                           "-C", str(repo), *args], env=e, capture_output=True, check=True)


@pytest.fixture
def repo(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    (r / "a.txt").write_bytes(b"one\n")
    git(r, "add", "a.txt")
    git(r, "commit", "-q", "-m", "one")
    return r


def outside_any_repo(path: Path) -> bool:
    return shutil.which("git") is None or subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"], capture_output=True).returncode != 0


# --- the observation model ------------------------------------------------------------------------------------------

def test_a_snapshot_is_consistent_and_says_what_each_fact_rests_on(repo):
    snap = collect(repo, ["a.txt"])
    assert env.problems(snap) == []
    assert snap["format"] == env.FORMAT and snap["collector"]["policy"] == "absent"
    assert {f["basis"] for f in snap["runtime"].values()} == {"buddie"}
    assert {snap["repository"][k]["basis"] for k in ("head", "worktree", "changes", "origin")} == {"agent_writable"}
    assert snap["repository"]["head"]["value"] == git(repo, "rev-parse", "HEAD").stdout.decode().strip()
    [a] = snap["artifacts"]
    assert a["path"] == "a.txt" and a["bytes"] == 4 and a["basis"] == "agent_writable"
    import hashlib
    assert a["sha256"] == hashlib.sha256(b"one\n").hexdigest()


def test_an_artifact_digest_is_a_file_anchor_that_holds(repo):
    """The digest is of the raw bytes, as a file anchor's: a report can carry it as `⚓ path#sha256`."""
    from buddie import verify
    [a] = collect(repo, ["a.txt"])["artifacts"]
    receipt = verify.verify(f"built `⚓ a.txt#{a['sha256']}`\n", repos=[repo], fetch=False, github=None)
    assert [x["status"] for x in receipt["predicate"]["anchors"]] == ["HOLDS"]


def test_empty_and_unavailable_observations_claim_nothing(tmp_path):
    if not outside_any_repo(tmp_path):
        pytest.skip("the temporary directory is inside a git repository")
    snap = collect(tmp_path)
    assert env.problems(snap) == [] and snap["artifacts"] == [] and snap["report"] is None and snap["supplied"] == {}
    for k in ("head", "worktree", "changes", "origin"):
        assert snap["repository"][k] == {"status": "unavailable", "value": None, "basis": "agent_writable",
                                         "reason": "not_a_repository"}
    assert "unavailable" in env.line(snap) or "not_a_repository" in env.line(snap)


def test_repeated_collection_is_byte_for_byte_the_same_and_ordered(repo):
    (repo / "b.txt").write_bytes(b"two")
    (repo / "Z.txt").write_bytes(b"z")
    one = env.dumps(collect(repo, ["b.txt", "../x", "a.txt", "Z.txt", "a.txt"]))
    two = env.dumps(collect(repo, ["b.txt", "../x", "a.txt", "Z.txt"]))
    assert one == two
    paths = [a["path"] for a in json.loads(one)["artifacts"]]
    assert paths == ["Z.txt", "a.txt", "b.txt", None]  # by path, each once; refused ones after, by position


def test_serialization_is_canonical_and_round_trips(repo):
    (repo / "café.txt").write_bytes(b"x")
    snap = collect(repo, ["café.txt"], report="отчёт\n", supplied={"note": "проверено"})
    text = env.dumps(snap)
    assert json.loads(text) == snap and env.dumps(json.loads(text)) == text
    assert "café.txt" in text and "проверено" in text  # UTF-8 as it is
    assert text == json.dumps(snap, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# --- provenance: caller-supplied stays caller-supplied --------------------------------------------------------------

def test_caller_supplied_facts_are_kept_apart_and_never_promoted(repo):
    forged = {"collected": True, "provenance": "collector_observed", "basis": "buddie", "status": "observed",
              "head": "0" * 40, "worktree": "clean", "exit_status": 0, "command": "pytest -q"}
    snap = collect(repo, supplied=forged)
    assert snap["supplied"] == dict(sorted(forged.items()))
    assert snap["repository"]["head"]["value"] != "0" * 40  # the caller's head is not the observed one
    assert snap["repository"]["worktree"]["basis"] == "agent_writable"
    assert snap["collector"] == {"buddie": snap["collector"]["buddie"], "policy": "absent"}
    assert env.problems(snap) == []


@pytest.mark.parametrize("bad", [
    {"Command": "x"}, {"": "x"}, {"k": [1]}, {"k": {"a": 1}}, {"k": float("nan")}, {"k": "x" * 2000},
    {f"k{i}": i for i in range(65)},
])
def test_supplied_facts_outside_the_contract_are_refused(tmp_path, bad):
    with pytest.raises(ValueError):
        collect(tmp_path, supplied=bad)


def test_subclasses_cannot_stand_in_for_plain_values(tmp_path):
    """A str subclass may print as something it is not; a dict subclass may answer items() as it likes."""
    class Sly(str):
        def __str__(self):
            return "observed"

    class Map(dict):
        pass
    with pytest.raises(ValueError):
        collect(tmp_path, supplied={"k": Sly("caller")})
    with pytest.raises(ValueError):
        collect(tmp_path, supplied=Map(k="v"))
    with pytest.raises(ValueError):
        collect(tmp_path, report=Sly("text"))
    [a] = collect(tmp_path, [Sly("a.txt")])["artifacts"]
    assert a["reason"] == "invalid_path" and a["path"] is None


def test_a_hand_edited_snapshot_that_claims_more_than_it_may_is_inconsistent(repo):
    snap = collect(repo, ["a.txt"])
    cases = []
    s = json.loads(env.dumps(snap))
    s["repository"]["head"]["basis"] = "buddie"  # repo facts rest on what the agent can write
    cases.append(s)
    s = json.loads(env.dumps(snap))
    s["artifacts"][0]["basis"] = "collector_observed"
    cases.append(s)
    s = json.loads(env.dumps(snap))
    s["runtime"]["os"] = {"status": "unavailable", "value": "Linux", "basis": "buddie", "reason": "not_reported"}
    cases.append(s)
    s = json.loads(env.dumps(snap))
    s["repository"]["worktree"] = {"status": "observed", "value": None, "basis": "agent_writable", "reason": None}
    cases.append(s)
    s = json.loads(env.dumps(snap))
    s["collector"]["collected"] = True
    cases.append(s)
    s = json.loads(env.dumps(snap))
    s["artifacts"][0]["sha256"] = None  # observed without a digest
    cases.append(s)
    s = json.loads(env.dumps(snap))
    s["repository"]["changes"]["value"] = 3  # "clean" with changes
    cases.append(s)
    for doc in cases:
        assert env.problems(doc), doc


@pytest.mark.parametrize("doc", [None, [], {}, {"format": env.FORMAT}, "snapshot"])
def test_malformed_documents_are_reported(doc):
    assert env.problems(doc)


def test_malformed_collection_inputs_are_errors_not_observations(tmp_path):
    with pytest.raises(ValueError):
        collect(tmp_path / "missing")
    (tmp_path / "f").write_text("x")
    with pytest.raises(ValueError):
        collect(tmp_path / "f")  # a file is not a root
    with pytest.raises(ValueError):
        collect(tmp_path, supplied=[("k", "v")])
    with pytest.raises(ValueError):
        collect(tmp_path, report=b"bytes")


# --- artifacts ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["../outside.txt", "/etc/passwd", "C:\\Windows\\win.ini", "a/../../outside.txt",
                                  "..\\outside.txt", "sub/../../outside.txt", "f.txt:stream", "\\\\server\\share\\x"])
def test_paths_that_lead_out_of_the_root_are_refused_and_not_repeated(tmp_path, name):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside.txt").write_text("secret")
    [a] = collect(root, [name])["artifacts"]
    assert a["status"] == "unavailable" and a["reason"] == "outside_root" and a["path"] is None
    assert a["sha256"] is None and name not in env.dumps(collect(root, [name]))


@pytest.mark.parametrize("name", ["", "a\0b", 7, None])
def test_names_that_are_no_path_are_invalid(tmp_path, name):
    [a] = collect(tmp_path, [name])["artifacts"]
    assert a["reason"] == "invalid_path" and a["path"] is None


def _symlink(link: Path, target: Path, directory: bool = False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("no symlinks here")


def test_a_symlink_out_of_the_root_is_not_followed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("secret")
    (tmp_path / "dir").mkdir()
    (tmp_path / "dir" / "s.txt").write_text("secret")
    _symlink(root / "link.txt", tmp_path / "secret.txt")
    _symlink(root / "d", tmp_path / "dir", directory=True)
    got = {a["request"]: a for a in collect(root, ["link.txt", "d/s.txt"])["artifacts"]}
    assert got[0]["reason"] == got[1]["reason"] == "outside_root"
    assert got[0]["path"] is None and got[1]["sha256"] is None


def test_a_symlink_inside_the_root_is_read_as_the_file_it_names(tmp_path):
    (tmp_path / "real.txt").write_text("x")
    _symlink(tmp_path / "alias.txt", tmp_path / "real.txt")
    [a] = collect(tmp_path, ["alias.txt"])["artifacts"]
    assert a["status"] == "observed"


def test_directories_missing_files_and_hard_links_are_not_observed(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "f.txt").write_text("x")
    try:
        os.link(tmp_path / "f.txt", tmp_path / "hard.txt")
    except OSError:
        pytest.skip("no hard links here")
    got = {a["path"]: a["reason"] for a in collect(tmp_path, ["d", "nope.txt", "hard.txt"])["artifacts"]}
    assert got == {"d": "not_a_plain_file", "nope.txt": "missing", "hard.txt": "not_a_plain_file"}


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                    reason="file modes do not deny reading here")
def test_an_unreadable_file_is_unavailable(tmp_path):
    f = tmp_path / "locked.txt"
    f.write_text("x")
    f.chmod(0)
    try:
        [a] = collect(tmp_path, ["locked.txt"])["artifacts"]
    finally:
        f.chmod(0o600)
    assert a["reason"] == "unreadable" and a["sha256"] is None


def test_oversized_files_and_collections_are_bounded(tmp_path, monkeypatch):
    from buddie import anchors
    for name, size in (("big", 50), ("a", 30), ("b", 30)):
        (tmp_path / name).write_bytes(b"x" * size)
    monkeypatch.setattr(anchors, "MAX_FILE_BYTES", 40)
    monkeypatch.setattr(env, "MAX_TOTAL_BYTES", 50)
    got = {a["path"]: a["reason"] for a in collect(tmp_path, ["big", "a", "b"])["artifacts"]}
    assert got == {"big": "too_large", "a": None, "b": "total_limit"}
    monkeypatch.setattr(env, "MAX_ARTIFACTS", 2)
    snap = collect(tmp_path, ["a", "b", "big"])
    assert len(snap["artifacts"]) == 2 and "artifact_count_limit" in snap["limitations"]


class _ReadingOs:
    """The collector's `os`, with read() changing the file under it: only on a descriptor open on that very file
    (os.path.samestat with the file's identity before the read, not a read size), once, and only in the collector
    (environment.os is replaced; os itself and every other module's reads, git's pipe among them, are untouched)."""

    def __init__(self, path: Path, mutate):
        self._identity, self._mutate, self.triggered = os.stat(path), mutate, 0

    def read(self, fd, n):
        if not self.triggered and os.path.samestat(os.fstat(fd), self._identity):
            self.triggered += 1
            self._mutate()
        return os.read(fd, n)

    def __getattr__(self, name):
        return getattr(os, name)


def _while_reading(monkeypatch, path: Path, mutate) -> _ReadingOs:
    fake = _ReadingOs(path, mutate)
    monkeypatch.setattr(env, "os", fake)
    return fake


def test_the_fault_injection_itself_changes_nothing_when_it_does_nothing(tmp_path, monkeypatch):
    """The control: the same hook with no change gives the digest, so the tests below see the change, not the hook."""
    f = tmp_path / "same.txt"
    f.write_bytes(b"x" * 10)
    fake = _while_reading(monkeypatch, f, lambda: None)
    [a] = collect(tmp_path, ["same.txt"])["artifacts"]
    import hashlib
    assert fake.triggered == 1 and a["status"] == "observed" and a["sha256"] == hashlib.sha256(b"x" * 10).hexdigest()


def test_a_file_that_grows_while_it_is_read_gets_no_digest(tmp_path, monkeypatch):
    f = tmp_path / "log.txt"
    f.write_bytes(b"x" * 10)

    def grow():
        with open(f, "ab") as fh:
            fh.write(b"more")
    fake = _while_reading(monkeypatch, f, grow)
    [a] = collect(tmp_path, ["log.txt"])["artifacts"]
    assert fake.triggered == 1
    assert a["reason"] == "changed_during_read" and a["sha256"] is None and a["bytes"] is None


def test_a_file_truncated_while_it_is_read_gets_no_digest(tmp_path, monkeypatch):
    f = tmp_path / "log.txt"
    f.write_bytes(b"x" * 100)

    def truncate():
        with open(f, "r+b") as fh:
            fh.truncate(3)
    fake = _while_reading(monkeypatch, f, truncate)
    [a] = collect(tmp_path, ["log.txt"])["artifacts"]
    assert fake.triggered == 1 and a["reason"] == "changed_during_read" and a["sha256"] is None


def test_a_file_rewritten_in_place_while_it_is_read_gets_no_digest(tmp_path, monkeypatch):
    """Same length, new bytes: the modification time tells (a change within its granularity would not)."""
    f = tmp_path / "data.bin"
    f.write_bytes(b"a" * 10)
    st = f.stat()

    def rewrite():
        with open(f, "r+b") as fh:
            fh.write(b"b" * 10)
        os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    fake = _while_reading(monkeypatch, f, rewrite)
    [a] = collect(tmp_path, ["data.bin"])["artifacts"]
    assert fake.triggered == 1 and a["reason"] == "changed_during_read" and a["sha256"] is None


def test_a_file_replaced_while_it_is_read_gets_no_digest(tmp_path, monkeypatch):
    """Linux, macOS: renamed over while open, the path names another file afterwards (detected). Windows: an open
    file cannot be renamed over (sharing mode), so there is nothing to detect: the digest is of the one file."""
    f = tmp_path / "out.txt"
    f.write_bytes(b"first")
    (tmp_path / "other").write_bytes(b"other")
    refused = []

    def replace():
        try:
            os.replace(tmp_path / "other", f)
        except PermissionError:
            refused.append(1)
    fake = _while_reading(monkeypatch, f, replace)
    [a] = collect(tmp_path, ["out.txt"])["artifacts"]
    assert fake.triggered == 1
    if os.name == "nt":
        assert refused and a["status"] == "observed" and a["bytes"] == len(b"first")
    else:
        assert not refused and a["reason"] == "changed_during_read" and a["sha256"] is None


def test_a_digest_says_what_was_read_not_what_is_there_now(tmp_path):
    """A file changed after its observation keeps its old digest in the snapshot: stable while read, not since."""
    f = tmp_path / "a.txt"
    f.write_bytes(b"before")
    [a] = collect(tmp_path, ["a.txt"])["artifacts"]
    f.write_bytes(b"after!")
    import hashlib
    assert a["sha256"] == hashlib.sha256(b"before").hexdigest() != hashlib.sha256(f.read_bytes()).hexdigest()


def test_a_platform_without_a_guarded_open_says_so(tmp_path, monkeypatch):
    (tmp_path / "a").write_text("x")
    monkeypatch.setattr(env, "guarded_open", lambda: False)
    snap = collect(tmp_path, ["a"])
    assert snap["limitations"] == ["artifact_open_unguarded"] and env.problems(snap) == []


def test_an_unknown_platform_is_reported_unavailable_not_guessed(tmp_path, monkeypatch):
    import platform
    monkeypatch.setattr(platform, "system", lambda: "")
    monkeypatch.setattr(platform, "machine", lambda: "")
    rt = collect(tmp_path)["runtime"]
    assert rt["os"] == rt["architecture"] == {"status": "unavailable", "value": None, "basis": "buddie",
                                              "reason": "not_reported"}


# --- the repository -------------------------------------------------------------------------------------------------

def test_clean_dirty_and_untracked_working_trees(repo):
    r = collect(repo)["repository"]
    assert (r["worktree"]["value"], r["changes"]["value"]) == ("clean", 0)
    (repo / "a.txt").write_bytes(b"changed\n")
    r = collect(repo)["repository"]
    assert (r["worktree"]["value"], r["changes"]["value"]) == ("dirty", 1)
    git(repo, "checkout", "--", "a.txt")
    (repo / "new.txt").write_text("x")
    r = collect(repo)["repository"]
    assert (r["worktree"]["value"], r["changes"]["value"]) == ("dirty", 1)


def test_a_commit_sha_does_not_say_the_tree_is_clean(repo):
    """head is observed either way; whether the tree differs from it is its own fact."""
    (repo / "a.txt").write_bytes(b"changed\n")
    r = collect(repo)["repository"]
    assert r["head"]["status"] == "observed" and r["worktree"]["value"] == "dirty"


def test_an_index_that_hides_files_from_git_status_is_not_shown_clean(repo):
    (repo / "a.txt").write_bytes(b"changed\n")
    git(repo, "update-index", "--assume-unchanged", "a.txt")
    assert git(repo, "status", "--porcelain").stdout == b""  # git itself shows it clean
    r = collect(repo)["repository"]
    assert r["worktree"] == {"status": "unavailable", "value": None, "basis": "agent_writable",
                             "reason": "index_hides_entries"}


def test_a_repository_without_commits_or_git(tmp_path, monkeypatch):
    if not outside_any_repo(tmp_path):
        pytest.skip("the temporary directory is inside a git repository")
    if shutil.which("git"):
        git(tmp_path, "init", "-q")
        assert collect(tmp_path)["repository"]["head"]["reason"] == "no_commit"
    monkeypatch.setattr(runner, "git_executable", lambda: None)
    r = collect(tmp_path)["repository"]
    assert {r[k]["reason"] for k in ("head", "worktree", "changes", "origin")} == {"git_unavailable"}


def test_a_root_inside_a_repository_says_the_repository_is_wider(repo):
    (repo / "sub").mkdir()
    (repo / "sub" / "x").write_text("x")
    snap = collect(repo / "sub", ["x"])
    assert "repository_wider_than_root" in snap["limitations"] and snap["artifacts"][0]["path"] == "x"


@pytest.mark.parametrize("url, want", [
    ("https://user:ghp_token@github.com/o/r.git", ("https://github.com/o/r.git", None)),
    ("https://github.com/o/r.git?token=x#frag", ("https://github.com/o/r.git", None)),
    ("ssh://git@github.com:22/o/r.git", ("ssh://github.com:22/o/r.git", None)),
    ("git@github.com:o/r.git", ("github.com:o/r.git", None)),
    ("/home/me/src/r", (None, "local_path")),
    ("C:\\Users\\me\\r", (None, "local_path")),
    ("file:///home/me/r", (None, "local_path")),
    ("../r", (None, "local_path")),
    ("https://exa mple\n.com", (None, "unrecognized_url")),
])
def test_the_origin_remote_never_carries_credentials_or_local_paths(url, want):
    assert env.origin_url(url) == want


@needs_git
def test_nothing_the_repositorys_config_names_is_run(repo, tmp_path):
    """.git/config is the agent's to write; git status runs a filter's clean command for a file whose stat changed,
    and core.fsmonitor's hook. Plain git status runs both here (the reproduction); the collector runs neither, so
    a command the agent planted never sees the process that holds the person's token."""
    marks = tmp_path / "marks"
    marks.mkdir()
    hook = tmp_path / "fsmonitor.sh"
    hook.write_text(f"#!/bin/sh\nenv > '{(marks / 'fsmonitor').as_posix()}'\nexit 1\n")
    hook.chmod(0o755)
    (repo / ".gitattributes").write_text("* filter=evil\n")
    git(repo, "add", ".gitattributes")
    git(repo, "commit", "-q", "-m", "attrs")
    git(repo, "config", "filter.evil.clean", f"env > '{(marks / 'filter').as_posix()}'; cat")
    git(repo, "config", "filter.evil.required", "true")
    git(repo, "config", "core.fsmonitor", hook.as_posix())
    os.utime(repo / "a.txt", (10, 10))  # stat-dirty (whole seconds: git may not compare nanoseconds): git reads
    # the file again, through its clean filter
    raw = dict(os.environ, **SECRETS)
    subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], env=raw, capture_output=True)
    ran = sorted(p.name for p in marks.iterdir())
    assert "filter" in ran  # every git runs a clean filter; core.fsmonitor hooks need git 2.36 or later
    if "fsmonitor" not in ran:
        git(repo, "config", "--unset", "core.fsmonitor")
    assert any(SECRETS["CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN"] in (marks / n).read_text() for n in ran)  # the leak
    for p in marks.iterdir():
        p.unlink()
    os.utime(repo / "a.txt", (20, 20))
    with pytest.MonkeyPatch.context() as mp:
        for k, v in SECRETS.items():
            mp.setenv(k, v)
        snap = collect(repo)
    assert list(marks.iterdir()) == []
    assert snap["repository"]["head"]["status"] == "observed"
    assert snap["repository"]["worktree"]["status"] in ("observed", "unavailable")


@needs_git
def test_a_filter_driver_that_cannot_be_switched_off_means_no_git_status(repo, tmp_path):
    mark = tmp_path / "ran"
    git(repo, "config", "filter.a=b.clean", f"touch '{mark.as_posix()}'; cat")
    (repo / ".gitattributes").write_text("* filter=a=b\n")
    os.utime(repo / "a.txt", (10, 10))
    r = collect(repo)["repository"]
    assert r["worktree"]["reason"] == r["changes"]["reason"] == "unneutralized_filter" and not mark.exists()


def test_git_runs_without_a_shell_in_an_environment_of_its_own(repo, monkeypatch):
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("GIT_DIR", str(repo.parent / "elsewhere"))  # buddie's environment does not steer git
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    seen = []
    real = subprocess.Popen

    def spy(argv, **kw):
        seen.append((argv, kw))
        return real(argv, **kw)
    monkeypatch.setattr(subprocess, "Popen", spy)
    runner.safe_directories.cache_clear()  # its own two calls are seen too
    snap = collect(repo)
    assert snap["repository"]["head"]["status"] == "observed"
    assert seen
    for argv, kw in seen:
        assert kw["shell"] is False and isinstance(argv, list) and kw["stdin"] is subprocess.DEVNULL
        assert not any(v in " ".join(kw["env"].values()) for v in SECRETS.values()) and "GIT_DIR" not in kw["env"]
        assert kw["env"]["GIT_ALLOW_PROTOCOL"] == "none" and "HTTPS_PROXY" not in kw["env"]
        if argv[2:4] == ["config", "--system"] or argv[2:4] == ["config", "--global"]:
            # the person's safe.directory entries, read from the system and global config alone
            assert argv[-2:] == ["--get-all", "safe.directory"]
            assert set(kw["env"]) <= set(runner.GIT_INHERITED) | set(runner._CONFIG_PLACES) | set(runner.GIT_ENV)
            continue
        assert set(kw["env"]) <= set(runner.GIT_INHERITED) | set(runner.GIT_ENV)
        assert kw["env"]["GIT_CONFIG_NOSYSTEM"] == "1"
        assert argv[1:3] == ["--no-pager", "-c"] and "core.fsmonitor=" in argv
    assert not any(v in env.dumps(snap) for v in SECRETS.values())


def test_git_is_stopped_at_its_timeout_and_its_output_bound():
    state, code, _ = runner.run([sys.executable, "-c", "import time; time.sleep(30)"], env=dict(os.environ),
                                timeout=0.5)
    assert (state, code) == ("timeout", None)
    state, code, out = runner.run([sys.executable, "-c", "import sys; sys.stdout.write('x' * 100000)"],
                                  env=dict(os.environ), limit=1000)
    assert (state, code) == ("output_limit", None) and len(out) <= 1000


def test_a_snapshot_reaches_no_network(repo, monkeypatch):
    import socket

    def refuse(*a, **k):
        raise AssertionError("a snapshot opened a socket")
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    (repo / "b").write_text("x")
    assert env.problems(collect(repo, ["b"])) == []


# --- secrets ----------------------------------------------------------------------------------------------------------

def test_no_environment_variable_user_or_local_path_is_in_a_snapshot(repo, monkeypatch):
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    text = env.dumps(collect(repo, ["a.txt", str(repo / "a.txt"), "../repo/a.txt"], report="r"))
    assert not any(v in text for v in SECRETS.values())
    assert str(repo) not in text and repo.as_posix() not in text and str(Path.home()) not in text
    import getpass
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - no user name to look for
        user = None
    if user and len(user) > 3:
        # the user name as a value; "root" is also a key of the snapshot, so a key match is not a leak
        assert not re.search(rf'(?<!{{)"{re.escape(user)}"(?!\s*:)', text)


# --- the protected policy -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, status", [(None, "absent"), ('version = 1\n[evidence]\ncollector = "isolated"\n',
                                                              "active"), ("version = 9\n", "invalid")])
def test_the_policy_is_recorded_and_changes_nothing_the_collector_does(tmp_path, monkeypatch, text, status):
    """The collector reads no place a policy could set aside (BUDDIE_REPOS, stores, the journal) and uses no
    network, so a policy, even an invalid one, makes nothing more permissive; its status is recorded."""
    from buddie import policy
    place = tmp_path / "system" / "policy.toml"
    place.parent.mkdir()
    monkeypatch.setattr(policy, "location", lambda: place)
    monkeypatch.setattr(policy, "protection_problem", lambda p: None)
    if text is not None:
        place.write_text(text, encoding="utf-8")
    monkeypatch.setenv("BUDDIE_REPOS", str(tmp_path / "elsewhere"))
    (tmp_path / "f").write_text("x")
    snap = collect(tmp_path, ["f"])
    assert snap["collector"]["policy"] == status and env.problems(snap) == []
    assert [a["status"] for a in snap["artifacts"]] == ["observed"]


def test_a_snapshot_inside_a_hook_event_reads_the_events_policy(tmp_path, monkeypatch):
    from buddie import policy
    with policy.snapshot() as loaded:
        monkeypatch.setattr(policy, "load", lambda *a: (_ for _ in ()).throw(AssertionError("read again")))
        assert collect(tmp_path)["collector"]["policy"] == loaded.status.value


# --- receipts -------------------------------------------------------------------------------------------------------

def _no_collection(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("collected")
    for name in ("collect", "repository", "artifacts", "artifact", "runtime"):
        monkeypatch.setattr(env, name, refuse)


def test_receipts_v0_and_v1_render_without_collecting(monkeypatch, repo):
    from buddie import receipts, verify
    text = "a quote “the system is working as intended” ([x](https://example.com/))\n"
    before = verify.verify(text, now=NOW, fetch=False, github=None)
    a = verify.assessment(text, now=NOW, fetch=False, github=None)
    _no_collection(monkeypatch)
    assert receipts.render(a) == a.receipt and verify.verify(text, now=NOW, fetch=False, github=None) == before
    v1 = receipts.render(a, "v1")
    assert receipts.problems(v1) == [] and "environment" not in json.dumps(v1)


def test_rendering_a_snapshot_does_not_collect_again(repo, monkeypatch):
    snap = collect(repo, ["a.txt"])
    _no_collection(monkeypatch)
    assert env.problems(snap) == [] and env.line(snap) and json.loads(env.dumps(snap)) == snap


def test_verification_does_not_import_or_call_the_collector():
    """Snapshots are a separate document: no check reads one, so a missing snapshot cannot become a PASS."""
    import re
    for mod in ("verify", "receipts", "findings", "core", "hook", "mcp", "remote", "evidence", "resolved"):
        src = (ROOT / "buddie" / f"{mod}.py").read_text(encoding="utf-8")
        assert not re.search(r"^\s*(?:from buddie import [^\n]*\benvironment\b|import buddie\.environment)", src,
                             re.M), mod
        assert not re.search(r"\benvironment\.(?:collect|repository|artifacts?|runtime)\(", src), mod


def test_cli_verify_never_collects(tmp_path, monkeypatch, capsys):
    from buddie import cli
    _no_collection(monkeypatch)
    report = tmp_path / "r.md"
    report.write_text("nothing to check\n", encoding="utf-8")
    assert cli.main(["verify", str(report), "--no-fetch", "--no-github"]) == 0


# --- the CLI --------------------------------------------------------------------------------------------------------

def test_cli_snapshot_pairs_with_the_receipt_of_the_same_report(repo, monkeypatch, capsys):
    from buddie import cli
    monkeypatch.chdir(repo)
    (repo / "report.md").write_bytes(b"line one\r\nline two \xe2\x80\x94 done\r\n")  # CRLF, as Windows writes it
    assert cli.main(["snapshot", "--report", "report.md", "--artifact", "a.txt", "--supply", "command=pytest -q",
                     "--json", "snap.json"]) == 0
    assert capsys.readouterr().out.startswith("buddie snapshot: head ")
    snap = json.loads((repo / "snap.json").read_text(encoding="utf-8"))
    assert env.problems(snap) == [] and snap["supplied"] == {"command": "pytest -q"}
    assert snap["root"] == {"origin": "working_directory"}
    assert cli.main(["verify", "report.md", "--no-fetch", "--no-github", "--json", "r.json"]) == 0
    receipt = json.loads((repo / "r.json").read_text(encoding="utf-8"))
    assert snap["report"]["sha256"] == receipt["subject"][0]["digest"]["sha256"]
    capsys.readouterr()
    assert cli.main(["snapshot", "--root", "."]) == 0
    assert env.problems(json.loads(capsys.readouterr().out)) == []


@pytest.mark.parametrize("argv, why", [
    (["--supply", "novalue"], "KEY=VALUE"), (["--supply", "Bad=1"], "lowercase"), (["--root", "missing"], "root"),
    (["--report", "."], "is a directory"), (["--report", "latin.md"], "not UTF-8"),
])
def test_cli_snapshot_input_errors_exit_2(tmp_path, monkeypatch, capsys, argv, why):
    from buddie import cli
    monkeypatch.chdir(tmp_path)
    (tmp_path / "latin.md").write_bytes(b"\xff\xfe")
    assert cli.main(["snapshot", *argv]) == 2
    err = capsys.readouterr().err
    assert why in err and "Traceback" not in err


# --- PR #32: the GitHub token's name, held -------------------------------------------------------------------------

def test_pr32_the_plugin_mcp_server_gets_the_token_under_the_plugins_own_name():
    """.mcp.json hands the plugin's token setting to the MCP server; under BUDDIE_GITHUB_TOKEN it could go to an API
    the environment names (BUDDIE_GITHUB_API). It must keep the name the hook gets it under."""
    server = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["buddie"]
    named = {k for k, v in server.get("env", {}).items() if "${user_config.github_token}" in v}
    assert named == {"CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN"}


def test_pr32_the_plugins_token_goes_to_github_and_not_where_the_environment_points(tmp_path):
    code = """
import json, sys, urllib.request
sys.path.insert(0, sys.argv[1])
asked = []
class Answer:
    def __init__(self, url): self.url = url
    def read(self, *a): return b"{}"
    def geturl(self): return self.url
    def __enter__(self): return self
    def __exit__(self, *a): return False
def urlopen(req, timeout):
    asked.append([req.full_url, req.get_header("Authorization") or req.unredirected_hdrs.get("Authorization")])
    return Answer(req.full_url)
urllib.request.urlopen = urlopen
from buddie import effects
try:
    effects.github_get("/repos/o/r/pulls/1")
except Exception:
    pass
print(json.dumps(asked))
"""
    base = {k: v for k, v in os.environ.items() if not k.startswith(("BUDDIE_", "CLAUDE_PLUGIN_OPTION_"))}
    plugin = dict(base, CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN="pers0nal")
    pointed = subprocess.run([sys.executable, "-I", "-c", code, str(ROOT)], capture_output=True, text=True, check=True,
                             env=dict(plugin, BUDDIE_GITHUB_API="https://agent.example")).stdout
    [[url, auth]] = json.loads(pointed)
    assert url.startswith("https://agent.example/") and auth is None
    default = subprocess.run([sys.executable, "-I", "-c", code, str(ROOT)], capture_output=True, text=True,
                             check=True, env=plugin).stdout
    [[url, auth]] = json.loads(default)
    assert url.startswith("https://api.github.com/") and auth == "Bearer pers0nal"
