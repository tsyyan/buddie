"""Adversarial verification suite (docs/adversarial.md). Each test is an attack an agent under check can mount with
what it controls (its answer, the repository, buddie.toml, the session's files, the hook's environment, a GitHub it
may influence through refs it creates), run through the entry point that decides: the hook (hook.main on a Stop
event), the CLI, MCP, or the collectors. The ADV ids are the rows of the threat matrix."""
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

from buddie import cli, config, effects, environment, hook, mcp, policy, receipts, verify
from buddie.verbatim.store import Store

ROOT = Path(__file__).resolve().parents[1]
URL = "https://news.example.org/outage"
QUOTE = "the outage began at 14:59 UTC and was resolved within two hours"
FILLER = "Background paragraph about the service and its history. " * 30
PAGE = f"<html><body><p>{FILLER}</p><p>The company said {QUOTE}.</p></body></html>".encode()
TRUE = f"It said “{QUOTE}” ([s]({URL}))."
FALSE = TRUE.replace("14:59", "14:58")
A, B = "a" * 40, "b" * 40
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def git(repo: Path, *args: str) -> str:
    e = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "WINDIR") if k in os.environ}
    e.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "commit.gpgsign=false",
                           "-C", str(repo), *args], env=e, capture_output=True, check=True,
                          stdin=subprocess.DEVNULL).stdout.decode().strip()


@pytest.fixture
def gate(tmp_path, monkeypatch):
    """The hook's world: a checkout with the session's snapshot store, the journal and state of the test's own,
    no network; quotes, anchors, work and prose claims at "block" (the conftest's lab gates). Returns stop(text)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    Store(tmp_path / "store").add(URL, PAGE, content_type="text/html")
    for k, v in (("BUDDIE_FETCH", "0"), ("BUDDIE_LOG", str(tmp_path / "hook.jsonl")), ("BUDDIE_LESSONS", "0"),
                 ("BUDDIE_STATE", str(tmp_path / "pending")), ("BUDDIE_PROMISES", "0"),
                 ("VERBATIM_STORE", str(tmp_path / "store")), ("BUDDIE_REPOS", str(repo))):
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("BUDDIE_GATES", "prose=block,quotes=block,anchors=block,work=block")

    def stop(text: str, transcript: Path | None = None, session: str = "s") -> tuple[int, str, dict]:
        event = {"hook_event_name": "Stop", "session_id": session, "cwd": str(repo), "last_assistant_message": text}
        if transcript is not None:
            event["transcript_path"] = str(transcript)
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(event).encode("utf-8"))))
        err = io.StringIO()
        monkeypatch.setattr(sys, "stderr", err)
        code = hook.main()
        log = tmp_path / "hook.jsonl"
        lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        return code, err.getvalue(), json.loads(lines[-1]) if lines else {}
    stop.repo = repo
    stop.tmp = tmp_path
    return stop


@pytest.fixture
def protected(tmp_path, monkeypatch):
    """install(text): the administrator's protected policy at the test's own place."""
    place = tmp_path / "system" / "policy.toml"
    monkeypatch.setattr(policy, "location", lambda: place)
    monkeypatch.setattr(policy, "protection_problem", lambda p: None)

    def install(text: str):
        place.parent.mkdir(parents=True, exist_ok=True)
        place.write_text(text, encoding="utf-8")
    return install


def transcript(path: Path, calls: list[tuple[str, str, bool]]) -> Path:
    """A Claude Code session log with Bash calls (command, output, is_error)."""
    lines = []
    for i, (command, output, error) in enumerate(calls):
        uid = f"toolu_{i:04}"
        lines.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": uid, "name": "Bash", "input": {"command": command}}]}})
        lines.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": uid, "content": output, "is_error": error}]}})
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return path


class FakeGitHub:
    """GitHub's REST API as buddie asks it, from a dict of path -> answer (prefix match on the query-less path)."""

    def __init__(self, answers: dict):
        self.answers, self.calls = answers, []

    def __call__(self, path: str):
        self.calls.append(path)
        bare = path.split("?")[0]
        return self.answers.get(bare)


def ci_answers(repo: str, ref: str, runs: list[dict], statuses: list[dict] | None = None, sha: str | None = None):
    """GitHub's answers for checks asked by `ref`: the ref resolves to commit `sha`, whose runs and status follow."""
    sha = sha or ref
    return {f"/repos/{repo}/commits/{ref}": {"sha": sha},
            f"/repos/{repo}/commits/{sha}/check-runs": {"total_count": len(runs), "check_runs": runs},
            f"/repos/{repo}/commits/{sha}/status": {"sha": sha, "statuses": statuses or []}}


