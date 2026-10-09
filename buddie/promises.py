"""The launch gate and the journal of open promises (0.7, audit/18 §5 п. 2, NEXT №69; 0.7.2 №85; 0.7.3 №83).

Launch gate. buddie.toml [launch] `tools` names the tools that launch work (a subagent, a thread, a cloud session);
with no such section the gate is off. PreToolUse on such a tool: the row it launches is the first №N of its short
fields (description, title, name), else of the first line of its prompt (a №N after ←, «родитель», «parent» or
«после» is a parent or a condition, not the row). A launch that names no row passes and is logged `unqueued`. A
launch of row N passes only with a basis in its own text:

  ⚓ NEXT.md@<commit>      the queue at that commit gives row N the verdict `auto` (mandate.py, the rule of chain.py)
  ⚓ choice:<id>=№N        the journal holds the person's choice of №N (summary.check_choice)

otherwise it is returned (exit 2) with the reasons and, when the queue at HEAD gives `auto`, the anchor to copy.
A launch with a basis is still returned when the row is taken (0.7.2, NEXT №85): the verdict for row N in the
automerge comment on the PR merged as the anchor's commit says `free: false` ([launch] `comment`: the comment's
first words; its fenced ```json block holds `chain.py merged`), or the [launch] `free` command («{n}» is the row;
JSON with `free` and `reasons`, exit 1 when taken) says so now. A comment's `free: true` is as of the merge, so the
command runs after it too: a second launch from the same comment finds the first thread's branch. With neither the
gate does not know and lets the launch through, logged `free: null`.
The verdict is judged now (0.7.3, NEXT №83): a time condition of row N comes due as in chain.py, the delay counted
from the commit that brought the row's text (Mandate.verdict_now).
Each launch writes a `launch` line to the journal.

Promises. A text that leaves the session (the gate let it through: the final answer at Stop, a reply at
PreToolUse) is read for promises, codewise: «запущу №N» with its condition («после влития lab#M», «как только
сольётся lab#M»: the PR is merged; «после №M»: row M is done; none: now), and «сводка будет», «пришлю сводку» (due
when no subagent is live and none is running and a result came after the promise). Quotes («…», `…`) and lines
starting with `>` are not promises; a promise names its row, so «напиши «да», и я запущу синхронизацию» is none.
Each goes to the journal as a `promise` line. A launch promise is kept by a passed launch of its row or by the row's
status (запущено, выполнено); a summary promise by a later `choice` line or a text that starts with «Сводка»; a
line `buddie: не запускаю №N …` (or `buddie: сводки не будет …`) drops it. Promises older than 48 hours expire.

SessionStart prints the open promises of all sessions (the shared folder holds them after a session is recycled:
audit/12, the lost autostart of №42); Stop returns the turn once per promise of this session whose condition holds.

Env: BUDDIE_PROMISES=0 turns promises off; BUDDIE_LAUNCH=<regex> sets the launch tools (0 turns the gate off);
BUDDIE_FREE=<command> sets the free command (0 turns it off); BUDDIE_GITHUB=0 skips the automerge comment.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROW = re.compile(r"№\s?(\d+)")
SHORT_KEYS = ("description", "title", "name", "subject")
LONG_KEYS = ("prompt", "message", "text", "task")
NOT_THE_ROW = re.compile(r"(?:←|родител\w*|parent|после(?: влития)?)\s*№\s?\d+", re.I)
LAUNCH_VERB = re.compile(r"(?<!\w)(запущу|запустим|запустится|стартую)(?!\w)", re.I)
PR_COND = re.compile(r"(?:после (?:влития|слияния|мержа)|как только (?:сольётся|сольют|вольётся|влит\w*)|"
                     r"когда (?:сольётся|сольют|вольётся))\s+(?P<repo>[\w.-]+(?:/[\w.-]+)?)?#(?P<n>\d+)", re.I)
ROW_COND = re.compile(r"(?:после(?: влития)?|как только (?:будет )?(?:выполн|закрыт|влит)\w*|"
                      r"когда (?:будет )?(?:выполн|закрыт)\w*)\s+(?:строк\w+ )?№\s?(?P<n>\d+)", re.I)
SUMMARY = re.compile(r"сводк\w*\s+(?:\w+\s+)?(?:будет|выйдет|появится|пришл\w+)|"
                     r"(?<!\w)(?:пришлю|дам|соберу|сделаю|напишу|выложу)\s+(?:\w+\s+){0,2}?сводк", re.I)
QUOTED = re.compile(r"«[^«»]*»|`[^`]*`|“[^“”]*”")
SENTENCE = re.compile(r"(?<=[.!?…])\s+|\n+")
DISCLOSED = re.compile(r"^\s*buddie\s*:(?P<rest>.*)$", re.I | re.M)
DROP_LAUNCH = re.compile(r"(не запуска\w*|не запущу|снима\w*|отмен\w*)[^№]{0,40}№\s?(\d+)", re.I)
DROP_SUMMARY = re.compile(r"сводк\w* не будет|(?:снима\w*|отмен\w*)[^.]{0,40}сводк", re.I)
SUMMARY_SENT = re.compile(r"^\s*(?:#+\s*|\*\*)?Сводка\b", re.M)
STARTED = ("запущено", "выполнено")
EXPIRE_HOURS = 48
MAX_LINES = 10


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(at: str) -> datetime:
    return datetime.fromisoformat(at.replace("Z", "+00:00"))


def on() -> bool:
    return os.environ.get("BUDDIE_PROMISES", "1") != "0"


def repos_of(event: dict) -> list[Path]:
    from buddie.anchors import find_repos
    env = [Path(p) for p in os.environ.get("BUDDIE_REPOS", "").split(os.pathsep) if p]
    return env or find_repos(Path(event.get("cwd") or os.getcwd()))


def launch_config(repos: list[Path]) -> dict:
    """The [launch] section of the first buddie.toml that has one."""
    for repo in repos:
        path = repo / "buddie.toml"
        if path.is_file() and (section := tomllib.loads(path.read_text(encoding="utf-8")).get("launch")):
            return section
    return {}


def launch_tools(repos: list[Path]) -> re.Pattern | None:
    env = os.environ.get("BUDDIE_LAUNCH")
    if env is not None:
        return None if env in ("", "0") else re.compile(env)
    tools = launch_config(repos).get("tools")
    return re.compile(tools) if tools else None


def is_launch(event: dict) -> bool:
    if event.get("hook_event_name") != "PreToolUse" or not event.get("tool_name"):
        return False
    tools = launch_tools(repos_of(event))
    return bool(tools and tools.fullmatch(event["tool_name"]))


# --- launch gate --------------------------------------------------------------------------------------------------

def strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in strings(v)]
    return []


def launched_row(tool_input: dict) -> int | None:
    heads = [v for k in SHORT_KEYS if isinstance(v := tool_input.get(k), str)]
    heads += [next((line for line in v.splitlines() if line.strip()), "")
              for k in LONG_KEYS if isinstance(v := tool_input.get(k), str)]
    for head in heads:
        if m := ROW.search(NOT_THE_ROW.sub(" ", head)):
            return int(m.group(1))
    return None


def _head(cfg: dict) -> str | None:
    """The commit the ready anchor names: origin/main, where the queue is merged, else HEAD. A working branch's HEAD
    carries its own commits (the row's «запущено»), and the verdict there is not the one on main (live run, №77)."""
    for ref in ("origin/main", "HEAD"):
        out = subprocess.run(["git", "-C", cfg["repo"], "rev-parse", "--verify", "-q", "--short", f"{ref}^{{commit}}"],
                             capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    return None


def basis(n: int, text: str, cfg: dict | None, transcript: str | None = None) -> tuple[dict | None, list[str]]:
    """The anchor in `text` that lets row n launch ({by, anchor}), else None and why each anchor did not; a choice on a
    decision card is read from the session's `transcript` too (buddie/decisions.py)."""
    from buddie import mandate, summary
    from buddie.anchors import ANCHOR, FILE_AT
    why = []
    for a in ANCHOR.findall(text):
        if m := summary.CHOICE.match(a):
            if not re.match(rf"{n}(?!\d)", summary._norm(m["step"])):
                why.append(f"`{a}` names another step, not №{n}")
                continue
            c = summary.check_choice(a, {"transcript": transcript})
            if c["status"] == summary.HOLDS:
                return {"by": "choice", "anchor": a}, why
            why.append(f"`{a}` {c['status']}: {c.get('why', '')}")
        elif (m := FILE_AT.match(a)) and cfg and Path(m["path"]).name == Path(cfg["queue"]).name:
            try:
                man = mandate.Mandate(cfg, m["commit"])
            except FileNotFoundError:
                why.append(f"`{a}`: no such commit in {cfg['repo']}")
                continue
            if n not in man.table:
                why.append(f"`{a}`: no row №{n} in {cfg['queue']} at {m['commit']}")
                continue
            v = man.verdict_now(n)
            if v["verdict"] == "auto":
                return {"by": "verdict", "anchor": a}, why
            why.append(f"`{a}`: verdict ask ({'; '.join(v['reasons'])})")
    return None, why


FENCED_JSON = re.compile(r"```json\s*\n(.*?)\n```", re.S)
MERGE_PR = re.compile(r"Merge pull request #(\d+)\b")
FREE_TIMEOUT = 20


def comment_verdict(n: int, commit: str, cfg: dict, launch: dict) -> dict | None:
    """Row n's verdict in the automerge comment on the PR merged as `commit` ({…, pr}), None when there is none."""
    prefix = launch.get("comment")
    if not prefix or os.environ.get("BUDDIE_GITHUB", "1") == "0":
        return None
    repo = Path(cfg["repo"])
    out = subprocess.run(["git", "-C", str(repo), "show", "-s", "--format=%H%n%s", commit],
                         capture_output=True, text=True)
    if out.returncode or len(out.stdout.split("\n")) < 2:
        return None
    sha, subject = out.stdout.split("\n")[:2]
    if not (m := MERGE_PR.search(subject)) or not (slug := _slug(repo)):
        return None
    from buddie.effects import GitHubUnavailable, github_get
    try:
        comments = github_get(f"/repos/{slug}/issues/{m[1]}/comments?per_page=100") or []
    except GitHubUnavailable:
        return None
    for c in reversed(comments if isinstance(comments, list) else []):
        body = c.get("body") or ""
        if not body.startswith(prefix) or not (j := FENCED_JSON.search(body)):
            continue
        try:
            record = json.loads(j[1])
        except json.JSONDecodeError:
            continue
        if not str(record.get("merge", "")).startswith(sha[:7]):
            continue
        for v in record.get("verdicts") or []:
            if v.get("n") == n:
                return dict(v, pr=f"{slug}#{m[1]}")
    return None


def free_now(n: int, cfg: dict, launch: dict) -> dict | None:
    """The [launch] free command's answer for row n ({free, reasons}), None when it is off or gives none."""
    cmd = os.environ.get("BUDDIE_FREE", launch.get("free") or "")
    if cmd in ("", "0"):
        return None
    try:
        out = subprocess.run(cmd.replace("{n}", str(int(n))), shell=True, cwd=cfg["repo"], capture_output=True,
                             text=True, timeout=FREE_TIMEOUT)
        data = json.loads(out.stdout.strip().splitlines()[-1])
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError, IndexError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("free"), bool):
        return None
    return {"free": data["free"], "reasons": [str(r) for r in data.get("reasons") or []]}


def taken(n: int, found: dict, cfg: dict | None, repos: list[Path]) -> dict:
    """Whether row n, which has a basis, is still free: {free: True|False|None, by, reasons}."""
    from buddie.anchors import FILE_AT
    if not cfg:
        return {"free": None, "by": None, "reasons": []}
    launch = launch_config(repos)
    if found["by"] == "verdict" and (m := FILE_AT.match(found["anchor"])):
        v = comment_verdict(n, m["commit"], cfg, launch)
        if v is not None and v.get("free") is False:
            return {"free": False, "by": f"automerge {v['pr']}", "reasons": v.get("free_reasons") or []}
    now = free_now(n, cfg, launch)
    if now is not None:
        return {"free": now["free"], "by": "free", "reasons": now["reasons"]}
    return {"free": None, "by": None, "reasons": []}


def gate(event: dict, err) -> int:
    from buddie import mandate
    from buddie.hook import log
    tin = event.get("tool_input") or {}
    n = launched_row(tin)
    entry = {"at": now_iso(), "session": event.get("session_id"), "event": "PreToolUse", "tool": event.get("tool_name"),
             "fields": sorted(tin)}
    if n is None:
        log(dict(entry, launch={"row": None, "outcome": "unqueued"}))
        return 0
    repos = repos_of(event)
    cfg = mandate.find_config(repos)
    found, why = basis(n, "\n".join(strings(tin)), cfg, event.get("transcript_path"))
    if found:
        t = taken(n, found, cfg, repos)
        if t["free"] is False:
            log(dict(entry, launch={"row": n, "outcome": "taken", **found, "free": False, "free_by": t["by"],
                                    "reasons": t["reasons"]}))
            print(f"buddie: строка №{n} уже взята ({t['by']}), запуск возвращён. Не запускай её второй раз: сверь "
                  f"треды и ветки; если строку перенумеровали, запускай по новому номеру.", file=err)
            for item in t["reasons"] or ["free: false без причин"]:
                print(f"- {item}", file=err)
            return 2
        log(dict(entry, launch={"row": n, "outcome": "passed", **found, "free": t["free"], "free_by": t["by"]}))
        return 0
    log(dict(entry, launch={"row": n, "outcome": "blocked", "reasons": why or ["no basis anchor"]}))
    print(f"buddie: запуск №{n} без основания. Запуск строки очереди проходит только с вердиктом auto на якоре "
          f"`⚓ {cfg['queue'] if cfg else 'NEXT.md'}@<коммит влития>` или с выбором человека `⚓ choice:<id>=№{n}` "
          f"в тексте запуска.", file=err)
    for item in why:
        print(f"- {item}", file=err)
    head = _head(cfg) if cfg else None
    if head:
        try:
            v = mandate.Mandate(cfg, head)
            verdict = v.verdict_now(n) if n in v.table else None
            if verdict and verdict["verdict"] == "auto":
                print(f"Готовый якорь, проверен сейчас: `⚓ {cfg['queue']}@{head}`", file=err)
            elif n in v.table:
                print(f"На {head} вердикт №{n} ask: {'; '.join(verdict['reasons'])}. Нужен выбор человека.",
                      file=err)
        except FileNotFoundError:
            pass
    return 2


# --- promises -----------------------------------------------------------------------------------------------------

def extract(text: str) -> list[dict]:
    """The promises in a text that leaves the session: [{kind, row?, cond, text}]."""
    plain = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">")
                      and not DISCLOSED.match(line))
    out = []
    for raw in SENTENCE.split(plain):
        s = QUOTED.sub(lambda m: " " * len(m.group(0)), raw)
        if not s.strip():
            continue
        sentence = re.sub(r"\s+", " ", raw).strip()[:300]
        if LAUNCH_VERB.search(s):
            cond, spans = {"kind": "now"}, []
            if m := PR_COND.search(s):
                cond, spans = {"kind": "pr", "repo": m["repo"] or "", "n": int(m["n"])}, [m.span()]
            elif m := ROW_COND.search(s):
                cond, spans = {"kind": "row", "n": int(m["n"])}, [m.span()]
            rest = "".join(" " if any(a <= i < b for a, b in spans) else ch for i, ch in enumerate(s))
            rows = [int(r.group(1)) for r in ROW.finditer(NOT_THE_ROW.sub(" ", rest))]
            if rows:
                out.append({"kind": "launch", "row": rows[0], "cond": cond, "text": sentence})
                continue
        if SUMMARY.search(s):
            out.append({"kind": "summary", "row": None, "cond": {"kind": "idle"}, "text": sentence})
    return out


