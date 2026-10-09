"""Ready anchors for a returned message (audit/13 §4.1 п. 3, NEXT №55): the fix becomes adding the proof.

From GitHub: the PRs the text or the session's tool output names (github.com/OWNER/REPO/pull/N, OWNER/REPO#N) give
`pr:OWNER/REPO#N=<state now>@<sha>` and, when their checks are done, `ci:OWNER/REPO@<head>=<success|failure>`.
A line claiming work in prose (NEXT №63) gets the same. From the transcript: a line with a bare count gets `run:<command> => <output line with that count>` from the latest
tool call whose output has it; a final answer with no anchor at all gets the latest call that ran without error.
Neither comes from a call that hands the report back (SubagentHandback) or opens by writing a file (NEXT №97).

Every suggestion is judged by effects.check before it is offered: only HOLDS goes back to the model, so copying it
as is passes the gate. None of it is written by the model.
"""
from __future__ import annotations

import difflib
import re

from buddie import effects as eff
from buddie.anchors import ANCHOR, counts

PR_URL = re.compile(r"github\.com/(?P<repo>[\w.-]+/[\w.-]+)/pull/(?P<n>\d+)")
PR_REF = re.compile(r"(?<![\w/.-])(?P<repo>[\w.-]+/[\w.-]+)#(?P<n>\d+)\b")
LIMIT = 5
SCAN = 200  # the latest tool calls searched for an output line


def _prs(text: str, calls: list[dict], limit: int = 3) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    sources = [text] + [c["output"] for c in reversed(calls) if "pull" in c["output"]]
    for src in sources:
        for rx in (PR_URL, PR_REF):
            for m in rx.finditer(src):
                key = (m["repo"], m["n"])
                if key not in found:
                    found.append(key)
    return found[:limit]


def _holds(anchor: str, ctx: dict) -> bool:
    return eff.check(anchor, ctx)["status"] == eff.HOLDS


def _github(text: str, calls: list[dict], ctx: dict) -> list[str]:
    out = []
    for repo, n in _prs(text, calls):
        try:
            data = eff._get(ctx, f"/repos/{repo}/pulls/{n}")
        except eff.GitHubUnavailable:
            return out
        if not data:
            continue
        state = "merged" if data.get("merged") else ("draft" if data.get("state") == "open" and data.get("draft")
                                                     else data.get("state"))
        sha = (data.get("merge_commit_sha") if state == "merged" else (data.get("head") or {}).get("sha")) or ""
        pr = f"pr:{repo}#{n}={state}" + (f"@{sha[:12]}" if sha else "")
        if _holds(pr, ctx):
            out.append(pr)
        head = ((data.get("head") or {}).get("sha") or "")[:12]
        for what in ("success", "failure"):
            ci = f"ci:{repo}@{head}={what}"
            if head and _holds(ci, ctx):
                out.append(ci)
                break
    return out


def _clean(s: str) -> str:
    return " ".join(s.replace("`", " ").split())


# a call that opens by writing a file (cat > F <<'EOF', tee F <<, sed -i): its first line is not what printed the
# output, so a run: anchor on it backs nothing the report claims (E017: «run:cd … && cat > REPORT.md <<'EOF' =>
# buddie PASS…» offered for a report with anchors, NEXT №97)
HEREDOC = re.compile(r"<<-?\s*['\"]?\w+")
REDIRECT = re.compile(r"(?<![=>&\d-])>>?\s*(?!&)[\w./~$\"'-]")
EDITS = re.compile(r"(?<![\w-])(?:sed\s+(?:-\w*\s+)*-i|perl\s+-p?i)\b")


def writes_file(first: str) -> bool:
    return bool(HEREDOC.search(first) and REDIRECT.search(first) or re.search(r"\btee\b", first)
                and HEREDOC.search(first) or EDITS.search(first))


def _cmd(call: dict) -> str | None:
    first = next((ln for ln in call["input"].splitlines() if ln.strip()), "")
    if writes_file(first):
        return None
    cmd = _clean(first)[:60].strip()
    return cmd if len(cmd) >= 4 and "=>" not in cmd and cmd in _clean(call["input"]) else None


