"""Which snapshots judge the quotes of a thread's answer (NEXT №37).

A thread that follows the verbatim skill snaps its sources before reading them, into $VERBATIM_STORE exported in
its own shell, into `--store <report dir>/sources`, or into ./.verbatim of whatever directory it was in. The hook runs
in another process: it does not see that shell's variables, so with a single default store it fetched the page again
and judged the quote against the page as it is now, not against the bytes the thread quoted from (a page that changed
or blocks the hook gives a false NOT_FOUND or SOURCE_UNAVAILABLE).

session_stores() lists the stores this session used: $BUDDIE_STORES, $VERBATIM_STORE, the stores named in its
Bash commands (`VERBATIM_STORE=DIR`, `--store DIR`) and in buddie MCP calls (`"store": DIR`), ./.verbatim next to
the cwd and the repos, and `sources/` stores the repos have uncommitted or not yet merged. UnionStore reads all of
them as one: for a URL, the newest snapshot that has bytes wins, whichever store holds it; a fetch (the URL is in
none of them) goes to the first store as before.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from buddie.verbatim.store import Store, canonical_url

NAMED = re.compile(r"""(?:VERBATIM_STORE=|--store[= ]+|"store":\s*)["']?([^\s"';&|)]+)""")


def _expand(raw: str, base: Path) -> Path:
    raw = raw.replace("${PWD}", str(base)).replace("$PWD", str(base))
    path = Path(os.path.expanduser(raw))
    return path if path.is_absolute() else base / path


def named_in_transcript(transcript: str | None, bases: list[Path]) -> list[Path]:
    """Stores the session named in its tool calls, resolved against each base dir (a Bash cwd is not recorded)."""
    if not transcript or not Path(transcript).exists():
        return []
    from buddie.effects import tool_calls, transcript_files
    out = []
    for call in tool_calls(transcript_files(transcript)):
        for raw in NAMED.findall(call["input"]):
            out += [_expand(raw, b) for b in bases]
    return out


GIT_TIMEOUT = 20.0   # seconds for git status in a large checkout
MAX_ENTRY = 2**16    # bytes of one path git lists; a longer one refuses the output


class _Stores:
    """The `sources/` directories among the NUL-separated paths git writes, read piece by piece: what is kept is the
    stores found and one unfinished entry, so a checkout with millions of untracked files costs no more memory."""

    def __init__(self, repo: Path, status: bool):
        self.repo, self.status, self.found, self._rest = repo, status, [], b""

    def __call__(self, chunk: bytes) -> bool:
        entries = (self._rest + chunk).split(b"\0")
        self._rest = entries.pop()
        if len(self._rest) > MAX_ENTRY:
            return False
        for raw in entries:
            path = raw.decode("utf-8", "surrogateescape")
            parts = Path(path[3:] if self.status else path).parts
            if "sources" in parts:
                store = self.repo.joinpath(*parts[:parts.index("sources") + 1])
                if store not in self.found:
                    self.found.append(store)
        return True


def changed_sources_of(repo: Path) -> tuple[list[Path], str | None]:
    """(`sources/` stores the repo has changed and not merged: untracked or modified, or on this branch only; None),
    or what of them could be listed and why not all: git is missing or did not answer ("unavailable", "timeout",
    "output_limit", "git_error"), or the repository's config names a filter driver git status would run that cannot
    be switched off ("unneutralized_filter"). git runs through buddie/runner.py: nothing the repository's config
    names is executed, and git never sees the hook's environment (where the person's token is)."""
    from buddie import runner
    got = _Stores(repo, status=True)
    st = runner.git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=all",
                    "--no-renames", timeout=GIT_TIMEOUT, consume=got, filters=True)
    if st.state != "ok":
        return [], st.state
    if st.code != 0:  # not a repository has nothing to list, which is no gap; asked only when status failed
        inside = runner.git(repo, "rev-parse", "--git-dir")
        if inside.state == "ok" and inside.code != 0 and not (repo / ".git").exists():
            return [], None
        return [], "git_error"
    base = runner.git_text(repo, "merge-base", "HEAD", "origin/main")  # none without origin/main: nothing to add
    if base and base.strip():
        branch = _Stores(repo, status=False)
        diff = runner.git(repo, "diff", "--name-only", "-z", base.strip(), "HEAD", timeout=GIT_TIMEOUT,
                          consume=branch)
        if diff.state != "ok" or diff.code != 0:
            return got.found, diff.state if diff.state != "ok" else "git_error"
        got.found += [s for s in branch.found if s not in got.found]
    return got.found, None


