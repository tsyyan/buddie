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
import subprocess
from pathlib import Path

from verbatim.store import Store, canonical_url

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


def _git(repo: Path, *args: str) -> list[str]:
    try:
        run = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return run.stdout.splitlines() if run.returncode == 0 else []


def changed_sources(repo: Path) -> list[Path]:
    """`sources/` stores the repo has changed and not merged: untracked or modified, or on this branch only."""
    paths = [line[3:] for line in _git(repo, "status", "--porcelain", "--untracked-files=all")]
    base = _git(repo, "merge-base", "HEAD", "origin/main")
    if base:
        paths += _git(repo, "diff", "--name-only", base[0], "HEAD")
    out = []
    for p in paths:
        parts = Path(p.strip('"')).parts
        if "sources" in parts:
            out.append(repo.joinpath(*parts[:parts.index("sources") + 1]))
    return out


def session_stores(cwd: Path, repos: list[Path], transcript: str | None = None) -> list[Path]:
    bases = [cwd, *repos]
    found = [Path(p) for p in os.environ.get("BUDDIE_STORES", "").split(os.pathsep) if p]
    if os.environ.get("VERBATIM_STORE"):
        found.append(Path(os.environ["VERBATIM_STORE"]))
    found += named_in_transcript(transcript, bases)
    found += [b / ".verbatim" for b in bases]
    for repo in repos:
        found += changed_sources(repo)
    out, seen = [], set()
    for p in found:
        key = p.resolve()
        if key not in seen and (p / "index.json").is_file():
            seen.add(key)
            out.append(p)
    return out


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