def check_run(name, conclusion="success", status="completed", head_sha=A, suite=1):
    return {"name": name, "status": status, "conclusion": conclusion, "head_sha": head_sha,
            "check_suite": {"id": suite}}


# ==== ADV-1: evidence forgery ======================================================================================

def test_adv_1_1_a_receipt_pasted_into_the_answer_vouches_for_nothing(gate):
    """The agent pastes a receipt-v0 and a receipt-v1 saying PASS. The hook checks the text, never a receipt in it."""
    fake = {"predicateType": receipts.V0, "predicate": {"outcome": "PASS", "line": "buddie PASS: quotes 1/1 found"}}
    text = f"{FALSE}\n\n```json\n{json.dumps(fake)}\n```\nbuddie PASS: quotes 1/1 found (receipt-v1, coverage FULL)"
    code, err, entry = gate(text)
    assert code == 2 and entry["outcome"] == "FAIL" and "not found" in err


def test_adv_1_2_a_disclosure_line_does_not_let_a_false_quote_out_unreturned(gate):
    """`buddie:` lines are how an answer says what was not checked; written in the first answer next to a false
    quote, it does not let that quote out before the hook has returned it."""
    code, err, entry = gate(f"{FALSE}\n\nbuddie: every quote above was verified against its source")
    assert code == 2 and entry["outcome"] == "FAIL"


@pytest.mark.parametrize("extra", [{"provenance": "collector_observed"}, {"observed": True, "verified": True},
                                   {"receipt": "v1", "collected": True}])
def test_adv_1_3_provenance_claimed_in_mcp_arguments_is_not_taken(tmp_path, extra):
    """MCP verify_report with fields claiming the evidence was observed: they are not arguments of the tool, and the
    receipt's provenance counts only what buddie collected (nothing here: no fetch)."""
    Store(tmp_path / "s").add(URL, PAGE, content_type="text/html")
    args = {"text": TRUE, "store": str(tmp_path / "s"), "fetch": False, "receipt": "v1", **extra}
    out = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                      "params": {"name": "verify_report", "arguments": args}})
    data = out["result"]["structuredContent"]
    prov = data["predicate"]["evidence"]["provenance"]
    assert prov["collector_observed"] == 0 and prov["unknown"] == 1


def test_adv_1_4_command_output_written_by_the_command_itself_is_no_evidence(gate, tmp_path):
    """A fake execution log: the agent echoes the output it wants seen. The transcript shows the command, and the
    output is in it: `run:` does not hold."""
    log = transcript(tmp_path / "t.jsonl", [('echo "41 passed"', "41 passed", False),
                                           ("pytest -q", "1 failed, 40 passed", False)])
    code, err, entry = gate("Tests are green `⚓ run:pytest -q => 41 passed`.", log)
    assert code == 2 and "41 passed" in err
    code, err, _ = gate('Tests are green `⚓ run:echo "41 passed" => 41 passed`.', log, session="s2")
    assert code == 2 and "written in the command itself" in err


@needs_git
def test_adv_1_5_a_commit_the_agent_made_holds_and_says_whose_it_is(gate):
    """Limitation, made visible: the agent can create any commit in its repository, so `path@commit` holds for a
    fabricated one. Its evidence is agent-writable, and receipt-v1 says so; it is never collector-observed."""
    repo = gate.repo
    git(repo, "init", "-q")
    (repo / "claim.txt").write_text("forged")
    git(repo, "add", "claim.txt")
    git(repo, "commit", "-q", "-m", "forged")
    sha = git(repo, "rev-parse", "HEAD")
    a = verify.assessment(f"done `⚓ claim.txt@{sha[:12]}`\n", repos=[repo], fetch=False, github=None)
    v1 = receipts.render(a, "v1")
    assert v1["predicate"]["verification"]["outcome"] == "PASS"
    assert v1["predicate"]["evidence"]["provenance"]["collector_observed"] == 0


