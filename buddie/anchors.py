"""State claims in a report: `⚓ path#sha256`, `⚓ path@commit`, `⚓ fact=value` (lab README, rule 7).

This is the repo-agnostic half of lab's tools/anchors.py: the report is a message from another session, so the
repository it talks about is not known in advance. Each anchor is resolved against the given repos in order:

  path#sha     HOLDS when some repo has the file and its sha256 starts with the prefix; BROKEN when a repo has
               the file with other bytes; UNCHECKABLE when no repo has that path, or the path leads out of the repo
               (absolute, "..", a symlink to outside) or is not a plain file: such a file is not read (audit R2)
  path@commit  HOLDS when some repo has the commit and the file in it; BROKEN when the commit is there without
               the file; UNCHECKABLE when no repo has the commit (shallow clone, another repository)
  fact=value   always UNCHECKABLE: its value was computed by the repo's own tools/anchors.py, and a repo under
               check does not get to run code in the checker (audit R1)

pr:, ci: and run: anchors (a PR's state, checks on a commit, a command and its output) are judged by effects.py
against GitHub and the session transcript given in ctx; choice:<id>=<step> (what the person picked on a summary card)
by summary.py against the hook's journal.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
from pathlib import Path

# the sign inside the backticks (`⚓ x`) or right before them (⚓ `x`, as people and the buddie skill write it)
BACKTICKED = re.compile(r"(?:`⚓\s*|(?:(?<!`)⚓\s*|⚓\s+)`\s*)([^`\s][^`]*?)\s*`")
FILE_SHA = re.compile(r"^(?P<path>[^#@=\s]+)#(?P<sha>[0-9a-f]{12,64})$")
FILE_AT = re.compile(r"^(?P<path>[^#@=\s]+)@(?P<commit>[0-9a-f]{7,40})$")
FACT = re.compile(r"^(?P<name>[a-z0-9_.]+)=(?P<value>\S+)$")
CODE_SPAN = re.compile(r"`[^`]*`")
BARE_SIGN = re.compile(r"⚓[ \t]*(?=[^\s`⚓])")
# a placeholder from the anchor table, not a claim: «(⚓ path@commit, … or ⚓ run:CMD => OUTPUT)» quoted from a return
TEMPLATE = re.compile(r"<[^>]*>|…|\b(?:OWNER/REPO|SHA)\b|^(?:path#sha256|path@commit|fact=value)$")
RUN_TEMPLATE = re.compile(r"^run:\s*(?:CMD|<[^>]*>)(?:\s|$)|=>\s*(?:OUT|OUTPUT|<[^>]*>)$")
TRAIL = ".,;:!?»\"'"


def _bare_end(line: str, start: int) -> int:
    """Where a bare anchor's run: claim ends: the next sign, a table cell's border (a line that starts with |),
    or the end of the line."""
    end = len(line)
    if (nxt := line.find("⚓", start)) != -1:
        end = nxt
    if line.lstrip().startswith("|") and (bar := line.find("|", start)) != -1:
        end = min(end, bar)
    return end


def _bare(line: str, start: int) -> tuple[str, int] | None:
    """The bare anchor (no backticks, E017 / NEXT №97) that starts at `start` and where it ends; None when the text
    after the sign is not an anchor (prose, a placeholder): a bare sign is a claim only in an anchor's own form."""
    from buddie import effects
    rest = line[start:_bare_end(line, start)]
    if rest.startswith("run:"):  # CMD => OUT holds spaces: to the end of the line or the delimiter
        cand = rest.rstrip()
        cand = cand.rstrip(TRAIL + " ")
        if cand.endswith(")") and cand.count(")") > cand.count("("):
            cand = cand[:-1].rstrip()
        end = start + len(cand)
    else:
        token = rest.split()[0] if rest.split() else ""
        cand = token.rstrip(TRAIL)
        if cand.endswith(")") and "(" not in cand:
            cand = cand.rstrip(")" + TRAIL)
        end = start + len(cand)
    if not cand or (RUN_TEMPLATE.search(cand) if cand.startswith("run:") else TEMPLATE.search(cand)):
        return None
    ok = (FILE_SHA.match(cand) or FILE_AT.match(cand) or FACT.match(cand) or cand.startswith("choice:")
          or effects.PR.match(cand) or effects.CI.match(cand) or effects.RUN.match(cand))
    return (cand, end) if ok else None


