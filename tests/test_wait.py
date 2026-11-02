"""buddie wait: poll CI until it is decided, print one line with an anchor that checks."""
from __future__ import annotations

import pytest

from buddie import anchors, cli, freshness, wait
from buddie.freshness import Binding
from buddie.core import Provenance

SHA = "169da519a6f486310fbd81a67d4a1c7fff860886"


def run(name, status="completed", conclusion="success"):
    return {"name": name, "status": status, "conclusion": conclusion if status == "completed" else None}


def ev(*runs, reason=None):
    if reason:
        return Binding("github_ci", "o/r", SHA[:12], None, Provenance.UNKNOWN, reason)
    got = freshness.ci_outcome(list(runs), [])
    return Binding("github_ci", "o/r", SHA[:12], SHA, Provenance.UNKNOWN, None, None,
                   {"ci": got, "check_runs": list(runs), "statuses": [], "duplicates": []})


class Clock:
    def __init__(self):
        self.t, self.slept = 0.0, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def go(monkeypatch, answers, **kw):
    seq = iter(answers)
    monkeypatch.setattr(freshness, "ci_evidence", lambda repo, sha, get: next(seq))
    c = Clock()
    code, line = wait.wait_ci("o/r", SHA[:12], None, sleep=c.sleep, clock=c, **kw)
    return code, line, c


def test_pending_then_success_ends_with_an_anchor_and_backs_off(monkeypatch):
    code, line, c = go(monkeypatch, [ev(run("a", "in_progress")), ev(run("a", "queued"), run("b")),
                                     ev(run("a"), run("b"))])
    assert code == 0 and line.endswith("⚓ `ci:o/r@169da519a6f4=success`") and "after 35s" in line
    assert c.slept == [15, 20]
    assert anchors.ANCHOR.findall(line) == ["ci:o/r@169da519a6f4=success"]


def test_fail_fast_names_the_check_that_failed_while_others_run(monkeypatch):
    code, line, _ = go(monkeypatch, [ev(run("lint", conclusion="failure"), run("test", "in_progress"))])
    assert code == 1 and "⚓ `ci:o/r@169da519a6f4/lint=failure`" in line and "others still running" in line


def test_all_waits_for_every_check(monkeypatch):
    code, line, _ = go(monkeypatch, [ev(run("lint", conclusion="failure"), run("test", "in_progress")),
                                     ev(run("lint", conclusion="failure"), run("test"))], fail_fast=False)
    assert code == 1 and "⚓ `ci:o/r@169da519a6f4=failure`; failed: lint" in line


def test_no_checks_yet_is_waited_for_then_undecided_never_success(monkeypatch):
    code, line, c = go(monkeypatch, [ev(reason="no_ci_results")] * 20, grace=60)
    assert code == 3 and "no checks appeared" in line and "⚓" not in line and c.t >= 60


def test_timeout_says_pending_with_an_anchor_that_holds_now(monkeypatch):
    code, line, _ = go(monkeypatch, [ev(run("a", "in_progress"))] * 50, timeout=100)
    assert code == 3 and "⚓ `ci:o/r@169da519a6f4=pending`" in line and "0 of 1 runs done" in line


def test_github_out_of_reach_ends_at_once(monkeypatch):
    code, line, c = go(monkeypatch, [ev(reason="github_unavailable")])
    assert code == 3 and "out of reach" in line and c.slept == []


def test_a_check_name_that_cannot_stand_in_an_anchor_is_not_put_in_one(monkeypatch):
    code, line, _ = go(monkeypatch, [ev(run("a=b", conclusion="failure"), run("c")), ],)
    assert code == 1 and "⚓ `ci:o/r@169da519a6f4=failure`" in line  # every check done: the whole-commit anchor


def test_cli_refuses_a_target_that_is_neither(capsys):
    assert cli.main(["wait", "not a target"]) == 2
    assert "OWNER/REPO@SHA or OWNER/REPO#N" in capsys.readouterr().out


def test_a_pr_waits_on_its_head_commit(monkeypatch):
    monkeypatch.setattr(freshness, "resolve_pr_head", lambda repo, n, get: Binding(
        "pr_head", repo, f"#{n}", SHA, Provenance.UNKNOWN))
    seen = []
    monkeypatch.setattr(freshness, "ci_evidence", lambda repo, sha, get: seen.append(sha) or ev(run("a")))
    code, line = wait.wait_pr("o/r", 92, None)
    assert code == 0 and seen == [SHA[:12]] and line.startswith("buddie wait: o/r#92: checks on o/r@169da519a6f4")
