"""`buddie wait`: wait for CI without spending an agent's turns, and end with an anchor that checks.

An agent that pushed and has to know whether CI passed either sleeps and polls in its own turns (every poll is a
model turn and its output in the context) or stops and is never told. `buddie wait ci OWNER/REPO@SHA` (or
`buddie wait pr OWNER/REPO#N`, the PR's head commit) polls GitHub itself, prints nothing while it waits, and ends with
one line holding a ready anchor:

    buddie wait: checks on octo/app@9653a7c1d2e4 ended success after 6m12s (11 checks) ⚓ `ci:octo/app@9653a7c1d2e4=success`
    buddie wait: check 'test (3.12)' on octo/app@9653a7c1d2e4 ended failure after 2m03s ⚓ `ci:octo/app@9653a7c1d2e4/test (3.12)=failure`

Run it in the background (Claude Code: a background Bash command wakes the agent when it exits), and the agent takes
no turn until the result is there. The anchor is checked again by verify_report and the hook like any ci: anchor.

What counts is freshness.ci_evidence, the same as for a ci: anchor: the SHA resolved to the commit GitHub has, the
latest check runs and statuses on it. Fail fast (the default): the first check that ended badly ends the wait with an
anchor on that check alone, while the others may still run. A commit with no checks yet is waited for during
`--grace` (CI may not have started); after it the wait ends undecided, never as success.

Exit codes: 0 success, 1 failure, 3 undecided (still pending at --timeout, no checks, GitHub out of reach, ambiguous).
"""
from __future__ import annotations

import re
import time

from buddie import freshness

TARGET_CI = re.compile(r"^(?:ci:)?(?P<repo>[\w.-]+/[\w.-]+)@(?P<sha>[0-9a-f]{7,40})$")
TARGET_PR = re.compile(r"^(?:pr:)?(?P<repo>[\w.-]+/[\w.-]+)#(?P<number>\d+)$")
STEPS = (15, 20, 30, 45, 60, 90, 120)   # seconds between polls: soon at first, then every two minutes
OK = freshness.OK_CONCLUSIONS
SUCCESS, FAILURE, UNDECIDED = 0, 1, 3


def _span(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"


def _failed(details: dict) -> list[str]:
    """Checks that already ended badly, by name, in GitHub's order."""
    bad = [r["name"] for r in details.get("check_runs", [])
           if r.get("status") == "completed" and r.get("conclusion") not in OK]
    bad += [s["context"] for s in details.get("statuses", []) if s.get("state") in ("failure", "error")]
    return bad


def _usable(name: str) -> bool:
    """Whether a check's name can stand in a ci: anchor (no '=' or backtick, which end it)."""
    return bool(name) and "=" not in name and "`" not in name and name.strip() == name


def wait_ci(repo: str, sha: str, get, *, timeout: float = 1800, grace: float = 300, fail_fast: bool = True,
            sleep=time.sleep, clock=time.monotonic) -> tuple[int, str]:
    """(exit code, the line) for the checks on repo@sha."""
    start, step, seen_any = clock(), 0, False
    while True:
        ev = freshness.ci_evidence(repo, sha, get)
        d, short = ev.details or {}, (ev.revision or sha)[:12]
        elapsed = clock() - start
        where = f"{repo}@{short}"
        if ev.revision is not None:
            seen_any = True
            got, runs = d.get("ci"), len(d.get("check_runs", [])) + len(d.get("statuses", []))
            if got in ("success", "failure"):
                return (SUCCESS if got == "success" else FAILURE,
                        f"buddie wait: checks on {where} ended {got} "
                        + (f"after {_span(elapsed)}" if step else "before the wait") + f" ({runs} checks)"
                        f" ⚓ `ci:{where}={got}`" + (f"; failed: {', '.join(_failed(d)[:5])}" if got == "failure" else ""))
            if got == "ambiguous":
                return UNDECIDED, (f"buddie wait: check suites on {where} disagree on "
                                   f"{', '.join(d.get('duplicates') or [])}: not decided")
            bad = [n for n in _failed(d) if _usable(n)]
            if fail_fast and bad:
                return FAILURE, (f"buddie wait: check {bad[0]!r} on {where} ended failure after {_span(elapsed)}, "
                                 f"others still running ⚓ `ci:{where}/{bad[0]}=failure`")
        elif ev.reason not in ("no_ci_results", "not_found") or (elapsed >= grace and not seen_any):
            why = {"no_ci_results": f"no checks appeared on {where} in {_span(elapsed)}",
                   "not_found": f"no commit {sha} on {repo} (missing, or no access)",
                   "github_unavailable": "GitHub is out of reach (network, rate limit or token)"}.get(
                ev.reason, ev.reason or "unknown")
            return UNDECIDED, f"buddie wait: {why}: not decided"
        if elapsed >= timeout:
            done = sum(r.get("status") == "completed" for r in d.get("check_runs", []))
            total = len(d.get("check_runs", []))
            return UNDECIDED, (f"buddie wait: checks on {where} still pending after {_span(elapsed)} "
                               f"({done} of {total} runs done) ⚓ `ci:{where}=pending`")
        sleep(min(STEPS[min(step, len(STEPS) - 1)], max(1.0, timeout - elapsed)))
        step += 1


def wait_pr(repo: str, number: int, get, **kw) -> tuple[int, str]:
    """The checks on the PR's head commit as GitHub gives it now."""
    head = freshness.resolve_pr_head(repo, number, get)
    if head.revision is None:
        return UNDECIDED, f"buddie wait: no head commit for {repo}#{number}: {head.reason}"
    code, line = wait_ci(repo, head.revision[:12], get, **kw)
    return code, line.replace("buddie wait: ", f"buddie wait: {repo}#{number}: ", 1)


def main(target: str, *, timeout: float, grace: float, fail_fast: bool, get=None, out=print) -> int:
    from buddie.effects import github_get
    get = get or github_get
    if m := TARGET_CI.match(target):
        code, line = wait_ci(m["repo"], m["sha"], get, timeout=timeout, grace=grace, fail_fast=fail_fast)
    elif m := TARGET_PR.match(target):
        code, line = wait_pr(m["repo"], int(m["number"]), get, timeout=timeout, grace=grace, fail_fast=fail_fast)
    else:
        out(f"buddie wait: not a target: {target!r}; give OWNER/REPO@SHA or OWNER/REPO#N")
        return 2
    out(line)
    return code
