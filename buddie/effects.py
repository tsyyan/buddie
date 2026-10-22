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

GitHub goes through the REST API (BUDDIE_GITHUB_TOKEN or the plugin's token setting if given; a cloud session's
proxy adds its own). The transcript is the
Claude Code jsonl the hooks get as transcript_path; the subagent transcripts next to it are searched too.

What these anchors prove: that the PR is in that state, that checks on that commit ended so, that the session ran
that command and saw that output. Not that the code is right: a green CI on weak tests stays weak (NOTE).
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import weakref
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
# tools that carry the report or write a file, not runs; SubagentHandback hands a subagent's report back (E017)
NOT_RUNS = re.compile(r"^(mcp__hearthbot__|mcp__claude-code-remote__send_message$|SendMessage$|SubagentHandback$|"
                      r"Write$|Edit$|NotebookEdit$)")
DEFAULT_API = "https://api.github.com"
ENV_API = os.environ.get("BUDDIE_GITHUB_API")  # GitHub Enterprise; the hook's environment, so the agent's to set
API = ENV_API or DEFAULT_API


def api() -> tuple[str, str]:
    """The API base pr:/ci: are asked of, and who chose it: "policy" (the protected policy's [evidence]
    github_api, which sets BUDDIE_GITHUB_API aside), "environment" (BUDDIE_GITHUB_API) or "default". The token goes
    only there, so an API from the environment is also where the token goes (findings.py does not count its answers
    as observed from GitHub)."""
    from buddie import policy
    limits = policy.current().effective
    if limits is not None and limits.github_api:
        return limits.github_api, "policy"
    return API, "environment" if API != DEFAULT_API else "default"


def is_effect(anchor: str) -> bool:
    return anchor.startswith(KINDS)


# a claim about work with an observable effect written in prose, the thing pr:/ci:/run: anchors are for (NEXT №43):
# "слито", "смержен", "CI зелёный", "тесты прошли", "41 passed", "прогнал"; future and plans ("сольются",
# "прогнать") are not claims. Code spans are left out: `merged` there names a state, it does not claim one
WORK = re.compile(r"(?<!\w)(?:слит[оаы]?|смержен\w*|влит[оаы]?|merged|CI\s+(?:зел[её]н\w*|green|прош[её]л\w*|pass\w*)|"
                  r"тест\w*\s+(?:прош\w*|зел[её]н\w*)|tests?\s+pass\w*|\d+\s+passed|прогнал\w*|прогнан\w*)(?!\w)", re.I)
CODE = re.compile(r"`[^`]*`")
# a line quoted in «…» or “…” is cited, not claimed (NEXT №63: this thread's own reply quoting «в main влиты №40…»)
QUOTED = re.compile(r"«[^»\n]*»|“[^”\n]*”")
# not claims either (NEXT №52, false hits of №45): a word right after plural «которые» describes a kind of thing
# («шаги, которые уже влиты, но не запущены»), and a clause after a future or infinitive check verb is a plan («я
# проверю, что CI зелёный»). Still claims: past «проверил, что CI зелёный», singular «lab#64, который уже влит» and
# «PR, которые я открыл, слиты» (comma). Missed: «#18 и #19, которые слиты» (a specific plural reads as a kind)
DESCRIBES = re.compile(r"(?<!\w)которые(?:\s+[^\s,;.:!?]+){0,2}\s+$", re.I)
PLANS = re.compile(r"(?<!\w)(?:провер|убед|удостовер|посмотр|просле|дожд|увид|узна|свер)\w*"
                   r"(?:ю|у|юсь|усь|им|ем|ём|имся|емся|ёмся|ит|ет|ёт|ится|ется|ить|ять|еть|ться|ишь|ешь|ёшь)"
                   r"\s*,?\s+(?:что|ли|когда)(?:\s+[^\s,;.:!?]+){0,3}\s+$", re.I)

# a negated word states work not done («PR ещё не слит», «not merged»), not a claim (NEXT №63: the line now blocks)
NEGATED = re.compile(r"(?<!\w)(?:не|not)(?:\s+(?:yet|ещё|еще))?\s+$", re.I)
# nor a condition or a plan («Once automerge has merged it, start row 119», «когда PR будет слит»): the word sits in a
# clause opened by once/after/when/if/until… within three words (NEXT №128: a false return of №82), and nor is an
# adjective before a noun («a container that already has the merged code», the other false return of №82)
CONDITION = re.compile(r"(?<!\w)(?:once|as\s+soon\s+as|after|when(?:ever)?|if|until|unless|before|"
                       r"после\s+того,?\s+как|как\s+только|когда|если|пока\s+не|до\s+того,?\s+как)"
                       r"(?:\s+[^\s,;.:!?]+){0,3}\s+$", re.I)
ADJECTIVE = re.compile(r"(?<!\w)(?:the|a|an|its|their|our|my|your|his|her)"
                       r"(?:\s+(?:already|freshly|newly|just|recently))?\s+$", re.I)
NOUN_AFTER = re.compile(r"\s+(?!(?:at|in|into|on|onto|to|by|after|before|and|but|or|with|without|as|via|from|for|"
                        r"cleanly|today|yesterday|now|already|successfully)(?!\w))[A-Za-z]", re.I)


def claims_work(line: str) -> bool:
    line = QUOTED.sub(" ", CODE.sub(" ", line))
    return any(not DESCRIBES.search(line[:m.start()]) and not PLANS.search(line[:m.start()])
               and not NEGATED.search(line[:m.start()]) and not CONDITION.search(line[:m.start()])
               and not (m.group().lower() == "merged" and ADJECTIVE.search(line[:m.start()])
                        and NOUN_AFTER.match(line, m.end()))
               for m in WORK.finditer(line))