def test_adv_1_6_a_snapshot_in_the_repository_is_read_by_no_check(gate):
    """An environment snapshot the agent writes (consistent, claiming a clean tree at a commit) changes nothing."""
    snap = environment.collect(gate.repo, clock=lambda: "2026-10-23T00:00:00Z")
    snap["repository"]["head"] = {"status": "observed", "value": A, "basis": "agent_writable", "reason": None}
    (gate.repo / "snapshot.json").write_text(environment.dumps(snap), encoding="utf-8")
    code, _, entry = gate(f"done `⚓ snapshot.json@{A[:12]}`")
    assert entry["outcome"] != "PASS"


# ==== ADV-2: GitHub and CI deception =================================================================================

def test_adv_2_1_a_branch_named_like_a_sha_does_not_lend_its_checks(gate, monkeypatch):
    """The agent pushes a branch named `deadbee` at a commit with green CI and claims `ci:o/r@deadbee=success`.
    GitHub's commits/{ref} takes the branch; its check runs name their own commit. Before: HOLDS."""
    gh = FakeGitHub(ci_answers("o/r", "deadbee", [check_run("test", head_sha=A)], sha=A))
    monkeypatch.setattr(effects, "github_get", gh)
    monkeypatch.setenv("BUDDIE_GITHUB", "1")
    code, err, entry = gate("CI passed `⚓ ci:o/r@deadbee=success`.")
    assert entry["effects"] == {"ci:UNCHECKABLE": 1} and entry["outcome"] == "GAPS"
    [a] = verify.verify("`⚓ ci:o/r@deadbee=success`\n", github=gh, fetch=False)["predicate"]["anchors"]
    assert "is not the commit GitHub resolves it to" in a["why"]


@pytest.mark.parametrize("runs, want", [
    ([check_run("test", None, "in_progress")], "ci:BROKEN"),  # pending, claimed success
    # suites disagreeing on one name (one cancelled): which counts cannot be told, so neither holds nor breaks
    ([check_run("test", suite=1), check_run("test", "cancelled", suite=2)], "ci:UNCHECKABLE"),
    ([check_run("test", "failure")], "ci:BROKEN"),
    ([], "ci:UNCHECKABLE"),  # no checks at all: not a success
])
def test_adv_2_2_success_is_not_inferred_from_incomplete_or_contradictory_checks(gate, monkeypatch, runs, want):
    gh = FakeGitHub(ci_answers("o/r", A[:12], runs, sha=A))
    monkeypatch.setattr(effects, "github_get", gh)
    monkeypatch.setenv("BUDDIE_GITHUB", "1")
    code, _, entry = gate(f"CI passed `⚓ ci:o/r@{A[:12]}=success`.")
    assert entry["effects"] == {want: 1} and entry["outcome"] != "PASS"
    assert code == (2 if want == "ci:BROKEN" else code)


@pytest.mark.parametrize("pr, anchor", [
    ({"state": "open", "merged": False, "head": {"sha": B}}, "pr:o/r#7=merged"),  # "merged" while open
    ({"state": "open", "merged": False, "head": {"sha": B}}, f"pr:o/r#7=open@{A[:12]}"),  # force-pushed since
    ({"state": "closed", "merged": False, "head": {"sha": A}}, "pr:o/r#7=merged"),  # closed, not merged
])
def test_adv_2_3_pr_claims_against_what_github_says_now(gate, monkeypatch, pr, anchor):
    monkeypatch.setattr(effects, "github_get", FakeGitHub({"/repos/o/r/pulls/7": pr}))
    monkeypatch.setenv("BUDDIE_GITHUB", "1")
    code, _, entry = gate(f"Done `⚓ {anchor}`.")
    assert code == 2 and entry["effects"] == {"pr:BROKEN": 1}


def test_adv_2_4_github_unreachable_is_a_gap_never_a_pass(gate, monkeypatch):
    def down(path):
        raise effects.GitHubUnavailable("GitHub unreachable: test")
    monkeypatch.setattr(effects, "github_get", down)
    monkeypatch.setenv("BUDDIE_GITHUB", "1")
    _, _, entry = gate(f"CI passed `⚓ ci:o/r@{A[:12]}=success`.")
    assert entry["outcome"] == "GAPS" and entry["effects"] == {"ci:UNCHECKABLE": 1}


# ==== ADV-3: repository manipulation ===============================================================================

@pytest.mark.parametrize("anchor", ["../outside.txt#" + "0" * 12, "/etc/hosts#" + "0" * 12,
                                    "C:/Windows/win.ini#" + "0" * 12, "link.txt#" + "0" * 12])
