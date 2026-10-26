"""Security hardening of buddie's execution boundaries (docs/security.md). Each finding has its exploit reproduced
against what buddie ran before (the same git command, the same inherited environment) and the hook-facing path
shown not to run it, not to disclose the sentinel token, and not to turn what it could not observe into a PASS."""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from buddie import anchors, environment, evidence, hook, mandate, policy, promises, resolved, runner, stores
from buddie.verbatim.store import Store

ROOT = Path(__file__).resolve().parents[1]
SENTINEL = "ghp_SENTINEL_plugin_token_0123456789"
URL = "https://news.example.org/a"
QUOTE = "the outage began at 14:59 UTC and was resolved within two hours"
FILLER = "Background paragraph about the service and its history. " * 30
PAGE = f"<html><body><p>{FILLER}</p><p>The company said {QUOTE}.</p></body></html>".encode()
TEXT = f"It said “{QUOTE}” ([s]({URL}))."
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    e = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "WINDIR") if k in os.environ}
    e.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "commit.gpgsign=false",
                           "-C", str(repo), *args], env=e, capture_output=True, check=True)


def planted(tmp_path: Path, driver: str = "evil") -> tuple[Path, Path]:
    """A repository whose .git/config, the agent's to write, makes `git status` run two commands: a filter driver's
    clean command (for a tracked file whose stat changed) and core.fsmonitor. Each writes its environment to a
    marker. The session's sources/ store (untracked: what changed_sources finds) holds the page the quote is on."""
    repo, marks = tmp_path / "repo", tmp_path / "marks"
    repo.mkdir()
    marks.mkdir()
    git(repo, "init", "-q")
    (repo / "a.txt").write_bytes(b"one\n")
    (repo / ".gitattributes").write_text(f"*.txt filter={driver}\n", encoding="utf-8")
    git(repo, "add", "a.txt", ".gitattributes")
    git(repo, "commit", "-q", "-m", "one")
    hookfile = tmp_path / "fsmonitor.sh"
    hookfile.write_text(f"#!/bin/sh\nenv > '{(marks / 'fsmonitor').as_posix()}'\nexit 1\n")
    hookfile.chmod(0o755)
    git(repo, "config", f"filter.{driver}.clean", f"env > '{(marks / 'filter').as_posix()}'; cat")
    git(repo, "config", "core.fsmonitor", hookfile.as_posix())
    Store(repo / "sources").add(URL, PAGE, content_type="text/html")
    os.utime(repo / "a.txt", (10, 10))  # stat-dirty: git reads it again, through the clean filter
    return repo, marks


def ran(marks: Path) -> dict[str, str]:
    return {p.name: p.read_text(errors="replace") for p in marks.iterdir()}


def hook_env(tmp_path: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BUDDIE_", "VERBATIM_", "CLAUDE_PLUGIN_OPTION_"))}
    env.update(BUDDIE_LOG=str(tmp_path / "hook.jsonl"), BUDDIE_STATE=str(tmp_path / "pending"),
               BUDDIE_INTRO=str(tmp_path / "intro.json"), BUDDIE_SHARED_LOG="0", BUDDIE_GITHUB="0",
               BUDDIE_FETCH="0", BUDDIE_LESSONS="0", BUDDIE_PROMISES="0", BUDDIE_GATES="quotes=block",
               CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN=SENTINEL)
    return env


def run_hook(repo: Path, tmp_path: Path, text: str = TEXT) -> tuple[int, str, dict]:
    """The hook as Claude Code starts it (run.py hook, a Stop event on stdin), in a process of its own with the
    plugin's token in its environment. Returns the exit code, stderr and the journal's line for the event."""
    event = {"hook_event_name": "Stop", "session_id": "s", "cwd": str(repo), "last_assistant_message": text}
    p = subprocess.run([sys.executable, "-I", str(ROOT / "run.py"), "hook"], input=json.dumps(event).encode(),
                       capture_output=True, env=hook_env(tmp_path), cwd=repo, timeout=120)
    lines = (tmp_path / "hook.jsonl").read_text(encoding="utf-8").splitlines() if (tmp_path / "hook.jsonl").exists() \
        else []
    return p.returncode, p.stderr.decode("utf-8", "replace"), json.loads(lines[-1]) if lines else {}


# --- SEC-01: the hook's git status runs what the repository's config names, with the plugin's token --------------

@needs_git
def test_sec01_reproduction_the_old_git_status_runs_planted_commands_with_the_token(tmp_path):
    """What stores.changed_sources ran before: `git -C repo status --porcelain --untracked-files=all` in the hook's
    own environment. The planted commands run and see the plugin's token."""
    repo, marks = planted(tmp_path)
    subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"],
                   env=hook_env(tmp_path), capture_output=True, timeout=60)
    got = ran(marks)
    assert "filter" in got and SENTINEL in got["filter"]  # every git runs a clean filter
    assert "fsmonitor" not in got or SENTINEL in got["fsmonitor"]  # core.fsmonitor hooks: git 2.36 or later


