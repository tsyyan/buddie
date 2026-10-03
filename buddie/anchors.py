"""State claims in a report: `⚓ path#sha256`, `⚓ path@commit`, `⚓ fact=value` (lab README, rule 7).

This is the repo-agnostic half of lab's tools/anchors.py: the report is a message from another session, so the
repository it talks about is not known in advance. Each anchor is resolved against the given repos in order:

  path#sha     HOLDS when some repo has the file and its sha256 starts with the prefix; BROKEN when a repo has
               the file with other bytes; UNCHECKABLE when no repo has that path
  path@commit  HOLDS when some repo has the commit and the file in it; BROKEN when the commit is there without
               the file; UNCHECKABLE when no repo has the commit (shallow clone, another repository)
  fact=value   computed by FACTS of the first repo with tools/anchors.py (lab); UNCHECKABLE when none has it

pr:, ci: and run: anchors (a PR's state, checks on a commit, a command and its output) are judged by effects.py
against GitHub and the session transcript given in ctx.
"""
from __future__ import annotations

import hashlib
import importlib.util
import re
import subprocess
from pathlib import Path

ANCHOR = re.compile(r"`⚓\s*([^`]+?)\s*`")
FILE_SHA = re.compile(r"^(?P<path>[^#@=\s]+)#(?P<sha>[0-9a-f]{12,64})$")
FILE_AT = re.compile(r"^(?P<path>[^#@=\s]+)@(?P<commit>[0-9a-f]{7,40})$")
FACT = re.compile(r"^(?P<name>[a-z0-9_.]+)=(?P<value>\S+)$")

HOLDS, BROKEN, UNCHECKABLE = "HOLDS", "BROKEN", "UNCHECKABLE"


def _git(repo: Path, *args: str) -> int:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True).returncode


def _facts(repo: Path):
    """tools/anchors.py of a repo that has one (lab), loaded once; None otherwise."""
    path = repo / "tools" / "anchors.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"buddie_facts_{abs(hash(str(repo)))}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_one(anchor: str, repos: list[Path], cache: dict, ctx: dict | None = None) -> dict:
    from buddie import effects
    if effects.is_effect(anchor):
        return effects.check(anchor, ctx)
    out = {"anchor": anchor}
    if m := FILE_SHA.match(anchor):
        for repo in repos:
            target = repo / m["path"]
            if target.is_file():
                actual = hashlib.sha256(target.read_bytes()).hexdigest()
                if actual.startswith(m["sha"]):
                    return dict(out, status=HOLDS, repo=str(repo))
                out.update(status=BROKEN, repo=str(repo), why=f"sha256 is now {actual[:12]}")
        return out if "status" in out else dict(out, status=UNCHECKABLE, why=f"no repo has {m['path']}")
    if m := FILE_AT.match(anchor):
        for repo in repos:
            if _git(repo, "cat-file", "-e", f"{m['commit']}^{{commit}}") != 0:
                continue
            if _git(repo, "cat-file", "-e", f"{m['commit']}:{m['path']}") == 0:
                return dict(out, status=HOLDS, repo=str(repo))
            return dict(out, status=BROKEN, repo=str(repo), why=f"{m['commit']} has no {m['path']}")
        return dict(out, status=UNCHECKABLE, why=f"no repo has commit {m['commit']} (fetch it, or full history)")
    if m := FACT.match(anchor):
        for repo in repos:
            key = ("facts", str(repo))
            if key not in cache:
                cache[key] = _facts(repo)
            module = cache[key]
            if module is None:
                continue
            if m["name"] not in module.FACTS:
                return dict(out, status=BROKEN, repo=str(repo), why=f"unknown fact {m['name']}")
            vkey = ("value", str(repo), m["name"])
            if vkey not in cache:
                cache[vkey] = str(module.fact(m["name"]))
            if cache[vkey] == m["value"]:
                return dict(out, status=HOLDS, repo=str(repo))
            return dict(out, status=BROKEN, repo=str(repo), why=f"is now {cache[vkey]}")
        return dict(out, status=UNCHECKABLE, why="no repo defines facts (tools/anchors.py)")
    return dict(out, status=BROKEN, why="not an anchor: expected path#sha256, path@commit, fact=value, pr:, ci: or run:")


def check_text(text: str, repos: list[Path], ctx: dict | None = None) -> list[dict]:
    """ctx for effect anchors: {"github": a GET function or None (offline), "transcript": the session jsonl}."""
    results, cache, ctx = [], {}, ctx if ctx is not None else {}
    for number, line in enumerate(text.splitlines(), 1):
        for anchor in ANCHOR.findall(line):
            results.append(dict(check_one(anchor, repos, cache, ctx), line=number))
    return results


# a number stated as a fact ("73 из 84", "11 %", "505 цитат", "0,61"); ids, dates, times, links and code are not
COUNT = re.compile(r"(?<![\w#№.,:/-])\d+(?:[.,]\d+)?(?![\w.:/-]|,\d)")
NOT_COUNT = re.compile(r"`[^`]*`|\[[^\]]*\]\([^)]*\)|https?://\S+|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}:\d{2}\b")


def unanchored(text: str, limit: int = 5) -> tuple[int, list[str]]:
    """Lines that state a count or a share with no anchor on the line (E003: bare numbers drift when relayed).
    A signal for the reader, never a failure: chat replies are not bound by the anchor rule."""
    n, examples = 0, []
    for number, line in enumerate(text.splitlines(), 1):
        if ANCHOR.search(line) or not COUNT.search(NOT_COUNT.sub(" ", line)):
            continue
        n += 1
        if len(examples) < limit:
            examples.append(f"line {number}: {line.strip()[:120]}")
    return n, examples


def find_repos(cwd: Path) -> list[Path]:
    """The git repo around cwd, else the git repos directly under it (a cloud session clones each repo there)."""
    top = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if top.returncode == 0:
        return [Path(top.stdout.strip())]
    return sorted(p for p in cwd.iterdir() if (p / ".git").exists()) if cwd.is_dir() else []
