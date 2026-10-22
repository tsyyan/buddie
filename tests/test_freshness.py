"""PR #35: evidence freshness (buddie/freshness.py). Whether evidence is bound to the revision a claim is about,
from immutable identifiers buddie observed: never from a caller's word, a timestamp, or a SHA string alone."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from buddie import cli, freshness, receipts, verify
from buddie.core import Provenance
from buddie.effects import GitHubUnavailable

ROOT = Path(__file__).resolve().parents[1]
A, B, C = "a" * 40, "b" * 40, "c" * 40
REPO = "acme/app"
NOW = "2026-10-23T00:00:00Z"


def clock():
    return NOW


def run(name, conclusion="success", status="completed", sha=A, suite=1):
    return {"name": name, "status": status, "conclusion": conclusion, "head_sha": sha, "check_suite": {"id": suite}}


class GitHub:
    """A GitHub with commits, PRs, check runs and statuses, as a GET function (path -> JSON or None)."""

    def __init__(self):
        self.commits = {A: [run("test"), run("lint")], B: [run("test", "failure", sha=B)]}
        self.statuses = {A: [{"context": "ci/legacy", "state": "success"}]}
        self.pulls = {7: A}
        self.calls = []
        self.down = False

    def __call__(self, path: str):
        self.calls.append(path)
        if self.down:
            raise GitHubUnavailable("GitHub unreachable: test")
        parts = path.split("?")[0].strip("/").split("/")
        if parts[:3] != ["repos", *REPO.split("/")]:
            return None
        rest = parts[3:]
        if rest[0] == "pulls" and int(rest[1]) in self.pulls:
            return {"state": "open", "head": {"sha": self.pulls[int(rest[1])]},
                    "base": {"repo": {"full_name": REPO}}}
        if rest[0] == "commits":
            sha = next((s for s in self.commits if s.startswith(rest[1])), None)
            if sha is None:
                return None
            if len(rest) == 2:
                return {"sha": sha}
            if rest[2] == "check-runs":
                return {"total_count": len(self.commits[sha]), "check_runs": self.commits[sha]}
            if rest[2] == "status":
                return {"sha": sha, "statuses": self.statuses.get(sha, [])}
        return None


@pytest.fixture
def gh():
    return GitHub()


def ci(gh, ref, **kw):
    return freshness.ci_evidence(REPO, ref, gh, clock=clock, **kw)


def pr(gh, n=7):
    return freshness.resolve_pr_head(REPO, n, gh, clock=clock)


def commit(sha, repo=REPO):
    return freshness.claimed("commit", repo, sha)


# --- the required cases ---------------------------------------------------------------------------------------------

def test_the_stale_ci_scenario_ci_passed_on_a_the_pr_moved_to_b(gh):
    """The mission's case: CI passes for A; the agent pushes B; "the PR passed CI" rests on the result for A."""
    before = freshness.assess(pr(gh), ci(gh, A))
    assert (before.state, before.reason) == ("CURRENT", "same_revision")
    gh.pulls[7] = B  # the PR advanced
    after = freshness.assess(pr(gh), ci(gh, A))
    assert (after.state, after.reason) == ("STALE", "different_revision")
    assert after.evidence.details["ci"] == "success"  # genuine, green, and not for this head


@pytest.mark.parametrize("target, evidence, state", [
    ("commit A", A, "CURRENT"), ("commit B", A, "STALE"), ("pr at A", A, "CURRENT"), ("pr at B", A, "STALE"),
    ("pr unavailable", A, "UNKNOWN"), ("commit A", "no sha", "UNKNOWN"), ("historical A", A, "CURRENT"),
])
def test_the_required_table(gh, target, evidence, state):
    if target == "pr at B":
        gh.pulls[7] = B
    t = {"commit A": commit(A), "commit B": commit(B), "historical A": commit(A)}.get(target)
    if t is None:
        t = pr(gh, 99 if target == "pr unavailable" else 7)
    if evidence == "no sha":
        gh.commits[A] = [dict(r, head_sha=None) for r in gh.commits[A]]  # check runs that name no commit
    got = freshness.assess(t, ci(gh, A))
    assert got.state == state, (got.reason, t.reason)


