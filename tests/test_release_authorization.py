"""Every publishing path of release.yml passes the protected authorization job (docs/release.md, "Who approves a
publication"). The workflow file itself is read: each job's `needs`, `if` and `environment`, and the `if`
expressions are evaluated the way GitHub schedules jobs, for every run mode and every way authorization can end.
Nothing here contacts GitHub; whether the environment has reviewers is the owner's setting and is not testable here."""
from __future__ import annotations

import itertools
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
PUBLISHERS = ("pypi", "mcp-registry", "github-release")
PROMOTER = "plugin-stable"  # the distribution branch: authorized like a publisher, chosen only by hand
ORDER = ("candidate", "authorize", *PUBLISHERS, PROMOTER)


def _jobs(text: str) -> dict[str, dict]:
    """Each top-level job: its block, `needs`, `if` (a folded `>-` scalar joined) and environment name."""
    body = text.split("\njobs:\n", 1)[1]
    heads = list(re.finditer(r"(?m)^  ([\w-]+):\n", body))
    jobs = {}
    for i, m in enumerate(heads):
        block = body[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(body)]
        needs = re.search(r"(?m)^    needs: (.+)$", block)
        names = re.findall(r"[\w-]+", needs[1]) if needs else []
        folded = re.search(r"(?m)^    if: >-\n((?:      .*\n)+)", block)
        inline = re.search(r"(?m)^    if: (?!>-)(.+)$", block)
        expr = " ".join(folded[1].split()) if folded else (inline[1].strip() if inline else "")
        env = re.search(r"(?m)^    environment: ([\w-]+)$", block) or \
            re.search(r"(?m)^    environment:\n      name: ([\w-]+)$", block)
        jobs[m[1]] = {"block": block, "needs": names, "if": expr, "environment": env[1] if env else None}
    return jobs


JOBS = _jobs(WORKFLOW)
STATUS = re.compile(r"\b(always|success|failure|cancelled)\(\)")


def _evaluate(expr: str, context: dict, needs: dict[str, str]) -> bool:
    """A job's `if` as GitHub reads it: an expression without a status function is `success() && (expr)`, and
    success() holds only when every needed job succeeded. The workflow's expressions use ==, !=, &&, ||,
    parentheses, string literals and these names; anything else fails the test rather than guessing."""
    if not expr:
        expr = "success()"
    elif not STATUS.search(expr):
        expr = f"success() && ({expr})"
    names = {"always()": "True", "success()": str(all(r == "success" for r in needs.values())),
             "failure()": str(any(r == "failure" for r in needs.values())),
             "cancelled()": str(any(r == "cancelled" for r in needs.values()))}
    py = expr
    for k, v in names.items():
        py = py.replace(k, v)

    def value(m):
        ref = m[0]
        if ref.startswith("needs."):
            return repr(needs[ref.split(".")[1]])
        if ref.startswith("inputs."):
            return repr(context["inputs"].get(ref.split(".", 1)[1], ""))
        if ref == "github.event_name":
            return repr(context["event"])
        raise AssertionError(f"unknown name {ref} in {expr!r}")

    py = re.sub(r"\b(?:needs\.[\w-]+\.result|inputs\.\w+|github\.\w+)", value, py)
    py = py.replace("&&", " and ").replace("||", " or ")
    assert re.fullmatch(r"[\s()'\w.=!-]*", py.replace(" and ", " ").replace(" or ", " ")), py
    return bool(eval(py, {"__builtins__": {}}, {}))  # noqa: S307 (a translated, checked workflow expression)


def _run(event: str, inputs: dict, authorize_ends: str = "success") -> dict[str, str]:
    """Which jobs run, and how each ends: authorize ends as `authorize_ends` (a rejected or failed review ends it
    as failure, a cancelled one as cancelled); every other job that runs succeeds."""
    results: dict[str, str] = {}
    context = {"event": event, "inputs": inputs}
    for name in ORDER:
        job = JOBS[name]
        needs = {n: results[n] for n in job["needs"]}
        runs = _evaluate(job["if"], context, needs)
        results[name] = (authorize_ends if name == "authorize" else "success") if runs else "skipped"
    return results