def changed_sources(repo: Path) -> list[Path]:
    """`sources/` stores the repo has changed and not merged (changed_sources_of, without why some may be missing)."""
    return changed_sources_of(repo)[0]


def session_sources(cwd: Path, repos: list[Path], transcript: str | None = None,
                    unavailable: list | None = None) -> list:
    """session_stores with who named each (evidence.Selected): the environment, the transcript, the event's cwd, a
    repo. Every one of them is a directory the agent can write; the origin says who chose it, not that it is true.
    unavailable: a list to which (repo, why) is added for each repo whose changed stores could not all be listed."""
    from buddie.evidence import Origin, Selected, env_paths
    bases = [cwd, *repos]
    found = [(p, Origin.ENVIRONMENT) for p in env_paths("BUDDIE_STORES")]
    if os.environ.get("VERBATIM_STORE"):
        found.append((Path(os.environ["VERBATIM_STORE"]), Origin.ENVIRONMENT))
    found += [(p, Origin.TRANSCRIPT) for p in named_in_transcript(transcript, bases)]
    found += [(cwd / ".verbatim", Origin.EVENT)] + [(r / ".verbatim", Origin.REPO) for r in repos]
    for repo in repos:
        changed, why = changed_sources_of(repo)
        found += [(p, Origin.REPO) for p in changed]
        if why is not None and unavailable is not None:
            unavailable.append((repo, why))
    out, seen = [], set()
    for p, origin in found:
        key = p.resolve()
        if key not in seen and (p / "index.json").is_file():
            seen.add(key)
            out.append(Selected("store", p, origin))
    return out


def session_stores(cwd: Path, repos: list[Path], transcript: str | None = None) -> list[Path]:
    return [s.path for s in session_sources(cwd, repos, transcript)]


class UnionStore(Store):
    """The first root takes new fetches; every root is read."""

    def __init__(self, root: str | os.PathLike | None, others: list[Path] = ()) -> None:
        super().__init__(root)
        mine = self.root.resolve()
        self.others = [Store(p) for p in others if Path(p).resolve() != mine]

    def roots(self) -> list[Path]:
        return [self.root, *(s.root for s in self.others)]

    def index(self) -> dict[str, list[dict]]:
        merged: dict[str, list[dict]] = {}
        for store in self.others:
            try:
                own = store.index()
            except (OSError, json.JSONDecodeError):
                continue
            for url, entries in own.items():
                merged.setdefault(url, []).extend(entries)
        for url, entries in Store.index(self).items():
            merged.setdefault(url, []).extend(entries)
        for entries in merged.values():
            entries.sort(key=lambda e: e.get("fetched_at") or "")
        return merged

    def record(self, url: str, entry: dict) -> dict:
        with self._lock:
            index = Store.index(self)
            index.setdefault(canonical_url(url), []).append(entry)
            self._write_index(index)
        return entry

    def latest(self, url: str) -> dict | None:
        entries = self.index().get(canonical_url(url))
        if not entries:
            return None
        read = [e for e in entries if e.get("sha256")]
        return (read or entries)[-1]

    def read(self, sha: str) -> bytes:
        for store in (self, *self.others):
            if (store.snapshots / sha).exists():
                return Store.read(store, sha)
        return Store.read(self, sha)