def test_current_does_not_mean_passed_and_stale_does_not_mean_failed(gh):
    failing = freshness.assess(commit(B), ci(gh, B))
    assert failing.state == "CURRENT" and failing.evidence.details["ci"] == "failure"
    green = freshness.assess(commit(B), ci(gh, A))
    assert green.state == "STALE" and green.evidence.details["ci"] == "success"


@pytest.mark.parametrize("change, outcome", [
    (lambda r: dict(r, status="in_progress", conclusion=None), "pending"),
    (lambda r: dict(r, conclusion="cancelled"), "failure"),
    (lambda r: dict(r, conclusion="timed_out"), "failure"),
    (lambda r: dict(r, conclusion="skipped"), "success"),
])
def test_pending_and_cancelled_ci_are_not_success_and_do_not_change_freshness(gh, change, outcome):
    gh.commits[A] = [change(r) for r in gh.commits[A]]
    got = freshness.assess(commit(A), ci(gh, A))
    assert got.state == "CURRENT" and got.evidence.details["ci"] == outcome


def test_a_pending_status_is_pending(gh):
    gh.statuses[A] = [{"context": "deploy", "state": "pending"}]
    assert ci(gh, A).details["ci"] == "pending"


def test_no_ci_results_is_missing_evidence_not_a_success(gh):
    gh.commits[C] = []
    got = freshness.assess(commit(C), ci(gh, C))
    assert (got.state, got.evidence.reason) == ("UNKNOWN", "no_ci_results")
    assert got.evidence.revision is None and got.evidence.details["ci"] == "none"


def test_checks_runs_and_statuses_stay_apart_and_ordered(gh):
    gh.commits[A] = [run("z"), run("a", suite=2), run("a", suite=1)]
    d = ci(gh, A).details
    assert [(r["name"], r["check_suite"]) for r in d["check_runs"]] == [("a", 1), ("a", 2), ("z", 1)]
    assert d["statuses"] == [{"context": "ci/legacy", "state": "success"}]
    assert ci(gh, A, check="ci/legacy").details["ci"] == "success"
    assert ci(gh, A, check="nope").revision is None  # nothing of that name: no evidence


# --- forgery and identity -------------------------------------------------------------------------------------------

def test_a_caller_built_binding_is_not_buddies_observation(gh):
    """Fields are not provenance: a Binding a caller builds with provenance=COLLECTOR_OBSERVED, or one that equals an
    observed one field for field, is the caller's statement."""
    real = ci(gh, A)
    forged = freshness.Binding("github_ci", REPO, A, A, Provenance.COLLECTOR_OBSERVED, details={"ci": "success"})
    copy = freshness.Binding(**{k: getattr(real, k) for k in real.__dataclass_fields__})
    assert freshness.observed(real) and not freshness.observed(forged) and not freshness.observed(copy)
    for evidence in (forged, copy):
        assert freshness.assess(commit(A), evidence).reason == "evidence_not_observed"


def test_a_caller_forged_pr_head_is_not_a_resolved_head(gh):
    forged = freshness.Binding("pr_head", REPO, "#7", A, Provenance.COLLECTOR_OBSERVED)
    assert freshness.assess(forged, ci(gh, A)).reason == "target_not_resolved"
    stated = freshness.claimed("pr_head", REPO, A)
    assert freshness.assess(stated, ci(gh, A)).reason == "target_not_resolved"


def test_a_caller_forged_ci_sha_is_checked_against_every_run(gh):
    """The SHA the evidence names must be the commit GitHub resolves it to, and every run and status must name it."""
    gh.commits[A] = [run("test"), run("other", sha=B)]
    assert ci(gh, A).reason == "inconsistent_answer"
    gh.commits[A] = [run("test")]
    gh.statuses[A] = [{"context": "x", "state": "success"}]
    gh.statuses_sha = B
    real = gh.__call__

    def lying(path):
        data = real(path)
        return dict(data, sha=B) if path.endswith("/status") else data
    assert freshness.ci_evidence(REPO, A, lying, clock=clock).reason == "inconsistent_answer"


