"""Claims about work that has an observable effect not written by the model (audit/11 §5–6, NEXT №39).

The executor writes the anchor itself, as with numbers; buddie checks it, with no model and no reading of prose:

  pr:OWNER/REPO#N=STATE[@SHA]      STATE open | draft | closed | merged. @SHA: for merged, the merge commit; else
                                   the head commit (prefix). HOLDS when GitHub says so now
  ci:OWNER/REPO@SHA[/CHECK]=WHAT   WHAT success | failure | pending: all check runs and commit statuses on SHA
                                   taken together (success: at least one, every one completed as success, neutral
                                   or skipped), or only the check run named CHECK
  run:CMD[ => OUT]                 a tool call in the session transcript whose input (the Bash command) contains
                                   CMD and whose result contains OUT. Without OUT: the call ran and did not error.
                                   CMD may also be a tool_use id (toolu_…). OUT written in the command itself does
                                   not count (`echo "41 passed"` proves nothing)

GitHub goes through the REST API (GITHUB_TOKEN if set; a cloud session's proxy adds its own). The transcript is the
Claude Code jsonl the hooks get as transcript_path; the subagent transcripts next to it are searched too.

What these anchors prove: that the PR is in that state, that checks on that commit ended so, that the session ran
that command and saw that output. Not that the code is right: a green CI on weak tests stays weak (NOTE).
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

HOLDS, BROKEN, UNCHECKABLE = "HOLDS", "BROKEN", "UNCHECKABLE"
NOTE = "pr:/ci:/run: anchors show what happened (PR state, checks on a commit, a command and its output), not that the code is correct"

PR = re.compile(r"^pr:(?P<repo>[\w.-]+/[\w.-]+)#(?P<number>\d+)=(?P<state>open|draft|closed|merged)"
                r"(?:@(?P<sha>[0-9a-f]{7,40}))?$")
CI = re.compile(r"^ci:(?P<repo>[\w.-]+/[\w.-]+)@(?P<sha>[0-9a-f]{7,40})(?:/(?P<check>[^=]+))?"
                r"=(?P<what>success|failure|pending)$")
RUN = re.compile(r"^run:(?P<cmd>.+?)(?:\s+=>\s+(?P<out>.+))?$")
KINDS = ("pr:", "ci:", "run:")
OK_CONCLUSIONS = {"success", "neutral", "skipped"}
NOT_RUNS = re.compile(r"^(mcp__hearthbot__|mcp__claude-code-remote__send_message$|SendMessage$|Write$|Edit$|NotebookEdit$)")
API = os.environ.get("BUDDIE_GITHUB_API", "https://api.github.com")


def is_effect(anchor: str) -> bool:
    return anchor.startswith(KINDS)


# a claim about work with an observable effect written in prose, the thing pr:/ci:/run: anchors are for (NEXT №43):
# "слито", "смержен", "CI зелёный", "тесты прошли", "41 passed", "прогнал"; future and plans ("сольются",
# "прогнать") are not claims. Code spans are left out: `merged` there names a state, it does not claim one
WORK = re.compile(r"(?<!\w)(?:слит[оаы]?|смержен\w*|влит[оаы]?|merged|CI\s+(?:зел[её]н\w*|green|прош[её]л\w*|pass\w*)|"
                  r"тест\w*\s+(?:прош\w*|зел[её]н\w*)|tests?\s+pass\w*|\d+\s+passed|прогнал\w*|прогнан\w*)(?!\w)", re.I)
CODE = re.compile(r"`[^`]*`")


def prose_work(text: str, anchor_rx: re.Pattern, limit: int = 5) -> tuple[int, list[str]]:
    """Lines that claim work done (merged, CI green, tests passed, ran) with no pr:/ci:/run: anchor on the line.
    A signal for the measurement of NEXT №43, never a failure."""
    n, examples = 0, []
    for number, line in enumerate(text.splitlines(), 1):
        if any(is_effect(a) for a in anchor_rx.findall(line)) or not WORK.search(CODE.sub(" ", line)):
            continue
        n += 1
        if len(examples) < limit:
            examples.append(f"line {number}: {line.strip()[:120]}")
    return n, examples


class GitHubUnavailable(Exception):
    pass


def github_get(path: str) -> dict | None:
    """GET a GitHub REST path; None on 404 (no such PR, or a repo this token cannot see)."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "buddie"}
    if token := os.environ.get("BUDDIE_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(API + path, headers=headers), timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise GitHubUnavailable(f"GitHub {error.code} on {path}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise GitHubUnavailable(f"GitHub unreachable: {error}") from error


def _get(ctx: dict, path: str):
    """Cached GET through ctx['github'] (a function like github_get, or None when offline)."""
    get = ctx.get("github")
    if get is None:
        raise GitHubUnavailable("GitHub lookups are off (offline)")
    cache = ctx.setdefault("_cache", {})
    if path not in cache:
        cache[path] = get(path)
    return cache[path]


def _pr(m, ctx: dict) -> dict:
    data = _get(ctx, f"/repos/{m['repo']}/pulls/{m['number']}")
    if data is None:
        return {"status": UNCHECKABLE, "why": f"no PR {m['repo']}#{m['number']} visible (missing, or no access)"}
    state = "merged" if data.get("merged") else ("draft" if data.get("state") == "open" and data.get("draft")
                                                 else data.get("state"))
    sha = data.get("merge_commit_sha") if state == "merged" else (data.get("head") or {}).get("sha")
    seen = {"state": state, "sha": (sha or "")[:12]}
    want = m["state"]
    if state != want and not (want == "open" and state == "draft") and not (want == "closed" and state == "merged"):
        return dict(seen, status=BROKEN, why=f"PR is {state}")
    if m["sha"] and not (sha or "").startswith(m["sha"]):
        return dict(seen, status=BROKEN, why=f"{'merge' if state == 'merged' else 'head'} commit is {(sha or '?')[:12]}")
    return dict(seen, status=HOLDS)


def _runs(m, ctx: dict) -> list[dict]:
    """Every check run and commit status on the SHA as {name, done, ok}."""
    out, page = [], 1
    while True:
        data = _get(ctx, f"/repos/{m['repo']}/commits/{m['sha']}/check-runs?per_page=100&page={page}")
        if data is None:
            return []
        runs = data.get("check_runs", [])
        out += [{"name": r["name"], "done": r["status"] == "completed", "ok": r.get("conclusion") in OK_CONCLUSIONS,
                 "conclusion": r.get("conclusion") or r["status"]} for r in runs]
        if len(runs) < 100:
            break
        page += 1
    statuses = _get(ctx, f"/repos/{m['repo']}/commits/{m['sha']}/status") or {}
    out += [{"name": s["context"], "done": s["state"] != "pending", "ok": s["state"] == "success",
             "conclusion": s["state"]} for s in statuses.get("statuses", [])]
    return out


def _ci(m, ctx: dict) -> dict:
    runs = _runs(m, ctx)
    if m["check"]:
        runs = [r for r in runs if r["name"] == m["check"].strip()]
    if not runs:
        what = f"check {m['check'].strip()!r}" if m["check"] else "checks"
        return {"status": UNCHECKABLE, "why": f"no {what} on {m['repo']}@{m['sha']} (missing commit, or no access)"}
    got = "pending" if not all(r["done"] for r in runs) else ("success" if all(r["ok"] for r in runs) else "failure")
    seen = {"ci": got, "checks": {r["name"]: r["conclusion"] for r in runs}}
    if got != m["what"]:
        bad = [f"{r['name']}={r['conclusion']}" for r in runs if not r["ok"]][:5]
        return dict(seen, status=BROKEN, why=f"checks are {got}" + (f" ({', '.join(bad)})" if bad else ""))
    return dict(seen, status=HOLDS)


def transcript_files(path: str | Path) -> list[Path]:
    """The session transcript and its subagents' transcripts (<session>/subagents/*.jsonl next to it)."""
    path = Path(path)
    files = [path] if path.is_file() else []
    side = path.with_suffix("")
    return files + sorted(side.glob("**/*.jsonl")) if side.is_dir() else files


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


def tool_calls(files: list[Path]) -> list[dict]:
    """Every tool_use with its tool_result: {id, name, input (command or JSON), output, error}."""
    calls, results = {}, {}
    for f in files:
        for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            content = (entry.get("message") or {}).get("content") if isinstance(entry, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("id"):
                    args = block.get("input") or {}
                    shown = args.get("command") if isinstance(args.get("command"), str) else json.dumps(args, ensure_ascii=False)
                    calls[block["id"]] = {"id": block["id"], "name": block.get("name"), "input": shown}
                elif block.get("type") == "tool_result" and block.get("tool_use_id"):
                    results[block["tool_use_id"]] = (_text(block.get("content")), bool(block.get("is_error")))
    return [dict(c, output=results[i][0], error=results[i][1]) for i, c in calls.items() if i in results]


def _squash(s: str) -> str:
    return " ".join(s.split())


def _run(m, ctx: dict) -> dict:
    if not ctx.get("transcript"):
        return {"status": UNCHECKABLE, "why": "no session transcript (hooks get transcript_path; CLI --transcript)"}
    key = ("calls", str(ctx["transcript"]))
    cache = ctx.setdefault("_cache", {})
    if key not in cache:
        cache[key] = tool_calls(transcript_files(ctx["transcript"]))
    cmd, out = m["cmd"].strip(), m["out"]
    if cmd.startswith("toolu_"):
        matched = [c for c in cache[key] if c["id"] == cmd]
    else:  # tool calls that only carry the report (reply, send_message, Write) are not runs
        matched = [c for c in cache[key] if cmd in c["input"] and not NOT_RUNS.search(c["name"] or "")]
    if not matched:
        return {"status": BROKEN, "why": f"no tool call with {cmd!r} in the transcript"}
    if out is None:
        ok = [c for c in matched if not c["error"]]
        if ok:
            return {"status": HOLDS, "tool_use_id": ok[-1]["id"], "command": ok[-1]["input"][:200]}
        return {"status": BROKEN, "tool_use_id": matched[-1]["id"], "why": "every matching call returned an error"}
    want = _squash(out)
    for c in reversed(matched):
        if want in _squash(c["output"]):
            if want in _squash(c["input"]) or f"run:{cmd}" in c["output"]:  # echoed, or a report read back
                continue
            return {"status": HOLDS, "tool_use_id": c["id"], "command": c["input"][:200],
                    **({"tool_error": True} if c["error"] else {})}
    if any(want in _squash(c["input"]) for c in matched):
        return {"status": BROKEN, "why": f"{out!r} is written in the command itself, not produced by it"}
    tail = _squash(matched[-1]["output"])[-160:]
    return {"status": BROKEN, "tool_use_id": matched[-1]["id"], "why": f"output has no {out!r}; it ends: …{tail}"}


def check(anchor: str, ctx: dict | None) -> dict:
    ctx = ctx if ctx is not None else {}
    for rx, fn in ((PR, _pr), (CI, _ci), (RUN, _run)):
        if m := rx.match(anchor):
            try:
                return {"anchor": anchor, "kind": anchor.split(":", 1)[0], **fn(m, ctx)}
            except GitHubUnavailable as error:
                return {"anchor": anchor, "kind": anchor.split(":", 1)[0], "status": UNCHECKABLE, "why": str(error)}
    return {"anchor": anchor, "status": BROKEN,
            "why": "not an effect anchor: expected pr:OWNER/REPO#N=STATE[@SHA], ci:OWNER/REPO@SHA[/CHECK]=success|"
                   "failure|pending or run:CMD[ => OUT]"}