def promise_id(session: str | None, p: dict) -> str:
    key = json.dumps([session, p["kind"], p["row"], re.sub(r"\W+", " ", p["text"]).casefold().strip()],
                     ensure_ascii=False)
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def record(event: dict, text: str) -> list[dict]:
    """Journal the promises of a text the gate let out, and what the text keeps or drops."""
    from buddie.hook import log
    if not on() or not text.strip():
        return []
    session = event.get("session_id")
    base = {"at": now_iso(), "session": session, "event": event.get("hook_event_name"), "tool": event.get("tool_name")}
    known = {e["promise"]["id"] for e in lines("promise")}
    found = extract(text)
    from buddie import config
    words = config.journal_text(config.of_event(event)[1])
    out = []
    for p in found:
        p = dict(p, id=promise_id(session, p))
        if p["id"] not in known:  # without [journal] text the line keeps the sentence's sha256, not the sentence
            log(dict(base, promise=p if words else dict(
                {k: v for k, v in p.items() if k != "text"},
                sha256=hashlib.sha256(p["text"].encode("utf-8")).hexdigest())))
            known.add(p["id"])
        out.append(p)
    drops = []
    for m in DISCLOSED.finditer(text):
        drops += [{"kind": "launch", "row": int(d.group(2))} for d in DROP_LAUNCH.finditer(m["rest"])]
        if DROP_SUMMARY.search(m["rest"]):
            drops.append({"kind": "summary", "row": None})
    if SUMMARY_SENT.search(text) and not any(p["kind"] == "summary" for p in found):
        drops.append({"kind": "summary", "row": None, "kept": True})
    if drops:
        log(dict(base, settle=drops))
    return out