def spans(line: str) -> list[tuple[int, int, str]]:
    """(start, end, anchor) of each anchor on a line: in backticks, or bare after the sign up to a space (a file,
    a commit, a fact, a PR) or, for run:, to the end of the line or the delimiter (NEXT №97)."""
    found = [(m.start(), m.end(), m.group(1)) for m in BACKTICKED.finditer(line)]
    masked = list(line)
    for a, b, _ in found:
        masked[a:b] = " " * (b - a)
    masked = CODE_SPAN.sub(lambda m: " " * len(m.group()), "".join(masked))
    for m in BARE_SIGN.finditer(masked):
        if got := _bare(masked, m.end()):
            found.append((m.start(), got[1], got[0]))
    return sorted(found)


class _Anchors:
    """The anchors of a text, as the regex it replaces was used: findall, search, sub, line by line."""

    def findall(self, text: str) -> list[str]:
        return [a for line in text.split("\n") for _, _, a in spans(line)]

    def search(self, text: str) -> bool:
        return any(spans(line) for line in text.split("\n"))

    def sub(self, repl: str, text: str) -> str:
        out = []
        for line in text.split("\n"):
            for a, b, _ in reversed(spans(line)):
                line = line[:a] + repl + line[b:]
            out.append(line)
        return "\n".join(out)


ANCHOR = _Anchors()

HOLDS, BROKEN, UNCHECKABLE = "HOLDS", "BROKEN", "UNCHECKABLE"


def _git(repo: Path, *args: str) -> int:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True).returncode


OUTSIDE = "outside"  # _inside's answer for a path that leads out of the repo


def _inside(repo: Path, rel: str) -> Path | str | None:
    """The file `rel` names in `repo`, every symlink followed: a Path when it exists inside the repo, OUTSIDE when
    the path or its target is not in the repo, None when there is no such file. "\\" counts as a separator on every
    system; an absolute path, a drive ("C:", also NTFS streams "file:stream") or a ".." part is OUTSIDE unread."""
    parts = rel.replace("\\", "/").split("/")
    if not parts[0] or ":" in rel or "\0" in rel or ".." in parts:
        return OUTSIDE
    try:
        root = repo.resolve(strict=True)
        target = root.joinpath(*[p for p in parts if p not in ("", ".")]).resolve(strict=True)
    except (OSError, RuntimeError):  # missing, or a symlink loop
        return None
    return target if target != root and target.is_relative_to(root) else OUTSIDE