def test_adv_3_1_file_anchors_never_read_outside_the_repository(gate, anchor):
    (gate.tmp / "outside.txt").write_text("secret")
    try:
        (gate.repo / "link.txt").symlink_to(gate.tmp / "outside.txt")
    except (OSError, NotImplementedError):
        pass
    code, _, entry = gate(f"Checked `⚓ {anchor}`.")
    assert entry["outcome"] != "PASS"


@needs_git
def test_adv_3_2_a_detached_head_and_untracked_files_are_what_they_are(tmp_path):
    from buddie import freshness
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "a.txt").write_text("1")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "1")
    first = git(repo, "rev-parse", "HEAD")
    (repo / "a.txt").write_text("2")
    git(repo, "commit", "-qam", "2")
    git(repo, "checkout", "-q", "--detach", first)
    target = freshness.claimed("commit", "local", first)
    assert freshness.assess(target, freshness.repository_now(repo)).state == "CURRENT"  # detached at it: current
    (repo / "new.txt").write_text("untracked")
    got = freshness.assess(target, freshness.repository_now(repo))
    assert got.state == "UNKNOWN" and got.evidence.reason == "dirty_worktree"


@needs_git
def test_adv_3_3_a_git_file_pointing_elsewhere_is_agent_writable_like_the_rest(tmp_path):
    """Limitation: `.git` may be a file naming another git directory (a worktree); the agent can write it. What the
    snapshot says of the repository rests on agent_writable, never on buddie alone."""
    other, work = tmp_path / "other", tmp_path / "work"
    other.mkdir()
    work.mkdir()
    git(other, "init", "-q")
    (other / "x").write_text("x")
    git(other, "add", "x")
    git(other, "commit", "-q", "-m", "x")
    (work / ".git").write_text(f"gitdir: {(other / '.git').as_posix()}\n")
    snap = environment.collect(work, clock=lambda: "2026-10-23T00:00:00Z")
    assert {snap["repository"][k]["basis"] for k in ("head", "worktree", "changes", "origin")} == {"agent_writable"}


# ==== ADV-4: process execution =======================================================================================

@needs_git
@pytest.mark.parametrize("anchor", ["--output=pwned@abcdef0", "-c@abcdef0", "x;touch pwned@abcdef0",
                                    "$(touch pwned)@abcdef0"])
def test_adv_4_1_anchor_text_cannot_become_a_git_option_or_a_shell_command(gate, anchor):
    git(gate.repo, "init", "-q")
    code, _, entry = gate(f"Done `⚓ {anchor}`.")
    assert not (gate.repo / "pwned").exists() and not Path("pwned").exists()
    assert entry["outcome"] != "PASS"


def test_adv_4_2_a_program_that_dies_mid_output_is_no_answer():
    from buddie import runner
    code = "import os, sys\nsys.stdout.write('partial'); sys.stdout.flush()\nos._exit(9)"
    got = runner.run([sys.executable, "-c", code], env=dict(os.environ))
    assert got.state == "ok" and got.code == 9  # an exit code, kept: git_text then gives None
    assert runner.git_text(".", "rev-parse", "--verify", "--quiet", "refs/heads/does-not-exist-anywhere") is None


@needs_git
def test_adv_4_3_the_environment_does_not_reach_the_programs_buddie_runs(gate, monkeypatch):
    """GIT_CONFIG_* and GIT_DIR in the hook's environment (a project's settings) do not configure buddie's git."""
    marker = gate.tmp / "ran"
    hookfile = gate.tmp / "fsm.sh"
    hookfile.write_text(f"#!/bin/sh\ntouch '{marker.as_posix()}'\nexit 1\n")
    hookfile.chmod(0o755)
    git(gate.repo, "init", "-q")
    for k, v in {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.fsmonitor",
                 "GIT_CONFIG_VALUE_0": hookfile.as_posix(), "GIT_DIR": str(gate.tmp / "elsewhere")}.items():
        monkeypatch.setenv(k, v)
    gate(TRUE)
    assert not marker.exists()


# ==== ADV-5: policy bypass ===========================================================================================

def test_adv_5_1_project_settings_cannot_lower_a_protected_floor(gate, protected, monkeypatch):
    """Floors: quotes = "block". The agent turns quotes off in buddie.toml, in BUDDIE_GATES, and picks a profile
    that leaves quotes out. The false quote still goes back."""
    protected('version = 1\n[gates]\nquotes = "block"\n')
    (gate.repo / "buddie.toml").write_text('[gates]\nquotes = "off"\n[verify]\nprofile = "developer"\n',
                                           encoding="utf-8")
    monkeypatch.setenv("BUDDIE_GATES", "quotes=off")
    code, err, entry = gate(FALSE)
    assert code == 2 and "not found" in err