def lines(key: str, paths=None) -> list[dict]:
    """Journal lines that carry `key` (files or dirs of *.jsonl; default the hook's own), each once."""
    from buddie.hook import journal_paths
    files = []
    for p in map(Path, paths if paths is not None else journal_paths()):
        files += sorted(p.glob("*.jsonl")) if p.is_dir() else [p] if p.is_file() else []
    out, seen = [], set()
    for f in files:
        for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if (key and f'"{key}"' not in raw) or raw in seen:
                continue
            seen.add(raw)
            try:
                e = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(e, dict) and (not key or e.get(key) is not None) and e.get("at"):
                out.append(e)
    out.sort(key=lambda e: e["at"])  # stable: lines of the same second keep the order they were written in
    return [dict(e, _i=i) for i, e in enumerate(out)]


def merged(repo: str, n: int, repos: list[Path]) -> bool:
    """PR #n is merged: its merge commit is in a local repo, or GitHub says so (BUDDIE_GITHUB=0 skips it)."""
    for r in repos:
        for grep in (f"Merge pull request #{n} ", f"(#{n})"):
            out = subprocess.run(["git", "-C", str(r), "log", "--all", "-F", "--grep", grep, "-1", "--format=%h"],
                                 capture_output=True, text=True)
            if out.returncode == 0 and out.stdout.strip():
                return True
    if os.environ.get("BUDDIE_GITHUB", "1") == "0":
        return False
    from buddie.effects import GitHubUnavailable, github_get
    slugs = [repo] if "/" in repo else [s for r in repos if (s := _slug(r)) and (not repo or s.endswith("/" + repo))]
    for slug in slugs:
        try:
            if (github_get(f"/repos/{slug}/pulls/{n}") or {}).get("merged"):
                return True
        except GitHubUnavailable:
            return False
    return False