def test_a_ref_that_resolves_elsewhere_is_ambiguous(gh):
    """A branch or tag named like a SHA prefix may point at another commit: the evidence is then not that SHA."""
    def branch(path):
        return {"sha": B} if path == f"/repos/{REPO}/commits/aaaaaaa" else gh(path)
    assert freshness.ci_evidence(REPO, "aaaaaaa", branch, clock=clock).reason == "ambiguous_reference"


def test_a_prefix_is_resolved_to_the_full_commit(gh):
    got = ci(gh, "aaaaaaa")
    assert got.revision == A and freshness.assess(commit(A), got).state == "CURRENT"


@pytest.mark.parametrize("sha", ["aaaaaaa", "main", "refs/heads/main", "A" * 40, "", None])
def test_a_target_that_is_no_full_commit_id_is_unknown(gh, sha):
    got = freshness.assess(freshness.claimed("commit", REPO, sha), ci(gh, A))
    assert got.state == "UNKNOWN" and got.reason in ("not_immutable", "target_unresolved")


def test_the_same_sha_in_another_repository_is_not_the_same_revision(gh):
    got = freshness.assess(commit(A, repo="other/fork"), ci(gh, A))
    assert (got.state, got.reason) == ("UNKNOWN", "different_repository")
    assert freshness.assess(commit(A, repo="ACME/App"), ci(gh, A)).state == "CURRENT"  # GitHub names ignore case


def test_a_pr_whose_base_is_another_repository_is_not_resolved(gh):
    def moved(path):
        data = gh(path)
        return dict(data, base={"repo": {"full_name": "someone/else"}}) if "/pulls/" in path else data
    got = freshness.resolve_pr_head(REPO, 7, moved, clock=clock)
    assert got.revision is None and got.reason == "different_repository"


def test_a_result_cannot_be_relabelled_after_it_was_assessed(gh):
    got = freshness.assess(commit(B), ci(gh, A))
    relabelled = freshness.Freshness("CURRENT", "same_revision", got.target, got.evidence)
    with pytest.raises(ValueError):
        freshness.render([relabelled])
    with pytest.raises(Exception):
        got.target.revision = A  # frozen
    assert freshness.render([got])["results"][0]["state"] == "STALE"


# --- resolution failures and malformed answers ----------------------------------------------------------------------

def test_github_errors_and_missing_answers_are_unknown(gh):
    gh.down = True
    assert pr(gh).reason == "github_unavailable" and ci(gh, A).reason == "github_unavailable"
    assert freshness.assess(pr(gh), ci(gh, A)).reason == "target_unresolved"
    gh.down = False
    assert ci(gh, "1234567").reason == "not_found"
    assert freshness.resolve_pr_head(REPO, 7, None, clock=clock, off="network_forbidden").reason == "network_forbidden"


@pytest.mark.parametrize("answer", [[], "x", {"head": "x"}, {"head": {"sha": "short"}, "base": {"repo": {}}},
                                    {"head": {"sha": A}}, {"head": {"sha": 7}}])
def test_malformed_pr_answers_resolve_nothing(answer):
    got = freshness.resolve_pr_head(REPO, 7, lambda p: answer, clock=clock)
    assert got.revision is None and got.reason in ("malformed_answer", "different_repository")


@pytest.mark.parametrize("runs", [[{"name": 1}], ["x"], [{"name": "t", "status": "completed", "head_sha": A}] * 0
                                  + [{"name": "t"}]])
def test_malformed_check_runs_are_no_evidence(gh, runs):
    gh.commits[A] = runs
    assert ci(gh, A).revision is None


@pytest.mark.parametrize("args", [("bad repo", A), (REPO, "zzz"), (REPO, "a" * 6), (REPO, None)])
def test_invalid_requests_are_refused_before_asking(gh, args):
    assert freshness.ci_evidence(*args, gh, clock=clock).reason == "invalid_evidence" and gh.calls == []


def test_no_network_is_asked_when_github_is_off(gh, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("a connection"))
    got = freshness.assess(freshness.resolve_pr_head(REPO, 7, None, clock=clock),
                           freshness.ci_evidence(REPO, A, None, clock=clock))
    assert got.state == "UNKNOWN" and got.target.reason == "github_off"


# --- the local repository and artifacts -----------------------------------------------------------------------------