@needs_git
def test_sec01_the_hook_runs_nothing_planted_and_still_finds_the_changed_store(tmp_path):
    repo, marks = planted(tmp_path)
    code, err, entry = run_hook(repo, tmp_path)
    assert ran(marks) == {}  # neither command ran, so the token went nowhere
    assert SENTINEL not in err and SENTINEL not in json.dumps(entry)
    # discovery still works: the quote is judged on the session's own sources/ store (no fetch here), and holds
    assert code == 0 and entry["outcome"] == "PASS" and entry["stores"] >= 1 and "stores_unavailable" not in entry


@needs_git
def test_sec01_a_filter_that_cannot_be_switched_off_is_said_and_never_a_pass(tmp_path):
    repo, marks = planted(tmp_path, driver="a=b")  # "=" in the name: no `-c filter.a=b.clean=` can name it
    code, err, entry = run_hook(repo, tmp_path)
    assert ran(marks) == {}  # git status was not run at all
    assert entry["stores_unavailable"] == ["unneutralized_filter"]
    assert entry["outcome"] != "PASS"  # the store was not found, so the quote was not checked: a gap, not a pass
    # a quote that does not hold goes back with the reason the store list is short
    false = TEXT.replace("14:59", "14:58")
    Store(repo / "sources").add(URL, PAGE, content_type="text/html")
    code, err, entry = run_hook(repo, tmp_path, false)
    assert entry["outcome"] != "PASS" and SENTINEL not in err


@needs_git
@pytest.mark.parametrize("text", [None, 'version = 1\n[gates]\nquotes = "block"\n[evidence]\nrepos = "event"\n'
                                         'collector = "isolated"\n', "version = 9\n"], ids=["absent", "active",
                                                                                           "invalid"])
def test_sec01_holds_under_every_protected_policy_state(tmp_path, monkeypatch, capsys, text):
    """In process, with the policy at the test's own protected place: absent, active and invalid (the strictest
    limits). The hook's git never runs the planted commands and never gets the token."""
    repo, marks = planted(tmp_path)
    place = tmp_path / "system" / "policy.toml"
    monkeypatch.setattr(policy, "location", lambda: place)
    monkeypatch.setattr(policy, "protection_problem", lambda p: None)
    if text is not None:
        place.parent.mkdir()
        place.write_text(text, encoding="utf-8")
    for k, v in hook_env(tmp_path).items():
        monkeypatch.setenv(k, v)
    event = {"hook_event_name": "Stop", "session_id": "s", "cwd": str(repo), "last_assistant_message": TEXT}
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(event).encode("utf-8"))))
    code = hook.main()
    err = capsys.readouterr().err
    assert ran(marks) == {} and SENTINEL not in err
    if text == "version = 9\n":
        assert code == 2  # an invalid policy returns the answer, as before


@needs_git
def test_sec01_changed_sources_reports_why_instead_of_an_empty_success(tmp_path, monkeypatch):
    repo, _ = planted(tmp_path, driver="a=b")
    assert stores.changed_sources_of(repo) == ([], "unneutralized_filter")
    missing: list = []
    stores.session_sources(repo, [repo], unavailable=missing)
    assert missing == [(repo, "unneutralized_filter")]
    monkeypatch.setattr(runner, "git_executable", lambda: None)
    assert stores.changed_sources_of(repo) == ([], "unavailable")
    with policy.snapshot(), evidence.store_for(repo, [repo], None) as (_, chosen):
        assert chosen.unavailable == [(repo, "unavailable")]


