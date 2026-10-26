"""The fixed, offline world every run of the benchmark sees (PROTOCOL.md, "Evidence"): a snapshot store with one page,
a synthetic git repository with fixed commit dates (so its commit ids are the same on every machine), a work queue
for work claims, and canned GitHub API answers. Both conditions get this world and nothing else.

Nothing here reaches the network: fetching is off, and GitHub answers come from GITHUB below through the same
function the server calls (buddie.effects.github_get, replaced for the run by `github_fixture`)."""
from __future__ import annotations

import contextlib
import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

URL = "https://news.example.org/outage"
PAGE = ("<p>" + "Background paragraph about the service. " * 40 + "</p><p>The company said the outage began at "
        "14:59 UTC and was resolved within two hours.</p>").encode()
GONE = "https://gone.example.org/postmortem"          # never in the store, fetching is off: unavailable evidence
SHA = "dbf390f479dee4806b67d6d62d90aeec7fc12843"       # the fixture commit the CI and PR answers are about
UNKNOWN_SHA = "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c"  # a commit GitHub has no answer for (unavailable)
DATA = b"hello\n"
DATA_SHA = hashlib.sha256(DATA).hexdigest()

GITHUB = {
    f"/repos/o/r/commits/{SHA}": {"sha": SHA},
    f"/repos/o/r/commits/{SHA}/check-runs?filter=latest&per_page=100&page=1":
        {"total_count": 1, "check_runs": [{"name": "test", "status": "completed", "conclusion": "failure",
                                           "head_sha": SHA}]},
    f"/repos/o/r/commits/{SHA}/status": {"state": "failure", "statuses": [], "total_count": 0},
    "/repos/o/r/pulls/55": {"state": "open", "merged": False, "draft": False, "head": {"sha": SHA}},
}

MANDATE = """[mandate]
done = "done"
proposed = "proposed"

[[mandate.refs]]
pattern = 'PLAN stage (?P<stage>\\d+)'
doc = "PLAN.md"
level = "stage"
"""
QUEUE_HEAD = "| # | Proposal | Source | Basis | Status |\n|---|---|---|---|---|\n"
GIT_ENV = {"GIT_AUTHOR_NAME": "bench", "GIT_AUTHOR_EMAIL": "bench@example.org", "GIT_COMMITTER_NAME": "bench",
           "GIT_COMMITTER_EMAIL": "bench@example.org", "GIT_AUTHOR_DATE": "2026-10-01T12:00:00Z",
           "GIT_COMMITTER_DATE": "2026-10-01T12:00:00Z", "GIT_CONFIG_NOSYSTEM": "1"}


@dataclass(frozen=True)
class World:
    root: Path
    store: Path
    repo: Path
    commit: str       # the repo's first commit (short), named by the done queue row's anchor

    def options(self) -> dict:
        """The check options of every verification in the benchmark, in both conditions (fixed per run)."""
        return {"repos": [str(self.repo)], "store": str(self.store), "fetch": False, "github": True,
                "numbers": "gap"}


def _git(repo: Path, *args: str) -> str:
    env = dict(os.environ, **GIT_ENV, HOME=str(repo.parent), XDG_CONFIG_HOME=str(repo.parent))
    return subprocess.run(["git", "-C", str(repo), "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false", *args],
                          capture_output=True, text=True, check=True, env=env).stdout.strip()


def build(root: Path) -> World:
    """The world in a fresh directory `root` (one per run: no state carries over between runs)."""
    from buddie.verbatim.store import Store
    root.mkdir(parents=True, exist_ok=False)
    Store(root / "store").add(URL, PAGE, content_type="text/html")
    repo = root / "repo"
    repo.mkdir()
    (repo / "data.txt").write_bytes(DATA)
    (repo / "buddie.toml").write_text(MANDATE, encoding="utf-8", newline="\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    commit = _git(repo, "rev-parse", "--short=12", "HEAD")
    rows = [f"fix the login form | t | fix | done `⚓ data.txt@{commit}`",
            "update the deploy docs | t | fix | done"]
    (repo / "NEXT.md").write_text(QUEUE_HEAD + "".join(f"| {i} | {r} |\n" for i, r in enumerate(rows, 1)),
                                  encoding="utf-8", newline="\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "queue")
    return World(root, root / "store", repo, commit)


@contextlib.contextmanager
def github_fixture(answers: dict | None = None):
    """GitHub answers from the fixture for the duration of a run, for every caller of buddie.effects.github_get
    (the MCP server's verify_report, feedback_start and feedback_resolve, and the validator alike)."""
    from buddie import effects
    answers = GITHUB if answers is None else answers
    real = effects.github_get
    effects.github_get = answers.get
    try:
        yield
    finally:
        effects.github_get = real