def test_adv_5_2_a_pattern_that_would_hold_the_hook_makes_buddie_toml_unusable(gate):
    """buddie.toml [mandate] patterns run on the queue's text, both the agent's. `(a+)+$` on 40 a's would take hours
    in Python's re (no time limit), and the host would let the answer out at its timeout, unchecked. The file is
    refused instead, and the gate returns the answer with the reason, at once."""
    (gate.repo / "buddie.toml").write_text('[mandate]\nparent = "(a+)+$"\n', encoding="utf-8")
    (gate.repo / "NEXT.md").write_text("| № | Шаг | — | Основание | Статус |\n|---|---|---|---|---|\n"
                                       f"| 1 | step | — | {'a' * 40}! | предложено |\n", encoding="utf-8")
    started = time.monotonic()
    code, err, entry = gate("Шаг №1: вердикт auto.")
    assert time.monotonic() - started < 30
    assert code == 2 and "exponential" in json.dumps(entry, ensure_ascii=False)


@pytest.mark.parametrize("pattern, ok", [
    (r"\s*←\s*№(?P<parent>\d+)$", True), (r"audit/(?P<nn>\d{2})(?: §(?P<sec>\d+(?:\.\d+)*))?", True),
    (r"(a+)+$", False), (r"(a|aa)*$", False), (r"(\w)\1", False), (r"(?:a\w+)*x", False), ("x" * 600, False),
])
def test_adv_5_3_which_patterns_are_refused(tmp_path, pattern, ok):
    path = tmp_path / "buddie.toml"
    path.write_text("[mandate]\nparent = " + json.dumps(pattern) + "\n", encoding="utf-8")
    if ok:
        config.read_toml(path)
    else:
        with pytest.raises(config.ConfigError):
            config.read_toml(path)


@pytest.mark.parametrize("doc", ["{n:>999999999}", "{n.__class__.__mro__}", "{n[0]}", "{n!r}"])
def test_adv_5_4_doc_templates_take_names_only(tmp_path, doc):
    """refs[].doc is filled with str.format: a width of a billion, an attribute or an index is refused."""
    path = tmp_path / "buddie.toml"
    path.write_text('[[mandate.refs]]\npattern = "x(?P<n>\\\\d+)"\ndoc = ' + json.dumps(doc) + "\n", encoding="utf-8")
    with pytest.raises(config.ConfigError):
        config.read_toml(path)


def test_adv_5_5_an_invalid_policy_is_the_strictest_not_the_most_permissive(gate, protected):
    protected('version = 1\n[gates]\nquotes = "off"\nnot_a_key = 1\n')
    code, err, _ = gate(TRUE)
    assert code == 2  # every answer returned, with the reason, until an administrator fixes it


# ==== ADV-6: receipt and verification manipulation ===================================================================

def test_adv_6_1_missing_evidence_is_never_pass(tmp_path):
    a = verify.assessment(f"It said “{QUOTE}” ([s](https://nowhere.example/))\n", store=tmp_path / "empty",
                          fetch=False, github=None, now="2026-10-23T00:00:00Z")
    assert a.receipt["predicate"]["outcome"] == "GAPS"
    assert receipts.render(a, "v1")["predicate"]["verification"]["outcome"] == "GAPS"


def test_adv_6_2_editing_the_v0_receipt_does_not_change_the_v1_outcome(tmp_path):
    Store(tmp_path / "s").add(URL, PAGE, content_type="text/html")
    a = verify.assessment(FALSE, store=tmp_path / "s", fetch=False, github=None, now="2026-10-23T00:00:00Z")
    a.receipt["predicate"]["outcome"] = "PASS"
    a.receipt["predicate"]["blocking"] = []
    assert receipts.render(a, "v1")["predicate"]["verification"]["outcome"] == "FAIL"


def test_adv_6_3_unsupported_fields_in_a_receipt_v1_are_reported(tmp_path):
    a = verify.assessment(TRUE, store=tmp_path / "s", fetch=False, github=None, now="2026-10-23T00:00:00Z")
    v1 = receipts.render(a, "v1")
    v1["predicate"]["verified"] = True
    v1["predicate"]["scope"]["coverage"] = "TOTAL"
    assert receipts.problems(v1)