def _slug(repo: Path) -> str | None:
    out = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"], capture_output=True, text=True)
    m = re.search(r"([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", out.stdout.strip()) if out.returncode == 0 else None
    return f"{m[1]}/{m[2]}" if m else None


def _status(cfg: dict | None, n: int) -> str:
    from buddie import mandate
    if not cfg:
        return ""
    try:
        row = mandate.Mandate(cfg).table.get(n)
    except FileNotFoundError:
        return ""
    return row["status"] if row else ""


def holds(p: dict, repos: list[Path], cfg: dict | None, event: dict | None = None) -> bool:
    """Whether the promise's condition holds now."""
    from buddie import summary
    c = p["cond"]
    if c["kind"] == "now":
        return True
    if c["kind"] == "pr":
        return merged(c.get("repo", ""), c["n"], repos)
    if c["kind"] == "row":
        return bool(cfg) and _status(cfg, c["n"]).startswith(cfg["done"])
    if c["kind"] == "idle":
        if event is None:
            return False
        state = summary.load(p["session"])
        live = [a for a in state["live"] if a not in {x["agent_id"] for x in summary.lost_agents(state)}]
        after = any(r["at"] >= p["at"] for r in state["results"])
        return after and not live and not summary._running(event.get("background_tasks"))
    return False