def prose_lines(text: str, anchor_rx: re.Pattern) -> list[int]:
    """Numbers of the lines that claim work done (merged, CI green, tests passed, ran) with no pr:/ci:/run: anchor
    on the line."""
    return [number for number, line in enumerate(text.splitlines(), 1)
            if not any(is_effect(a) for a in anchor_rx.findall(line)) and claims_work(line)]


def prose_work(text: str, anchor_rx: re.Pattern, limit: int = 5) -> tuple[int, list[str]]:
    """The count of prose_lines and the first `limit` of them. A final answer is returned for them (NEXT №63,
    buddie/hook.py); elsewhere a signal for the measurement of NEXT №43."""
    numbers, lines = prose_lines(text, anchor_rx), text.splitlines()
    return len(numbers), [f"line {n}: {lines[n - 1].strip()[:120]}" for n in numbers[:limit]]


class GitHubUnavailable(Exception):
    pass


def _origin(url: str) -> tuple:
    u = urllib.parse.urlsplit(url)
    scheme = u.scheme.lower()
    return scheme, (u.hostname or "").lower(), u.port or {"https": 443, "http": 80}.get(scheme)


def github_get(path: str) -> dict | None:
    """GET a GitHub REST path; None on 404 (no such PR, or a repo this token cannot see).

    The token goes only to the API it belongs with. BUDDIE_GITHUB_TOKEN comes from the hook's environment, as
    BUDDIE_GITHUB_API does, so it may go to that API. The plugin's token setting is the person's and goes only to
    the default API or the protected policy's github_api, never to one the environment named (the agent could name
    its own server and receive it). It is sent as an unredirected header, which urllib never copies to a redirect's
    target; an answer that came from another origin than the API's (scheme, host, port) is not taken
    (GitHubUnavailable: the anchor stays unchecked). A redirect on the API's own origin, as a renamed repo's, is
    asked again there with the token. The request goes through urllib's installed opener: the remote server's
    guarded one, the hook's isolated collector, or urllib's default."""
    from buddie.verbatim.store import read_body
    base, chosen = api()
    home = _origin(base)
    # only a token given to buddie by name: BUDDIE_GITHUB_TOKEN, or the plugin setting (Claude Code exports userConfig
    # as CLAUDE_PLUGIN_OPTION_*). An ambient GITHUB_TOKEN is never picked up and sent (1.1); in CI set
    # BUDDIE_GITHUB_TOKEN: ${{ github.token }}. An unset option may arrive as the literal placeholder: skip it.
    names = ("BUDDIE_GITHUB_TOKEN",) + (("CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN",) if chosen != "environment" else ())
    token = next((v for v in (os.environ.get(k, "") for k in names) if v and not v.startswith("${")), None)

    def ask(url: str):
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "buddie"})
        if token:
            req.add_unredirected_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=20) as r:
            if _origin(r.geturl()) != home:
                raise GitHubUnavailable(f"GitHub redirected {path} to another host; its answer is not taken")
            return json.loads(read_body(r))
    url = base + path
    for attempt in range(2):
        try:
            return ask(url)
        except urllib.error.HTTPError as error:
            final = error.geturl() or url
            if _origin(final) != home:
                raise GitHubUnavailable(f"GitHub redirected {path} to another host; its answer is not taken") from error
            if error.code == 404 and token and final != url and attempt == 0:
                url = final  # redirected on the API's origin without the token: ask there with it
                continue
            if error.code == 404:
                return None
            raise GitHubUnavailable(f"GitHub {error.code} on {path}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise GitHubUnavailable(f"GitHub unreachable: {error}") from error
    return None


# Which GitHub GETs are buddie's own collection (findings.github_provenance), by identity: github_get and the
# wrappers buddie's own code makes of it (remote.public_github). Kept here, not as an attribute of the function: a
# caller can set any attribute on a callback it hands in, while handing one in adds nothing to this list. Weak, so a
# wrapper the remote server drops after its call is not kept alive.
_OWN_GETS: weakref.WeakSet = weakref.WeakSet()


def own_get(get) -> bool:
    """Whether `get` is buddie's own GitHub GET: github_get, or a wrapper of it registered by buddie's code."""
    return get is github_get or any(get is g for g in _OWN_GETS)  # `is`: a callback's __eq__ or __hash__ is not asked


def _own_wrapper(wrapper, inner):
    """`wrapper`, registered as buddie's own when `inner` is (remote.public_github). For buddie's modules: a caller
    that runs code in this interpreter could call it, as it could replace github_get itself; a caller that only
    hands verify a callback cannot."""
    if own_get(inner):
        _OWN_GETS.add(wrapper)
    return wrapper


def _get(ctx: dict, path: str):
    """Cached GET through ctx['github'] (a function like github_get, or None when offline)."""
    get = ctx.get("github")
    if get is None:
        raise GitHubUnavailable("GitHub lookups are off (offline)")
    if any(part in (".", "..") for part in path.split("?")[0].split("/")):  # pr:../x#1: no other API path
        raise GitHubUnavailable(f"not a repository path: {path}")
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


def claude_transcript(files: list[Path]) -> bool:
    """Whether the files are a Claude Code transcript (entries with a `message` whose content is a list). Codex
    passes its own session log as transcript_path; its tool calls have another shape, so `run:` is not judged there."""
    for f in files:
        for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict) and isinstance((entry.get("message") or {}).get("content"), list):
                return True
    return False


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
        files = transcript_files(ctx["transcript"])
        cache[key] = tool_calls(files) if claude_transcript(files) else None
    if cache[key] is None:
        return {"status": UNCHECKABLE, "why": "the transcript is not a Claude Code session (e.g. Codex): run: is "
                                              "judged only against Claude Code transcripts"}
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