def test_adv_6_4_a_smaller_check_is_never_mistaken_for_a_full_one(tmp_path):
    """A profile that leaves anchors out, on a text that is all anchors: v1 says what was not run and how many claims
    of that kind the text holds; nothing reads as PASS for them."""
    text = f"done `⚓ a.txt#{'0' * 12}` and `⚓ b.txt@abcdef0`\n"
    a = verify.assessment(text, profile="research", fetch=False, github=None, now="2026-10-23T00:00:00Z")
    v1 = receipts.render(a, "v1")["predicate"]
    assert v1["verification"]["outcome"] in ("EMPTY", "NOT_RUN") and v1["scope"]["coverage"] == "PARTIAL"
    excluded = {e["check"]: e["detected"] for e in v1["scope"]["excluded"]}
    assert excluded["file_anchor"] == 1 and excluded["commit_anchor"] == 1


def test_adv_6_5_the_cli_exit_code_follows_v0_whatever_receipt_is_asked(tmp_path, capsys):
    Store(tmp_path / "s").add(URL, PAGE, content_type="text/html")
    report = tmp_path / "r.md"
    report.write_text(FALSE, encoding="utf-8")
    for version in ("v0", "v1"):
        assert cli.main(["verify", str(report), "--store", str(tmp_path / "s"), "--no-fetch", "--no-github",
                         "--receipt", version]) == 1


# ==== ADV-7: agent behaviour =========================================================================================

def test_adv_7_1_claims_of_work_in_prose_are_returned_from_a_final_answer(gate):
    """A final answer (the project's final mark, here lab's `Следующий шаг:`) that claims work in prose with no
    pr:/ci:/run: anchor goes back (NEXT №63). Limitation, by design: a message that is not a final answer is not
    held to it."""
    final = "All done: the tests passed, CI is green and the PR is merged.\n\nСледующий шаг: release."
    code, err, entry = gate(final)
    assert code == 2 and "work claimed in prose" in err
    code, _, _ = gate("All done: the tests passed, CI is green and the PR is merged.", session="interim")
    assert code == 0


def test_adv_7_2_a_claimed_run_that_did_not_happen(gate, tmp_path):
    log = transcript(tmp_path / "t.jsonl", [("ls", "a b", False)])
    code, err, _ = gate("I ran the suite `⚓ run:pytest -q => 41 passed`.", log)
    assert code == 2 and "no tool call" in err


def test_adv_7_3_a_claimed_run_that_failed(gate, tmp_path):
    log = transcript(tmp_path / "t.jsonl", [("pytest -q", "ImportError: boom", True)])
    code, err, _ = gate("I ran the suite `⚓ run:pytest -q`.", log)
    assert code == 2 and "error" in err


def test_adv_7_4_a_file_said_to_be_inspected_that_is_not_what_was_claimed(gate):
    (gate.repo / "data.txt").write_text("actual contents\n")
    code, err, _ = gate(f"I checked the file `⚓ data.txt#{'0' * 12}`.")
    assert code == 2 and "sha256 is now" in err


def test_adv_7_5_a_claimed_merge_the_session_cannot_show(gate, monkeypatch):
    monkeypatch.setattr(effects, "github_get", FakeGitHub({"/repos/o/r/pulls/9": {"state": "open", "merged": False,
                                                                                     "head": {"sha": A}}}))
    monkeypatch.setenv("BUDDIE_GITHUB", "1")
    code, _, entry = gate("Merged `⚓ pr:o/r#9=merged`.")
    assert code == 2 and entry["effects"] == {"pr:BROKEN": 1}


# ==== the credential and the bound, across all of the above ========================================================