def open_promises(repos: list[Path], cfg: dict | None, now: datetime | None = None, paths=None) -> list[dict]:
    """Promises not kept, not dropped and not expired, oldest first: [{…promise, session, at}]."""
    now = now or datetime.now(timezone.utc)
    every = lines("", paths)
    launches = [e for e in every if (e.get("launch") or {}).get("outcome") in ("passed", "taken")]  # taken: it runs
    choices = [e for e in every if e.get("choice")]
    settles = [e for e in every if e.get("settle")]
    out = []
    for e in (e for e in every if e.get("promise")):
        p = dict(e["promise"], session=e.get("session"), at=e["at"], _i=e["_i"])
        if now - _parse(p["at"]) > timedelta(hours=EXPIRE_HOURS):
            continue
        settled = any(s.get("session") == p["session"] and s["_i"] > p["_i"]
                      and any(d["kind"] == p["kind"] and d.get("row") == p["row"] for d in s["settle"])
                      for s in settles)
        if p["kind"] == "launch":
            kept = any(x["launch"].get("row") == p["row"] and _parse(x["at"]) >= _parse(p["at"]) - timedelta(hours=1)
                       for x in launches) or _status(cfg, p["row"]).startswith(STARTED)
        else:
            kept = any(x.get("session") == p["session"] and x["_i"] > p["_i"] for x in choices)
        if not (settled or kept):
            out.append(p)
    return out