def _published(results: dict) -> set[str]:
    return {j for j in PUBLISHERS if results[j] != "skipped"}


def _dispatch(only="all", candidate="40023776731"):
    return {"candidate": candidate, "confirm": "publish buddie 2.0.0", "only": only}


# --- the structure --------------------------------------------------------------------------------------------------

def test_the_workflow_has_exactly_these_jobs():
    assert tuple(JOBS) == ORDER


def test_authorize_runs_in_the_protected_environment():
    assert JOBS["authorize"]["environment"] == "pypi"
    assert JOBS["authorize"]["if"] == "github.event_name == 'workflow_dispatch' && inputs.candidate != ''"


def test_the_pypi_job_keeps_its_environment_for_trusted_publishing():
    assert JOBS["pypi"]["environment"] == "pypi"
    assert "url: https://pypi.org/project/buddie/" in JOBS["pypi"]["block"]
    assert "id-token: write" in JOBS["pypi"]["block"]


def test_only_authorize_and_pypi_name_an_environment():
    """No other job gained or lost one: the candidate build stays unprotected (it publishes nothing), and the
    recovery jobs are covered by authorize rather than by environments of their own."""
    assert {n for n, j in JOBS.items() if j["environment"]} == {"authorize", "pypi"}


@pytest.mark.parametrize("name", PUBLISHERS)
def test_every_publisher_needs_authorize(name):
    assert "authorize" in JOBS[name]["needs"]


def test_what_can_write_is_only_in_jobs_that_need_authorize():
    """Every job holding a publishing permission or tool depends on authorize."""
    writers = {n for n, j in JOBS.items()
               if re.search(r"id-token: write|contents: write|pypi-publish|mcp-publisher|release_publish.py github",
                            j["block"])}
    assert writers == set(PUBLISHERS) | {PROMOTER}
    assert all("authorize" in JOBS[n]["needs"] for n in writers)


# --- what runs ------------------------------------------------------------------------------------------------------

def test_a_tag_push_builds_the_candidate_and_publishes_nothing():
    results = _run("push", {})
    assert results["candidate"] == "success" and results["authorize"] == "skipped"
    assert _published(results) == set()


@pytest.mark.parametrize("only", ["all", "pypi", "mcp-registry", "github-release"])
def test_a_manual_candidate_build_publishes_nothing(only):
    results = _run("workflow_dispatch", _dispatch(only, candidate=""))
    assert results["candidate"] == "success" and results["authorize"] == "skipped"
    assert _published(results) == set()


@pytest.mark.parametrize("only, stages", [
    ("all", set(PUBLISHERS)),
    ("pypi", {"pypi"}),
    ("mcp-registry", {"mcp-registry"}),          # recovery: PyPI skipped, registry runs
    ("github-release", {"github-release"}),      # recovery: PyPI skipped, release runs
])
def test_an_authorized_publish_runs_the_chosen_stages_and_no_candidate(only, stages):
    results = _run("workflow_dispatch", _dispatch(only))
    assert results["candidate"] == "skipped" and results["authorize"] == "success"
    assert _published(results) == stages


@pytest.mark.parametrize("only, ends", list(itertools.product(["all", "pypi", "mcp-registry", "github-release"],
                                                            ["failure", "cancelled"])))
def test_no_stage_runs_when_authorization_is_rejected_fails_or_is_cancelled(only, ends):
    results = _run("workflow_dispatch", _dispatch(only), authorize_ends=ends)
    assert results["authorize"] == ends
    assert _published(results) == set(), results


def test_a_skipped_authorize_satisfies_no_publisher():
    """Each publisher, given every combination of its needs' results in which authorize did not succeed, stays
    skipped: the recovery jobs' always() cannot let one through."""
    for name in PUBLISHERS:
        others = [n for n in JOBS[name]["needs"] if n != "authorize"]
        for auth in ("skipped", "failure", "cancelled"):
            for combo in itertools.product(["success", "skipped", "failure", "cancelled"], repeat=len(others)):
                needs = {"authorize": auth, **dict(zip(others, combo))}
                for only in ("all", name):
                    assert not _evaluate(JOBS[name]["if"], {"event": "workflow_dispatch",
                                                             "inputs": _dispatch(only)}, needs), (name, needs)