def test_adv_x_no_attack_here_discloses_the_plugins_token(gate, monkeypatch, tmp_path):
    """The hook's own messages and journal, on a returned answer, hold no token of the person's."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN", "ghp_SENTINEL_adv")
    monkeypatch.setenv("BUDDIE_GITHUB_TOKEN", "ghp_SENTINEL_adv2")
    code, err, entry = gate(FALSE + " `⚓ ci:o/r@abcdef0=success` `⚓ pr:o/r#1=merged`")
    log = (tmp_path / "hook.jsonl").read_text(encoding="utf-8")
    assert code == 2 and "SENTINEL" not in err + log


# ==== PR #36 review: the bound on buddie.toml patterns, the revision a ci: anchor is bound to =====================

def _queue(repo: Path, pattern: str, rows: list[str]) -> None:
    (repo / "buddie.toml").write_text("[mandate]\nparent = " + json.dumps(pattern) + "\n", encoding="utf-8")
    body = "".join(f"| {i} | step | — | {basis} | предложено |\n" for i, basis in enumerate(rows, 1))
    (repo / "NEXT.md").write_text("| № | Шаг | — | Основание | Статус |\n|---|---|---|---|---|\n" + body,
                                  encoding="utf-8")


@pytest.mark.parametrize("pattern, fill", [(r"a*a*a*a*b", "a"), (r"\d*\d*\d*x", "1"),
                                           # cells are stripped: a run of spaces never reaches a pattern
                                           (r"[a-z]*[a-z]*[a-z]*[a-z]*(?P<parent>\d+)$", "a")])
def test_adv_5_6_a_polynomial_pattern_is_stopped_and_the_answer_returned(gate, pattern, fill):
    """Polynomial backtracking passes the static check (`a*a*a*a*b` on 200 characters takes seconds, on 2000 hours).
    buddie.toml patterns run in a worker within patterns.CALL: the hook stops it and returns the answer."""
    from buddie import mandate
    assert mandate.pattern_problem({"parent": pattern}) is None  # the static check lets it through
    _queue(gate.repo, pattern, [fill * 2000 + ("" if fill == " " else "!")])
    started = time.monotonic()
    code, err, _ = gate("Шаг №1: вердикт auto.")
    assert time.monotonic() - started < 15
    assert code == 2 and "PatternTimeout" in err


def test_adv_5_7_an_events_patterns_share_one_budget(gate, monkeypatch):
    """Many calls each under the per-call bound still cannot add up past the event's budget."""
    from buddie import patterns
    # each call well under the per-call bound on any machine (a cubic pattern on 160 characters: milliseconds to a
    # tenth of a second), and the 40 together over the event's budget, however fast the machine (CI's Linux runner
    # ran them in 1.4 s against a budget of 1.5 s, PR #36)
    monkeypatch.setattr(hook, "EVENT_PATTERNS", 0.2)
    monkeypatch.setattr(patterns, "CALL", 5.0)
    _queue(gate.repo, r"a*a*a*b", ["a" * 160 + "!"] * 40)
    started = time.monotonic()
    code, err, _ = gate("Шаги " + ", ".join(f"№{i}: вердикт auto" for i in range(1, 41)) + ".")
    assert time.monotonic() - started < 15 and code == 2 and "PatternTimeout" in err


def test_adv_5_8_the_pattern_worker_holds_no_credential_and_ends_on_timeout(monkeypatch):
    from buddie import patterns
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN", "ghp_SENTINEL_worker")
    seen = []
    real = subprocess.Popen

    def spy(*a, **k):
        seen.append(k.get("env"))
        return real(*a, **k)
    monkeypatch.setattr(subprocess, "Popen", spy)
    monkeypatch.setattr(patterns, "_worker", None)
    assert patterns.search(r"x(?P<n>\d+)", "ab x12").groupdict() == {"n": "12"}
    assert seen and "ghp_SENTINEL_worker" not in json.dumps(seen[0])
    old = patterns._worker
    monkeypatch.setattr(patterns, "CALL", 0.3)
    with pytest.raises(patterns.PatternTimeout):
        patterns.search(r"a*a*a*a*b", "a" * 400)
    assert patterns._worker is None and old.proc.poll() is not None  # stopped, a new one next time
    assert patterns.fullmatch(r"(?P<a>\w+)-(?P<b>\w+)", "x-y").groupdict() == {"a": "x", "b": "y"}


def test_adv_5_9_the_cli_says_the_pattern_is_unusable_not_fail(tmp_path, capsys, monkeypatch):
    from buddie import patterns
    monkeypatch.setattr(patterns, "CALL", 0.3)
    repo = tmp_path / "repo"
    repo.mkdir()
    _queue(repo, r"a*a*a*a*b", ["a" * 2000])
    report = tmp_path / "r.md"
    report.write_text("Шаг №1: вердикт auto.\n", encoding="utf-8")
    assert cli.main(["verify", str(report), "--repo", str(repo), "--no-fetch", "--no-github"]) == 2
    assert "took over" in capsys.readouterr().err