def describe(p: dict, repos: list[Path], cfg: dict | None, event: dict | None = None) -> str:
    c = p["cond"]
    when = {"now": "без условия", "idle": "когда сабагентов не останется",
            "pr": f"после влития {c.get('repo', '')}#{c.get('n')}", "row": f"после №{c.get('n')}"}[c["kind"]]
    what = f"запуск №{p['row']}" if p["kind"] == "launch" else "сводка"
    state = "условие выполнено" if holds(p, repos, cfg, event) else "условие ещё не выполнено"
    said = f" — «{p['text'][:160]}»" if p.get("text") else ""
    return f"{what}, {when}: {state}{said} ({p['at'][:16].replace('T', ' ')}, id {p['id']})"


def session_start(event: dict) -> str:
    """The open promises of all sessions, at most ten lines, for SessionStart."""
    if not on():
        return ""
    repos = repos_of(event)
    cfg = _cfg(repos)
    found = open_promises(repos, cfg)
    if not found:
        return ""
    head = (f"buddie: открытые обещания ({len(found)}), выполни или сними строкой `buddie: не запускаю №N — "
            f"почему` / `buddie: сводки не будет — почему`:")
    rows = [f"- {'эта сессия' if p['session'] == event.get('session_id') else 'сессия ' + str(p['session'])}: "
            + describe(p, repos, cfg) for p in found[-(MAX_LINES - 1):]]
    return "\n".join([head] + rows)


def _cfg(repos: list[Path]) -> dict | None:
    from buddie import mandate
    return mandate.find_config(repos)


def on_stop(event: dict) -> str | None:
    """The reason to return the turn: this session's open promises whose condition holds, each once."""
    from buddie import summary
    if not on():
        return None
    session = event.get("session_id")
    repos = repos_of(event)
    cfg = _cfg(repos)
    mine = [p for p in open_promises(repos, cfg) if p["session"] == session]
    if not mine:
        return None
    due = [p for p in mine if holds(p, repos, cfg, event)]
    with summary.editing(session) as s:
        returned = s.setdefault("returned", [])
        due = [p for p in due if p["id"] not in returned]
        returned += [p["id"] for p in due]
    if not due:
        return None
    out = [f"buddie: обещание, условие которого выполнено ({len(due)}):"]
    out += [f"- {describe(p, repos, cfg, event)}" for p in due]
    out.append("Выполни сейчас: запуск — инструментом запуска с якорем `⚓ NEXT.md@<коммит>` (вердикт auto) или "
               "`⚓ choice:<id>=№N`; сводка — текстом, начиная со строки «Сводка», или через `summary`. Не будешь — "
               "скажи строкой `buddie: не запускаю №N — почему` или `buddie: сводки не будет — почему`.")
    return "\n".join(out)