def git(repo: Path, *args: str) -> str:
    e = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "WINDIR") if k in os.environ}
    e.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "commit.gpgsign=false",
                           "-C", str(repo), *args], env=e, capture_output=True, check=True).stdout.decode().strip()


@pytest.fixture
def repo(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    (r / "a.txt").write_text("one")
    git(r, "add", "a.txt")
    git(r, "commit", "-q", "-m", "one")
    return r


def test_the_checkout_at_the_commit_is_current_and_after_a_commit_stale(repo):
    first = git(repo, "rev-parse", "HEAD")
    target = freshness.claimed("commit", "local", first)
    assert freshness.assess(target, freshness.repository_now(repo)).state == "CURRENT"
    (repo / "a.txt").write_text("two")
    git(repo, "commit", "-qam", "two")
    got = freshness.assess(target, freshness.repository_now(repo))
    assert (got.state, got.reason) == ("STALE", "different_revision")


def test_a_dirty_tree_at_the_commit_is_not_current(repo):
    """A HEAD with other files beside it is not that commit's state: matching HEADs do not prove the files."""
    head = git(repo, "rev-parse", "HEAD")
    (repo / "a.txt").write_text("edited")
    got = freshness.assess(freshness.claimed("commit", "local", head), freshness.repository_now(repo))
    assert got.state == "UNKNOWN" and got.evidence.reason == "dirty_worktree"
    assert got.evidence.details == {"head": head} and got.evidence.provenance is Provenance.AGENT_WRITABLE


def test_not_a_repository_is_unknown(tmp_path):
    got = freshness.assess(freshness.claimed("commit", "local", A), freshness.repository_now(tmp_path))
    assert got.state == "UNKNOWN"


def test_an_artifact_is_current_while_its_bytes_are_the_same(tmp_path):
    import hashlib
    (tmp_path / "app.whl").write_bytes(b"v1")
    digest = hashlib.sha256(b"v1").hexdigest()
    assert freshness.assess_artifact(digest, freshness.artifact_now(tmp_path, "app.whl")).state == "CURRENT"
    (tmp_path / "app.whl").write_bytes(b"v2")
    got = freshness.assess_artifact(digest, freshness.artifact_now(tmp_path, "app.whl"))
    assert (got.state, got.reason) == ("STALE", "different_bytes")
    assert freshness.assess_artifact(digest, freshness.artifact_now(tmp_path, "gone.whl")).state == "UNKNOWN"
    assert freshness.assess_artifact(digest, freshness.artifact_now(tmp_path, "../x")).state == "UNKNOWN"


def test_a_snapshot_is_compared_with_the_repository_now_not_taken_as_evidence(repo, tmp_path, capsys):
    """The snapshot's HEAD and digests are what is compared (the target): the evidence is buddie's observation now,
    so a hand-written snapshot makes nothing current that is not."""
    from buddie import environment
    snap = environment.collect(repo, ["a.txt"], clock=clock)
    path = tmp_path / "snap.json"
    path.write_text(environment.dumps(snap), encoding="utf-8")
    assert cli.main(["freshness", "repo", "--root", str(repo), "--snapshot", str(path)]) == 0
    (repo / "a.txt").write_text("changed")
    git(repo, "commit", "-qam", "changed")
    assert cli.main(["freshness", "repo", "--root", str(repo), "--snapshot", str(path)]) == 1
    out = capsys.readouterr().out
    assert "STALE (different_revision)" in out and "a.txt: freshness STALE (different_bytes)" in out
    forged = json.loads(path.read_text(encoding="utf-8"))
    forged["repository"]["head"]["basis"] = "buddie"  # inconsistent: refused as input
    path.write_text(json.dumps(forged), encoding="utf-8")
    assert cli.main(["freshness", "repo", "--root", str(repo), "--snapshot", str(path)]) == 2


# --- receipts, determinism ------------------------------------------------------------------------------------------

def test_receipts_are_unchanged_and_rendering_asks_nothing(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("freshness ran")
    for name in ("resolve_pr_head", "ci_evidence", "repository_now", "artifact_now", "assess"):
        monkeypatch.setattr(freshness, name, refuse)
    text = f"CI is green `⚓ ci:{REPO}@{A[:7]}=success`\n"
    a = verify.assessment(text, now=NOW, fetch=False, github=None)
    assert receipts.render(a)["predicateType"].endswith("receipt-v0")
    v1 = receipts.render(a, "v1")
    assert receipts.problems(v1) == [] and "freshness" not in json.dumps(v1)
    assert set(receipts.SCHEMA["properties"]["predicate"]["properties"]) == {
        "producer", "checked_at", "verification", "scope", "evidence"}


def test_the_document_is_deterministic(gh):
    one = freshness.dumps(freshness.render([freshness.assess(pr(gh), ci(gh, A))]))
    two = freshness.dumps(freshness.render([freshness.assess(pr(gh), ci(gh, A))]))
    assert one == two and json.loads(one)["format"] == freshness.FORMAT
    doc = json.loads(one)["results"][0]
    assert doc["evidence"]["observed_by_buddie"] is True and doc["target"]["provenance"] == "unknown"  # a test GET


# --- the CLI, against a GitHub of its own ---------------------------------------------------------------------------

@pytest.fixture
def api(gh):
    """gh served over HTTP, for the CLI in a process of its own (BUDDIE_GITHUB_API: buddie's real github_get)."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server's name
            data = gh(self.path)
            body = json.dumps(data).encode()
            self.send_response(200 if data is not None else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    srv.server_close()


def cli_run(api_base, *args, tmp_path=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BUDDIE_", "CLAUDE_PLUGIN_OPTION_"))}
    env.update(BUDDIE_GITHUB_API=api_base)
    p = subprocess.run([sys.executable, "-I", str(ROOT / "run.py"), "freshness", "ci", "--repo", REPO, *args],
                       capture_output=True, env=env, timeout=60)
    return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")


def test_cli_the_stale_ci_regression_end_to_end(gh, api, tmp_path):
    code, out, _ = cli_run(api, "--pr", "7", "--evidence", A[:7])
    assert code == 0 and "freshness CURRENT (same_revision)" in out
    gh.pulls[7] = B
    code, out, _ = cli_run(api, "--pr", "7", "--evidence", A[:7], "--json", str(tmp_path / "f.json"))
    assert code == 1 and "freshness STALE (different_revision)" in out and "success (not a freshness answer)" in out
    doc = json.loads((tmp_path / "f.json").read_text(encoding="utf-8"))
    r = doc["results"][0]
    assert (r["target"]["revision"], r["evidence"]["revision"]) == (B, A)
    # an API the environment named: its answers are taken, and not called collector-observed
    assert r["evidence"]["provenance"] == "unknown"


def test_cli_exit_codes_tell_freshness_failure_missing_and_invalid_apart(gh, api):
    assert cli_run(api, "--commit", B, "--evidence", B)[0] == 0  # current, though the CI failed
    assert cli_run(api, "--commit", A, "--evidence", "1234567")[0] == 3  # no such commit: unknown
    assert cli_run(api, "--pr", "99", "--evidence", A)[0] == 3  # no such PR: unknown
    assert cli_run(api, "--commit", "main", "--evidence", A)[0] == 2  # a branch is no target revision
    assert cli_run(api, "--pr", "7", "--commit", A, "--evidence", A)[0] == 2
    assert cli_run(api, "--commit", A, "--evidence", A, "--no-github")[0] == 3


def test_cli_a_protected_policy_without_network_asks_nothing(gh, tmp_path, monkeypatch, capsys):
    from buddie import effects, policy
    place = tmp_path / "system" / "policy.toml"
    place.parent.mkdir()
    place.write_text('version = 1\nnetwork = "forbidden"\n', encoding="utf-8")
    monkeypatch.setattr(policy, "location", lambda: place)
    monkeypatch.setattr(policy, "protection_problem", lambda p: None)
    monkeypatch.setattr(effects, "github_get", lambda path: pytest.fail("GitHub was asked"))
    assert cli.main(["freshness", "ci", "--repo", REPO, "--pr", "7", "--evidence", A]) == 3
    assert "network_forbidden" in capsys.readouterr().out


def test_cli_verify_exit_codes_are_unchanged(tmp_path):
    report = tmp_path / "r.md"
    report.write_text("nothing to check\n", encoding="utf-8")
    assert cli.main(["verify", str(report), "--no-fetch", "--no-github"]) == 0