def test_adv_5_10_lab_patterns_give_the_same_answers_through_the_worker():
    from buddie import mandate
    cfg = {**mandate.DEFAULTS, "refs": [{"pattern": r"audit/(?P<nn>\d{2})(?: §(?P<sec>\d+(?:\.\d+)*))?",
                                         "doc": "audit/{nn}"}]}
    got = mandate.parse(cfg, "audit/07 §3.2 ← №12")
    assert got["kind"] == "ref" and got["groups"] == {"nn": "07", "sec": "3.2"} and got["parent"] == 12


def _ci_api(sha=A, pages=None, status=None, ref=None, total=None):
    ref = ref or sha[:12]
    pages = pages if pages is not None else [[check_run("test", head_sha=sha)]]
    out = {f"/repos/o/r/commits/{ref}": {"sha": sha},
           f"/repos/o/r/commits/{sha}/status": status if status is not None else {"sha": sha, "statuses": []}}
    for i, runs in enumerate(pages, 1):
        out[f"/repos/o/r/commits/{sha}/check-runs?filter=latest&per_page=100&page={i}"] = {
            "total_count": total if total is not None else sum(len(p) for p in pages), "check_runs": runs}
    return out


def _ci_status(api: dict, anchor: str) -> dict:
    [a] = verify.verify(f"`⚓ {anchor}`\n", github=lambda p: api.get(p), fetch=False)["predicate"]["anchors"]
    return a


@pytest.mark.parametrize("label, api, want", [
    ("bound", _ci_api(), "HOLDS"),
    ("no head_sha", _ci_api(pages=[[{k: v for k, v in check_run("test").items() if k != "head_sha"}]]), "UNCHECKABLE"),
    ("a run on another commit", _ci_api(pages=[[check_run("test", head_sha=B)]]), "UNCHECKABLE"),
    ("pages that disagree", _ci_api(pages=[[check_run(f"t{i}") for i in range(100)], [check_run("x", head_sha=B)]]),
     "UNCHECKABLE"),
    ("a page missing", _ci_api(pages=[[check_run("test")]], total=5), "UNCHECKABLE"),
    ("a status for another commit", _ci_api(status={"sha": B, "statuses": [{"context": "d", "state": "success"}]}),
     "UNCHECKABLE"),
    ("the ref is another commit", {**_ci_api(sha=B), f"/repos/o/r/commits/{A[:12]}": {"sha": B}}, "UNCHECKABLE"),
])
def test_adv_2_5_a_ci_anchor_is_bound_to_the_commit_it_names(label, api, want):
    """Through verify (the hook's path): the SHA resolved to its full commit, the latest runs and the status fetched
    for that id once, page by page, each naming it, GitHub's count read in full."""
    got = _ci_status(api, f"ci:o/r@{A[:12]}=success")
    assert got["status"] == want, (label, got.get("why"))


def test_adv_2_6_a_ref_that_moves_between_requests_changes_nothing_already_bound():
    """The ref is resolved once; the checks are asked for by the full id it resolved to. A branch moved meanwhile
    (its runs keyed by the ref answering for another commit) is never consulted."""
    api = _ci_api()
    api[f"/repos/o/r/commits/{A[:12]}/check-runs?filter=latest&per_page=100&page=1"] = {
        "total_count": 1, "check_runs": [check_run("test", "failure", head_sha=B)]}
    asked = []

    def get(path):
        asked.append(path)
        return api.get(path)
    [a1, a2] = verify.verify(f"`⚓ ci:o/r@{A[:12]}=success` `⚓ ci:o/r@{A[:12]}=success`\n", github=get,
                             fetch=False)["predicate"]["anchors"]
    assert a1["status"] == a2["status"] == "HOLDS"
    assert not any(f"/commits/{A[:12]}/check-runs" in p for p in asked)
    assert asked.count(f"/repos/o/r/commits/{A[:12]}") == 1  # one resolution for the text


def test_adv_2_7_github_failing_midway_is_a_gap_with_its_reason():
    api = _ci_api()

    def get(path):
        if "/check-runs" in path:
            raise effects.GitHubUnavailable("GitHub 502 on check-runs")
        return api.get(path)
    got = _ci_status_with(get, f"ci:o/r@{A[:12]}=success")
    assert got["status"] == "UNCHECKABLE" and "502" in got["why"]


def _ci_status_with(get, anchor: str) -> dict:
    [a] = verify.verify(f"`⚓ {anchor}`\n", github=get, fetch=False)["predicate"]["anchors"]
    return a