@needs_git
def test_sec01_ordinary_changed_and_branch_only_stores_are_still_found(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "x.txt").write_text("x")
    git(repo, "add", "x.txt")
    git(repo, "commit", "-q", "-m", "x")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    Store(repo / "reports" / "r1" / "sources").add(URL, PAGE)  # committed on this branch only
    git(repo, "add", "reports")
    git(repo, "commit", "-q", "-m", "r1")
    Store(repo / "notes" / "sources").add(URL, PAGE)  # untracked
    found, why = stores.changed_sources_of(repo)
    assert why is None
    assert sorted(found) == sorted([repo / "reports" / "r1" / "sources", repo / "notes" / "sources"])


# --- SEC-08: the environment steering which repository git reads --------------------------------------------------

@needs_git
def test_sec08_git_dir_in_the_environment_does_not_choose_the_repository(tmp_path, monkeypatch):
    """GIT_DIR, GIT_CONFIG_* and the like are the hook's environment, which a project's settings can set: before,
    buddie's git took them, so a repository the agent made answered for the event's checkout (here: a commit only
    the fake one has makes `path@commit` hold). buddie's git no longer sees them."""
    real, fake = tmp_path / "real", tmp_path / "fake"
    for r in (real, fake):
        r.mkdir()
        git(r, "init", "-q")
        (r / "a.txt").write_text(r.name)
        git(r, "add", "a.txt")
        git(r, "commit", "-q", "-m", r.name)
    forged = git(fake, "rev-parse", "HEAD").stdout.decode().strip()
    text = f"done `⚓ a.txt@{forged}`\n"
    env = dict(os.environ, GIT_DIR=str(fake / ".git"))
    old = subprocess.run(["git", "-C", str(real), "cat-file", "-e", f"{forged}^{{commit}}"], env=env)
    assert old.returncode == 0  # the reproduction: with the environment's GIT_DIR the forged commit is "there"
    monkeypatch.setenv("GIT_DIR", str(fake / ".git"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.fsmonitor")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(tmp_path / "nothing-to-run"))
    assert [p.resolve() for p in anchors.find_repos(real)] == [real.resolve()]
    [a] = anchors.check_text(text, anchors.find_repos(real))
    assert a["status"] == "UNCHECKABLE" and "no repo has commit" in a["why"]


# --- SEC-09: the launch gate's free command gets the token, and can hold the hook ---------------------------------

def test_sec09_the_free_command_does_not_get_the_plugins_token(tmp_path, monkeypatch):
    script = tmp_path / "free.py"
    seen = tmp_path / "seen.json"
    script.write_text("import json, os, sys\n"
                      f"open(r'{seen}', 'w').write(json.dumps(dict(os.environ)))\n"
                      "print(json.dumps({'free': True, 'reasons': []}))\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN", SENTINEL)
    monkeypatch.setenv("BUDDIE_GITHUB_TOKEN", SENTINEL + "b")
    monkeypatch.setenv("BUDDIE_FREE", f'"{sys.executable}" "{script}" {{n}}')
    with policy.snapshot():
        assert promises.free_now(2, {"repo": str(tmp_path)}, {}) == {"free": True, "reasons": []}
    env = json.loads(seen.read_text())
    assert SENTINEL not in json.dumps(env) and "PATH" in {k.upper() for k in env}  # the rest of the environment stays


def test_sec09_a_free_command_that_leaves_a_child_on_its_output_cannot_hold_the_hook(tmp_path, monkeypatch):
    """Before, a timeout on Windows waited for the output to end (subprocess.run reads it after the kill), and a
    child of the command that kept it open held the hook until the host's own timeout let the answer out."""
    script = tmp_path / "free.py"
    script.write_text("import subprocess, sys\n"
                      "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                      "print('{\"free\": true}', flush=True)\n"
                      "import time; time.sleep(60)\n", encoding="utf-8")
    monkeypatch.setenv("BUDDIE_FREE", f'"{sys.executable}" "{script}" {{n}}')
    monkeypatch.setattr(promises, "FREE_TIMEOUT", 2)
    started = time.monotonic()
    with policy.snapshot():
        assert promises.free_now(2, {"repo": str(tmp_path)}, {}) is None  # no answer in time: not "free"
    assert time.monotonic() - started < 2 + 2 * runner.CLEANUP + 3


# --- SEC-02: output read is bounded, kept or streamed --------------------------------------------------------------

@pytest.mark.parametrize("consume", [None, "count"])
def test_sec02_output_past_the_limit_stops_the_program(consume):
    sink = [0]
    fn = None if consume is None else (lambda chunk: sink.__setitem__(0, sink[0] + len(chunk)))
    got = runner.run([sys.executable, "-c", "import sys\nwhile True: sys.stdout.write('x' * 65536)"],
                     env=dict(os.environ), limit=200_000, consume=fn, timeout=30)
    assert (got.state, got.code) == ("output_limit", None)
    assert len(got.out) <= 200_000 and sink[0] <= 200_000


def test_sec02_a_consumer_can_refuse_the_output():
    got = runner.run([sys.executable, "-c", "print('x' * 10)"], env=dict(os.environ), consume=lambda c: False)
    assert got.state == "output_limit"


def test_sec02_an_entry_with_no_end_is_not_buffered_without_bound():
    hidden = environment._Hidden()
    assert hidden(b"H " + b"x" * 10) is True
    assert hidden(b"y" * environment.MAX_ENTRY) is False  # one entry over the bound: refused, not kept
    found = stores._Stores(Path("r"), status=True)
    assert found(b"?? " + b"z" * stores.MAX_ENTRY) is False


@needs_git
def test_sec02_a_tree_whose_index_listing_is_cut_is_not_shown_clean(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    for i in range(50):
        (repo / f"file-{i:03}.txt").write_text("x")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "files")
    assert environment.repository(repo)[0]["worktree"]["value"] == "clean"
    monkeypatch.setattr(runner, "STREAM", 100)  # the listing of the index is longer than this
    w = environment.repository(repo)[0]["worktree"]
    assert w["status"] == "unavailable" and w["reason"] == "output_limit"


# --- SEC-03: a program's whole tree ends, and the caller always gets an answer in time -----------------------------

def test_sec03_a_grandchild_that_keeps_the_output_open_is_stopped(tmp_path):
    beat = tmp_path / "beat"
    child = (f"import time\nwhile True:\n    open(r'{beat}', 'w').write(str(time.time()))\n    time.sleep(0.2)\n")
    parent = (f"import subprocess, sys\nsubprocess.Popen([sys.executable, '-c', {child!r}])\n"
              "print('parent done', flush=True)\nimport time; time.sleep(60)\n")
    started = time.monotonic()
    got = runner.run([sys.executable, "-c", parent], env=dict(os.environ), timeout=3)
    assert got.state == "timeout" and time.monotonic() - started < 3 + 2 * runner.CLEANUP + 2
    for _ in range(50):
        if beat.exists():
            break
        time.sleep(0.1)
    time.sleep(1)
    last = beat.read_text()
    time.sleep(1.5)
    assert beat.read_text() == last  # the grandchild no longer runs


def test_sec03_a_program_that_closes_its_output_but_runs_on_is_stopped():
    code = "import os, sys, time\nos.close(1)\ntime.sleep(60)"
    started = time.monotonic()
    got = runner.run([sys.executable, "-c", code], env=dict(os.environ), timeout=2)
    assert got.state == "timeout" and time.monotonic() - started < 2 + 2 * runner.CLEANUP + 2


def test_sec03_one_budget_for_every_program_of_an_event():
    with runner.deadline(1.5):
        started = time.monotonic()
        first = runner.run([sys.executable, "-c", "import time; time.sleep(30)"], env=dict(os.environ), timeout=30)
        second = runner.run([sys.executable, "-c", "print(1)"], env=dict(os.environ))
        assert first.state == second.state == "timeout"  # the second never starts: the budget is spent
        assert time.monotonic() - started < 1.5 + 2 * runner.CLEANUP + 2
        with runner.deadline(60):  # an inner, longer budget does not extend the outer one
            assert runner.run([sys.executable, "-c", "print(1)"], env=dict(os.environ)).state == "timeout"
    assert runner.run([sys.executable, "-c", "print(1)"], env=dict(os.environ)) == ("ok", 0, b"1" + os.linesep.encode())


def test_sec03_the_hook_runs_each_event_under_a_budget(monkeypatch):
    seen = []
    monkeypatch.setattr(hook, "run", lambda event: seen.append(runner._DEADLINE.get()) or 0)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{"hook_event_name": "Stop"}')))
    assert hook.main() == 0
    # compared by addition, not subtraction: on Windows monotonic() can return the same tick, and
    # (t + 40.0) - t is 40.00000000000006 for some t (CI on PR #59)
    assert seen and seen[0] is not None and seen[0] <= time.monotonic() + hook.EVENT_PROGRAMS


@needs_git
@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no FIFOs here")
def test_sec03_a_repository_that_blocks_every_git_cannot_hold_the_checks(tmp_path, monkeypatch):
    """A FIFO where git expects a file blocks it on open. Each anchor asks git; together they stay in the budget,
    and each is unchecked, never held."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / ".git" / "HEAD").unlink()
    os.mkfifo(repo / ".git" / "HEAD")
    text = "".join(f"step `⚓ a.txt@{i:07x}0` done\n" for i in range(30))
    monkeypatch.setattr(runner, "TIMEOUT", 1.0)
    started = time.monotonic()
    with runner.deadline(4):
        got = anchors.check_text(text, [repo])
    assert time.monotonic() - started < 4 + 2 * runner.CLEANUP + 5
    assert {a["status"] for a in got} == {"UNCHECKABLE"}


# --- SEC-04: what buddie's git commands can be made to run ---------------------------------------------------------

COMMANDS = {  # every git command buddie runs, as it runs it (name: args, needs filters switched off)
    "stores status": (["status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=all",
                       "--no-renames"], True),
    "stores merge-base": (["merge-base", "HEAD", "HEAD"], False),
    "stores diff": (["diff", "--name-only", "-z", "HEAD~1", "HEAD"], False),
    "anchors cat-file commit": (["cat-file", "-e", "HEAD^{commit}"], False),
    "anchors cat-file path": (["cat-file", "-e", "HEAD:a.txt"], False),
    "anchors find_repos": (["rev-parse", "--show-toplevel"], False),
    "mandate show": (["show", "HEAD:a.txt"], False),
    "mandate log": (["log", "--first-parent", "--format=%H %cI", "HEAD", "--", "a.txt"], False),
    "mandate shallow": (["rev-parse", "--is-shallow-repository"], False),
    "promises head": (["rev-parse", "--verify", "-q", "--short", "HEAD^{commit}"], False),
    "promises show": (["show", "-s", "--format=%H%n%s", "HEAD"], False),
    "promises log grep": (["log", "--all", "-F", "--grep", "two", "-1", "--format=%h"], False),
    "promises remote": (["remote", "get-url", "origin"], False),
    "environment head": (["rev-parse", "--verify", "--quiet", "HEAD^{commit}"], False),
    "environment ls-files": (["ls-files", "-v", "-z"], False),
    "environment remote": (["config", "--get", "remote.origin.url"], False),
}


@pytest.fixture(scope="module")
def armed(tmp_path_factory):
    """A repository whose config names every program git could be asked to run: filters, fsmonitor, textconv, an
    external diff, signature verification, a pager, hooks, an alias over a builtin, ssh and a credential helper."""
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    tmp = tmp_path_factory.mktemp("armed")
    repo, marks = tmp / "repo", tmp / "marks"
    repo.mkdir()
    marks.mkdir()

    def prog(name):
        p = tmp / f"{name}.sh"
        p.write_text(f"#!/bin/sh\ntouch '{(marks / name).as_posix()}'\ncat\n")
        p.chmod(0o755)
        return p.as_posix()
    git(repo, "init", "-q")
    (repo / "a.txt").write_text("one\n")
    (repo / ".gitattributes").write_text("*.txt diff=tc filter=ev\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "one")
    (repo / "a.txt").write_text("two\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "two")
    (repo / "a.txt").write_text("three\n")
    for k, v in {"core.fsmonitor": prog("fsmonitor"), "filter.ev.clean": prog("filter"),
                 "filter.ev.smudge": prog("smudge"), "filter.ev.process": prog("process"),
                 "diff.tc.textconv": prog("textconv"), "diff.external": prog("extdiff"),
                 "log.showSignature": "true", "gpg.program": prog("gpg"), "core.pager": prog("pager"),
                 "core.hooksPath": str(tmp), "alias.status": "!" + prog("alias"), "core.sshCommand": prog("ssh"),
                 "credential.helper": "!" + prog("cred"), "remote.origin.url": "ssh://example.invalid/r.git"}.items():
        git(repo, "config", k, v)
    return repo, marks


@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_sec04_no_command_buddie_runs_executes_what_the_repository_names(armed, name, monkeypatch):
    repo, marks = armed
    for p in marks.iterdir():
        p.unlink()
    os.utime(repo / "a.txt", (100 + len(name), 100 + len(name)))  # stat-dirty for the status run
    for k, v in {"GIT_EXTERNAL_DIFF": str(repo / "x"), "GIT_PAGER": str(repo / "x"), "GIT_SSH_COMMAND": "x",
                 "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.fsmonitor",
                 "GIT_CONFIG_VALUE_0": str(repo / "x")}.items():
        monkeypatch.setenv(k, v)  # what the hook's environment could add: buddie's git sees none of it
    args, filters = COMMANDS[name]
    got = runner.git(repo, *args, filters=filters)
    assert got.state == "ok", got
    assert sorted(p.name for p in marks.iterdir()) == []


def test_sec04_git_gets_nothing_of_buddies_environment_but_where_it_is(monkeypatch):
    for k in ("CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN", "BUDDIE_GITHUB_TOKEN", "GITHUB_TOKEN", "GIT_DIR", "GIT_WORK_TREE",
              "GIT_CONFIG_PARAMETERS", "GIT_EXEC_PATH", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "HTTPS_PROXY", "HOME"):
        monkeypatch.setenv(k, SENTINEL)
    env = runner.git_env()
    assert set(env) <= set(runner.GIT_INHERITED) | set(runner.GIT_ENV) and SENTINEL not in json.dumps(env)
    assert env["GIT_ALLOW_PROTOCOL"] == "none" and env["GIT_CONFIG_GLOBAL"] == os.devnull


def test_sec04_other_programs_get_buddies_environment_without_its_credentials(monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN", SENTINEL)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_OTHER", SENTINEL)
    monkeypatch.setenv("BUDDIE_GITHUB_TOKEN", SENTINEL)
    monkeypatch.setenv("BUDDIE_HTTP_TOKEN", SENTINEL)
    monkeypatch.setenv("SOMETHING_ELSE", "kept")
    env = runner.without_credentials()
    assert SENTINEL not in json.dumps(env) and env["SOMETHING_ELSE"] == "kept"


@needs_git
def test_sec04_the_persons_safe_directory_still_lets_git_read_a_repository(tmp_path, monkeypatch):
    """buddie's git reads no global configuration, except safe.directory, so a checkout another user owns that the
    person allowed (a container's volume) is still read; a repository's own safe.directory is never taken."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "safe.directory", "*")  # ignored by git itself in a repository's own config
    runner.safe_directories.cache_clear()
    try:
        assert "-c" not in runner.safe_directories() or all(
            not v.startswith("safe.directory=" + str(repo)) for v in runner.safe_directories())
    finally:
        runner.safe_directories.cache_clear()


# --- false contradictions: a git that does not answer proves nothing -----------------------------------------------

def test_a_git_that_does_not_answer_never_breaks_a_commit_anchor(tmp_path, monkeypatch):
    answers = iter([0, None])  # the commit is there; the second question gets no answer
    monkeypatch.setattr(anchors, "_git", lambda *a: next(answers))
    [a] = anchors.check_text("x `⚓ a.txt@abcdef0`\n", [tmp_path])
    assert a["status"] == "UNCHECKABLE" and "did not answer" in a["why"]
    monkeypatch.setattr(anchors, "_git", lambda *a: None)
    [a] = anchors.check_text("x `⚓ a.txt@abcdef0`\n", [tmp_path])
    assert a["status"] == "UNCHECKABLE" and "did not answer" in a["why"]


@needs_git
def test_a_git_that_does_not_answer_never_breaks_a_queue_at_a_commit(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    cfg = {**mandate.DEFAULTS, "repo": str(repo)}
    monkeypatch.setattr(runner, "git_executable", lambda: None)
    with pytest.raises(mandate.GitUnavailable):
        mandate.read(cfg, "NEXT.md", "abcdef0")
    got = mandate._missing_rev(cfg, "abcdef0", mandate.GitUnavailable("NEXT.md at abcdef0: git unavailable"))
    assert got["status"] == "UNCHECKABLE"
    monkeypatch.undo()
    got = mandate._missing_rev({**cfg, "repo": str(tmp_path / "not-a-repo")}, "abcdef0", FileNotFoundError("x"))
    assert got["status"] == "UNCHECKABLE"  # git cannot read it: nothing is known of the commit


# --- SEC-07: snapshots are consistent or not; never evidence ---------------------------------------------------------

class Sly(str):
    def __eq__(self, other):
        raise AssertionError("a method of the caller's object ran")

    __hash__ = str.__hash__


@pytest.mark.parametrize("mutate", [
    lambda s: s["repository"]["head"].__setitem__("basis", Sly("agent_writable")),
    lambda s: s["repository"]["head"].__setitem__("status", Sly("observed")),
    lambda s: s["artifacts"].append({"request": 0, "path": ["a"], "status": "observed"}),
    lambda s: s.__setitem__("limitations", [["x"]]),
    lambda s: s["runtime"]["os"].__setitem__("reason", {"a": 1}),
    lambda s: s.__setitem__("supplied", {"k": object()}),
    lambda s: s.__setitem__("collector", {"buddie": "1", "policy": Sly("active")}),
    lambda s: s["repository"].__setitem__("observed_at", 7),
])
def test_sec07_hostile_values_are_reported_without_running_their_methods(tmp_path, mutate):
    snap = environment.collect(tmp_path, clock=lambda: "2026-10-23T00:00:00Z")
    mutate(snap)
    got = environment.problems(snap)
    assert got and all(type(p) is str for p in got)


def test_sec07_a_hand_written_snapshot_is_never_evidence(tmp_path):
    """A consistent snapshot claiming a commit does not make an anchor naming it hold: no check reads snapshots."""
    from buddie import verify
    snap = environment.collect(tmp_path, clock=lambda: "2026-10-23T00:00:00Z")
    snap["repository"]["head"] = {"status": "observed", "value": "a" * 40, "basis": "agent_writable",
                                  "reason": None}
    (tmp_path / "snapshot.json").write_text(environment.dumps(snap), encoding="utf-8")
    receipt = verify.verify(f"`⚓ a.txt@{'a' * 40}`\n", repos=[tmp_path], fetch=False, github=None)
    assert [a["status"] for a in receipt["predicate"]["anchors"]] == ["UNCHECKABLE"]


# --- Phase 5: the hook's verdicts, with the hardening in place ------------------------------------------------------

@needs_git
def test_unavailable_evidence_under_an_observed_only_policy_is_not_a_pass(tmp_path, monkeypatch):
    """stores = "observed" with no fetch: the session's stores do not count, the quote is not checked: a gap."""
    repo, marks = planted(tmp_path)
    place = tmp_path / "system" / "policy.toml"
    place.parent.mkdir()
    place.write_text('version = 1\n[gates]\nquotes = "block"\n[evidence]\nstores = "observed"\n', encoding="utf-8")
    monkeypatch.setattr(policy, "location", lambda: place)
    monkeypatch.setattr(policy, "protection_problem", lambda p: None)
    for k, v in hook_env(tmp_path).items():
        monkeypatch.setenv(k, v)
    with policy.snapshot(), evidence.collector():
        ctx = resolved.resolve({"cwd": str(repo)})
        receipt, chosen, _ = hook.assess_for(TEXT, {"cwd": str(repo)}, ctx=ctx)
    assert receipt["predicate"]["outcome"] == "GAPS" and list(chosen) == [] and ran(marks) == {}