def test_recovery_after_pypi_failed_waits_for_a_new_run():
    """When the PyPI stage fails in an `all` run, the registry and the release do not run in that run."""
    needs = {"authorize": "success", "pypi": "failure"}
    for name in ("mcp-registry", "github-release"):
        assert not _evaluate(JOBS[name]["if"], {"event": "workflow_dispatch", "inputs": _dispatch("all")}, needs)


# --- the integrity checks are still there -------------------------------------------------------------------------

def test_authorize_still_checks_the_candidate_and_holds_no_publishing_permission():
    block = JOBS["authorize"]["block"]
    assert "python3 scripts/release_publish.py authorize rc" in block
    assert 'git merge-base --is-ancestor "$GITHUB_SHA" origin/main' in block
    assert '--confirm "$CONFIRM"' in block and "run-id: ${{ inputs.candidate }}" in block
    assert not re.search(r"id-token: write|contents: write", block)


@pytest.mark.parametrize("name, checks", [
    ("pypi", ["release_manifest.py verify rc", "release_publish.py pypi-plan", "release_manifest.py pypi rc"]),
    ("mcp-registry", ["release_manifest.py pypi rc", "release_publish.py registry-check", "sha256sum -c"]),
    ("github-release", ["release_manifest.py verify rc", "release_publish.py github-release"]),
])
def test_each_stage_still_verifies_the_candidates_files(name, checks):
    block = JOBS[name]["block"]
    assert "run-id: ${{ inputs.candidate }}" in block and "python -m build" not in block
    for check in checks:
        assert check in block, (name, check)


# --- plugin-stable (scripts/plugin_promote.py) ----------------------------------------------------------------------

def _promote(only="plugin-stable"):
    return {"candidate": "40023776731", "confirm": "promote buddie 2.0.0 to plugin-stable", "only": only}


def test_plugin_stable_runs_only_when_chosen_by_hand_and_authorized():
    results = _run("workflow_dispatch", _promote())
    assert results["authorize"] == "success" and results[PROMOTER] == "success"
    assert _published(results) == set()                     # promoting publishes nothing else
    for event, inputs in (("push", {}), ("workflow_dispatch", _dispatch("all")),
                          ("workflow_dispatch", _dispatch("all", candidate="")), ("workflow_dispatch", _dispatch("pypi"))):
        assert _run(event, inputs)[PROMOTER] == "skipped", (event, inputs)
    for ends in ("failure", "cancelled"):
        assert _run("workflow_dispatch", _promote(), authorize_ends=ends)[PROMOTER] == "skipped"


def test_plugin_stable_pushes_without_force_verifies_and_installs():
    block = JOBS[PROMOTER]["block"]
    assert JOBS[PROMOTER]["needs"] == ["authorize"] and JOBS[PROMOTER]["environment"] is None
    for needed in ("run-id: ${{ inputs.candidate }}", "release_manifest.py verify rc", "plugin_package.py verify rc/plugin --ref",
                   "plugin_promote.py promote rc", "plugin_promote.py verify --commit", "plugin install buddie@buddie",
                   "smoke_plugin.py", "create_branch"):
        assert needed in block, needed
    assert not re.search(r"--force|push -f|\+refs/", WORKFLOW)
    promote = (ROOT / "scripts/plugin_promote.py").read_text(encoding="utf-8")
    pushes = re.findall(r'git\(repo, "push"[^)]*\)', promote)
    assert pushes == ['git(repo, "push", "--quiet", remote, f"{commit}:{ref}")']


def test_a_publish_approval_does_not_promote_and_a_promotion_approval_does_not_publish():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import release_publish as rp
    assert rp.confirmation("2.0.0") == "publish buddie 2.0.0"
    assert rp.confirmation("2.0.0", "plugin-stable") == "promote buddie 2.0.0 to plugin-stable"
    assert rp.confirmation("2.0.0", "all") != rp.confirmation("2.0.0", "plugin-stable")