def _read(target: Path, root: Path) -> bytes | None:
    """The bytes of `target` (a path _inside resolved), or None when it is not a plain file of its own or was swapped
    after the check. Where the system allows (Linux, macOS) each part of the path is opened under the one before it
    without following symlinks, so a part replaced by a symlink after _inside fails to open. Elsewhere (Windows) the
    opened file must be the one that was checked; a swap and swap back between the two is not caught there."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        if nofollow and os.open in os.supports_dir_fd and hasattr(os, "O_DIRECTORY"):
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                for part in target.relative_to(root).parts[:-1]:
                    nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | nofollow, dir_fd=fd)
                    os.close(fd)
                    fd = nxt
                f = os.open(target.name, flags | nofollow, dir_fd=fd)
            finally:
                os.close(fd)
        else:
            checked = os.stat(target)
            f = os.open(target, flags)
            opened = os.fstat(f)
            if (opened.st_dev, opened.st_ino) != (checked.st_dev, checked.st_ino) \
                    or not os.path.realpath(target).startswith(str(root) + os.sep):
                os.close(f)
                return None
    except OSError:
        return None
    with os.fdopen(f, "rb") as fh:
        st = os.fstat(fh.fileno())
        # a hard link can make a file outside the repo look like one inside it (a git checkout has none)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink > 1:
            return None
        return fh.read()


def check_one(anchor: str, repos: list[Path], cache: dict, ctx: dict | None = None) -> dict:
    from buddie import effects
    if effects.is_effect(anchor):
        return effects.check(anchor, ctx)
    if anchor.startswith("choice:"):
        from buddie.summary import check_choice
        return check_choice(anchor, ctx)
    out = {"anchor": anchor}
    if m := FILE_SHA.match(anchor):
        refused = None
        for repo in repos:
            target = _inside(repo, m["path"])
            if target is None:
                continue
            data = None if target == OUTSIDE else _read(target, repo.resolve())
            if data is None:
                refused = refused or (f"{m['path']} leads outside the repo, not read" if target == OUTSIDE
                                      else f"{m['path']} is not a plain file in the repo, not read")
                continue
            actual = hashlib.sha256(data).hexdigest()
            if actual.startswith(m["sha"]):
                return dict(out, status=HOLDS, repo=str(repo))
            out.update(status=BROKEN, repo=str(repo), why=f"sha256 is now {actual[:12]}")
        if "status" in out:
            return out
        return dict(out, status=UNCHECKABLE, why=refused or f"no repo has {m['path']}")
    if m := FILE_AT.match(anchor):
        for repo in repos:
            if _git(repo, "cat-file", "-e", f"{m['commit']}^{{commit}}") != 0:
                continue
            if _git(repo, "cat-file", "-e", f"{m['commit']}:{m['path']}") == 0:
                return dict(out, status=HOLDS, repo=str(repo))
            return dict(out, status=BROKEN, repo=str(repo), why=f"{m['commit']} has no {m['path']}")
        return dict(out, status=UNCHECKABLE, why=f"no repo has commit {m['commit']} (fetch it, or full history)")
    if FACT.match(anchor):
        return dict(out, status=UNCHECKABLE,
                    why="fact= is not checked: computing it would run the repo's own code (tools/anchors.py)")
    return dict(out, status=BROKEN, why="not an anchor: expected path#sha256, path@commit, fact=value, pr:, ci:, run: or choice:")


def check_text(text: str, repos: list[Path], ctx: dict | None = None) -> list[dict]:
    """ctx for effect anchors: {"github": a GET function or None (offline), "transcript": the session jsonl}."""
    results, cache, ctx = [], {}, ctx if ctx is not None else {}
    for number, line in enumerate(text.splitlines(), 1):
        for anchor in ANCHOR.findall(line):
            results.append(dict(check_one(anchor, repos, cache, ctx), line=number))
    return results


# a number stated as a fact ("73 из 84", "11 %", "505 цитат", "0,61"); ids, dates, times, links and code are not
COUNT = re.compile(r"(?<![\w#№.,:/-])\d+(?:[.,]\d+)?(?![\w.:/-]|,\d)")
# a lone year names a time, as a date does (NEXT №108: «по переписи 2020 года», «за 2024 год», «April 2026»,
# «(2021)»): 1800-2099, or a range of two, followed by a year word, or after a month (with its day: «14 марта 2024»),
# after in/since/until, or in brackets
_Y = r"(?<![\w#№.,:/-])(?:1[89]|20)\d{2}(?![\w,:/-]|\.\d)"
_MONTH = (r"(?i:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?"
          r"|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|январ[а-я]*|феврал[а-я]*|март[а-я]*|апрел[а-я]*|ма[йяе]|июн[а-я]*"
          r"|июл[а-я]*|август[а-я]*|сентябр[а-я]*|октябр[а-я]*|ноябр[а-я]*|декабр[а-я]*)")
YEAR = re.compile(rf"(?:{_Y}\s*[–—]\s*)?{_Y}(?=\s*(?:-(?:го|м|й|х)\b|гг?\.|(?i:год[а-я]*|year)\b))"
                  rf"|(?:\b\d{{1,2}}\s+)?\b{_MONTH}\s+{_Y}|\b(?i:in|since|until)\s+{_Y}|\(\s*{_Y}\s*\)")
NOT_COUNT = re.compile(r"`[^`]*`|\[[^\]]*\]\([^)]*\)|https?://\S+|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}:\d{2}\b|" + YEAR.pattern)


def counts(line: str) -> list[str]:
    """The counts and shares a line states, leaving out ids, dates, lone years, times, links and code."""
    return COUNT.findall(NOT_COUNT.sub(" ", line))


def unanchored_lines(text: str, backed=()) -> list[int]:
    """Numbers of the lines that state a count with no anchor on the line; `backed` lines (a quote found on the page
    the line links, verify.quote_backed) carry their source and are left out."""
    return [n for n, line in enumerate(text.splitlines(), 1)
            if n not in backed and not ANCHOR.search(line) and counts(line)]


def unanchored(text: str, limit: int = 5, backed=()) -> tuple[int, list[str]]:
    """Lines that state a count or a share with no anchor on the line (E003: bare numbers drift when relayed).
    A signal for the reader, never a failure: chat replies are not bound by the anchor rule."""
    found, lines = unanchored_lines(text, backed), text.splitlines()
    return len(found), [f"line {n}: {lines[n - 1].strip()[:120]}" for n in found[:limit]]


def find_repos(cwd: Path) -> list[Path]:
    """The git repo around cwd, else the git repos directly under it (a cloud session clones each repo there)."""
    top = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if top.returncode == 0:
        return [Path(top.stdout.strip())]
    return sorted(p for p in cwd.iterdir() if (p / ".git").exists()) if cwd.is_dir() else []