def _window(line: str, token: str, width: int = 80) -> str:
    line = _clean(line)
    if len(line) <= width:
        return line
    at = max(line.find(token) - width // 3, 0)
    return line[at:at + width].strip()


WORDS = re.compile(r"[\w.,%]+")


def _words(line: str) -> set[str]:
    return {w.strip(".,").lower() for w in WORDS.findall(line) if w.strip(".,")}


def _near(line: str, word: re.Pattern, span: int = 3) -> tuple[set[str], str]:
    """The words around the count (span on each side) and the word right after it ("47 passed": "passed")."""
    m = word.search(line)
    if not m:
        return set(), ""
    before, after = WORDS.findall(line[:m.start()])[-span:], WORDS.findall(line[m.end():])[:span]
    return _words(" ".join(before + [m.group()] + after)), (_words(after[0]).pop() if after and _words(after[0]) else "")


def echo(line: str, claim: str) -> bool:
    """The claim read back in a tool's output: its start, most of it, or a long run of it (a draft with another
    first word, a gate's reason quoting the line)."""
    a, b = _clean(line), _clean(ANCHOR.sub(" ", claim))
    if len(b) < 20:
        return False
    m = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return b[:40] in a or m.ratio() >= 0.6 or m.find_longest_match(0, len(a), 0, len(b)).size >= min(30, len(b) // 2)


def _runs(text: str, lines: list[int], calls: list[dict], ctx: dict, whole: bool) -> list[tuple[int | None, str]]:
    """For each line with a bare count: the output line of a recent call that states one of its counts and shares
    the most words around it (at least one besides the number; the same word right after the number counts double;
    ties go to the latest call)."""
    ran = [c for c in reversed(calls) if not c["error"] and not eff.NOT_RUNS.search(c["name"] or "")][:SCAN]
    out: list[tuple[int | None, str]] = []
    rows = text.splitlines()
    for n in lines:
        found = []
        for token in counts(rows[n - 1]):
            word = re.compile(rf"(?<![\w.,]){re.escape(token)}(?![\w]|[.,]\d)")
            claim, unit = _near(rows[n - 1], word)
            for age, c in enumerate(ran):
                cmd = _cmd(c)
                if not cmd:
                    continue
                for line in c["output"].splitlines():
                    if echo(line, rows[n - 1]):  # the claim itself read back (a draft, a gate's reason)
                        continue
                    if word.search(line) and (score := len(claim & _words(line))) >= 2:
                        score += 2 * bool(unit and _near(line, word)[1] == unit)
                        found.append((-score, age, f"run:{cmd} => {_window(line, token)}"))
        for _, _, anchor in sorted(found):
            if _holds(anchor, ctx):
                out.append((n, anchor))
                break
    if whole and not out:
        for c in ran:
            tail = next((ln for ln in reversed(c["output"].splitlines()) if _clean(ln)), None)
            cmd = _cmd(c)
            if tail and cmd and _holds(f"run:{cmd} => {_window(tail, '')}", ctx):
                out.append((None, f"run:{cmd} => {_window(tail, '')}"))
                break
    return out


def ready_anchors(text: str, items: list[dict], *, transcript: str | None = None, github=None) -> list[str]:
    """Lines for the gate's reason: '- line N: `⚓ run:…`' or '- `⚓ pr:…`', each already checked to hold."""
    kinds = {i["kind"] for i in items}
    if not kinds & {"final_no_anchor", "final_bare", "prose"}:
        return []
    ctx = {"github": github, "transcript": transcript}
    calls = eff.tool_calls(eff.transcript_files(transcript)) if transcript else []
    out = [f"- `⚓ {a}`" for a in _github(text, calls, ctx)] if github else []
    if calls:
        # a prose claim with a count ("47 passed") gets the output line with it; one without, the latest run
        bare = sorted({i["line"] for i in items if i["kind"] in ("final_bare", "prose")})
        out += [f"- line {n}: `⚓ {a}`" if n else f"- `⚓ {a}`"
                for n, a in _runs(text, bare, calls, ctx, bool(kinds & {"final_no_anchor", "prose"}))]
    return out[:LIMIT]
