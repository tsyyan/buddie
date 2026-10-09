"""The summary with a choice card (audit/16, NEXT №61): when no subagent is left, what was done and what to launch.

The hook keeps a small state per session (local, like journal.py's pending lines, never the shared folder):

  SubagentStart   live[agent_id] = start time
  SubagentStop    the agent leaves `live`; its last message gets a receipt (hook.py runs verify) and is kept with its
                  «Следующий шаг:» lines as a result not yet summarized
  Stop            the orchestrator stops with no live subagent and with results nobody asked to summarize yet: the
                  turn is returned once per batch of results, asking to call `summary` and show the card (hook.py)
  PostToolUse     AskUserQuestion: what the person chose goes to the journal as a `choice` line (hashes of the
                  picked steps by default; the options and answers as text with [journal] text = true); with
                  metadata.source `buddie:<summary_id>` the results of that summary count as summarized

`build()` makes the summary (audit/16 §3) with no model: done (receipt outcome per result), lost (started, no stop,
transcript quiet longer than `stale`), next steps with their verdicts (mandate.py, the rule of lab's chain.py),
debt, open effects, at most three card options in a fixed order and a ready AskUserQuestion input. The model only
shows it. The anchor `choice:<id>=<step>` holds when the journal has that choice: <id> is the summary id (or the
AskUserQuestion tool_use id), <step> the option's key (`№N` or N), its label, or what the person typed in «Other».
A project's decision card (ask_decision) is read from the session's transcript and the journal (buddie/decisions.py):
<id> is the card's message id.

Env: BUDDIE_SUMMARY=0 turns the Stop demand off; BUDDIE_SUMMARY_MIN (default 1) results before it asks;
BUDDIE_SESSIONS sets where the state lives (default: next to BUDDIE_STATE, else ~/.cache/buddie/sessions).
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

NEXT_MARK = re.compile(r"Следующий шаг:\s*(.+)")
ROW = re.compile(r"№\s?(\d+)")
FIX = re.compile(r"^\s*(fix\b|исправ)", re.I)
WAITING = "ждёт условия"
STALE_MINUTES = 30
MAX_OPTIONS = 3
NOTHING = {"key": "none", "label": "Ничего не запускать",
           "description": "Шаги остаются в очереди и войдут в следующую сводку с пометкой «ждёт с …»"}
CHOICE = re.compile(r"^choice:(?P<id>[\w.-]+)=(?P<step>.+)$")
HOLDS, BROKEN, UNCHECKABLE = "HOLDS", "BROKEN", "UNCHECKABLE"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(at: str) -> datetime:
    return datetime.fromisoformat(at.replace("Z", "+00:00"))


# --- per-session state ------------------------------------------------------------------------------------------

def state_root() -> Path:
    if root := os.environ.get("BUDDIE_SESSIONS"):
        return Path(root)
    pending = os.environ.get("BUDDIE_STATE")
    if pending not in (None, "", "0"):
        return Path(pending).parent / "sessions"
    return Path.home() / ".cache" / "buddie" / "sessions"


def state_file(session: str | None) -> Path:
    return state_root() / (re.sub(r"[^\w.-]", "_", session or "nosession") + ".json")


def empty() -> dict:
    return {"live": {}, "results": [], "demanded": [], "summaries": {}, "shown": {}}


def load(session: str | None) -> dict:
    try:
        return {**empty(), **json.loads(state_file(session).read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError):
        return empty()


@contextlib.contextmanager
def editing(session: str | None):
    """Read, change and write the state under a lock: parallel subagents stop at the same time."""
    f = state_file(session)
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f.with_suffix(".lock"), "w") as lock:
        try:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        except ImportError:  # Windows: no lock, the race is rare and costs one result
            pass
        state = load(session)
        yield state
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(f)


def latest_session() -> str | None:
    """The session whose state changed last (the MCP server is not told which session it serves)."""
    files = sorted(state_root().glob("*.json"), key=lambda p: p.stat().st_mtime) if state_root().is_dir() else []
    return files[-1].stem if files else None


# --- hook events --------------------------------------------------------------------------------------------------

def on_start(event: dict) -> None:
    aid = event.get("agent_id")
    if not aid:
        return
    with editing(event.get("session_id")) as s:
        s["live"][aid] = {"at": now_iso(), "type": event.get("agent_type") or "",
                          "transcript": event.get("transcript_path")}


def next_lines(text: str) -> list[str]:
    return [m.group(1).strip() for m in NEXT_MARK.finditer(text) if m.group(1).strip()]


def head_line(text: str) -> str:
    for line in text.splitlines():
        line = re.sub(r"^[#>*\s-]+", "", line).strip()
        if line:
            return line[:160]
    return ""


def internal(event: dict) -> bool:
    """Claude Code's own helper (context compaction): a SubagentStop with an empty agent_type and no SubagentStart; its
    message is the session summary, not a result (NEXT №70, dogfood/summary-live)."""
    if event.get("agent_type"):
        return False
    return event.get("agent_id") not in load(event.get("session_id"))["live"]


def on_stop_subagent(event: dict, text: str, receipt: dict | None) -> dict:
    """Record a subagent's result; `receipt` is hook.py's verify of its last message (None for an empty one)."""
    aid = event.get("agent_id") or f"agent-{now_iso()}"
    pred = (receipt or {}).get("predicate") or {}
    result = {"agent_id": aid, "agent_type": event.get("agent_type") or "", "at": now_iso(), "head": head_line(text),
              "outcome": pred.get("outcome", "EMPTY"), "line": pred.get("line", ""),
              "anchors": [{k: a.get(k) for k in ("anchor", "status", "kind", "why") if a.get(k)}
                          for a in pred.get("anchors", [])],
              "next": next_lines(text), "summarized": False, "transcript": event.get("agent_transcript_path")}
    with editing(event.get("session_id")) as s:
        start = s["live"].pop(aid, None)
        if start:
            result["started"] = start["at"]
        s["results"] = [r for r in s["results"] if r["agent_id"] != aid] + [result]
    return result


def _running(tasks) -> int:
    """Background tasks Claude Code passes to Stop (2.1.288: `background_tasks`) that have not ended."""
    if not isinstance(tasks, list):
        return 0
    ended = {"completed", "failed", "killed", "stopped", "done", "cancelled", "error"}
    return sum(1 for t in tasks if not isinstance(t, dict) or str(t.get("status", "running")).lower() not in ended)


def on_stop(event: dict, now: datetime | None = None) -> str | None:
    """The orchestrator's Stop: the reason to return the turn, once per batch of new results; None to let it stop."""
    if os.environ.get("BUDDIE_SUMMARY", "1") == "0" or event.get("stop_hook_active"):
        return None
    session = event.get("session_id")
    if not state_file(session).is_file():
        return None
    minimum = int(os.environ.get("BUDDIE_SUMMARY_MIN", "1") or 1)
    with editing(session) as s:
        lost = {a["agent_id"] for a in lost_agents(s, now)}
        live = [a for a in s["live"] if a not in lost]
        if live or _running(event.get("background_tasks")):
            return None
        fresh = [r["agent_id"] for r in s["results"] if not r["summarized"] and r["agent_id"] not in s["demanded"]]
        if len(fresh) < max(1, minimum):
            return None
        s["demanded"] += fresh
    run = Path(__file__).resolve().parents[1] / "run.py"
    return (f"buddie: сабагентов не осталось, новых результатов {len(fresh)}. Собери сводку кодом: инструмент MCP "
            f"buddie `summary` (session {session}) или `python3 {run} summary --session {session} --text`. Покажи "
            f"её текст как есть и, если в ней есть `card`, задай вопрос AskUserQuestion с этим `card` без изменений "
            f"(подписи можно сократить, варианты и metadata не менять). Выбранное запускай с якорем "
            f"`⚓ choice:<summary_id>=<шаг>`. Карточка не нужна — скажи это одной строкой, начиная с `buddie:`.")


def transcript_source(transcript: str | None, tool_use_id: str | None) -> str:
    """metadata.source of the AskUserQuestion call, read from the transcript: Claude Code drops `metadata` from the
    hook's tool_input (NEXT №70, dogfood/summary-live), so the card's summary id is found by the tool_use id."""
    if not transcript or not tool_use_id or not Path(transcript).is_file():
        return ""
    for raw in Path(transcript).read_text(encoding="utf-8", errors="replace").splitlines():
        if tool_use_id not in raw:
            continue
        try:
            content = (json.loads(raw).get("message") or {}).get("content")
        except json.JSONDecodeError:
            continue
        for c in content if isinstance(content, list) else []:
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("id") == tool_use_id:
                source = ((c.get("input") or {}).get("metadata") or {}).get("source")
                return source if isinstance(source, str) else ""
    return ""


def on_choice(event: dict) -> dict | None:
    """PostToolUse on AskUserQuestion: write the options and the person's answer to the journal, codewise."""
    from buddie.hook import log
    tin, tout = event.get("tool_input") or {}, event.get("tool_response") or {}
    if isinstance(tout, str):
        try:
            tout = json.loads(tout)
        except json.JSONDecodeError:
            tout = {"response": tout}
    questions = tin.get("questions") or tout.get("questions") or []
    answers = tout.get("answers") or tin.get("answers") or {}
    source = ((tin.get("metadata") or {}).get("source") or "") or transcript_source(
        event.get("transcript_path"), event.get("tool_use_id"))
    sid = source[len("buddie:"):] if source.startswith("buddie:") else None
    session = event.get("session_id")
    known = load(session)["summaries"].get(sid, {}) if sid else {}
    by_label = {o["label"]: o["key"] for o in known.get("options", [])}
    asked, chosen, other = [], [], []
    for q in questions:
        labels = [o.get("label", "") for o in q.get("options") or []]
        asked.append({"question": q.get("question", ""), "options": labels})
        answer = answers.get(q.get("question", ""))
        rest = ", ".join(map(str, answer)) if isinstance(answer, list) else str(answer or "")
        picked = set()
        for label in sorted(filter(None, labels), key=len, reverse=True):  # multi-select answers are «a, b»
            if label in rest:
                picked.add(label)
                rest = rest.replace(label, "", 1)
        chosen += [by_label.get(label, label) for label in labels if label in picked]
        if rest := re.sub(r"^[\s,]+|[\s,]+$", "", re.sub(r"(,\s*){2,}", ", ", rest)):
            other.append(rest)
    if tout.get("response"):
        other.append(str(tout["response"]))
    choice = {"id": sid or event.get("tool_use_id") or now_iso(), "summary_id": sid, "asked": asked,
              "options": known.get("options", []), "chosen": chosen, "other": other, "answers": answers}
    from buddie import config
    kept = choice if config.journal_text(config.of_event(event)[1]) else receipt_of_choice(choice, known)
    log({"at": now_iso(), "session": session, "event": "PostToolUse", "tool": "AskUserQuestion", "choice": kept})
    if sid:
        with editing(session) as s:
            done = set(s["summaries"].get(sid, {}).get("done", []))
            for r in s["results"]:
                if r["agent_id"] in done:
                    r["summarized"] = True
            for o in s["summaries"].get(sid, {}).get("options", []):
                s["shown"].setdefault(o["key"], now_iso())
            s["summaries"].setdefault(sid, {})["chosen"] = chosen
    return choice


def _step_hash(step: str) -> str:
    return hashlib.sha256(_norm(step).encode("utf-8")).hexdigest()[:16]


def receipt_of_choice(choice: dict, known: dict) -> dict:
    """A choice line without words of the conversation ([journal] text = false, NEXT №104): the hashes of the
    picked steps (key and label), the queue numbers of a typed answer, how many questions and options there were."""
    picked = set(choice["chosen"])
    picked |= {o["label"] for o in known.get("options", []) if o.get("key") in picked}
    return {"id": choice["id"], "summary_id": choice["summary_id"], "picked": sorted(map(_step_hash, picked)),
            "other_rows": sorted({n for t in choice["other"] for n in re.findall(r"\d+", t)}),
            "questions": len(choice["asked"]), "options": sum(len(q["options"]) for q in choice["asked"])}


# --- building the summary -----------------------------------------------------------------------------------------

def _transcript_age(agent: dict, aid: str, now: datetime) -> timedelta | None:
    path = agent.get("transcript")
    if not path:
        return None
    side = Path(path).with_suffix("")
    files = list(side.glob(f"**/*{aid}*.jsonl")) if side.is_dir() else []
    if not files:
        return None
    return now - datetime.fromtimestamp(max(f.stat().st_mtime for f in files), timezone.utc)


def lost_agents(state: dict, now: datetime | None = None, stale: int = STALE_MINUTES) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    out = []
    for aid, a in state["live"].items():
        age = now - _parse(a["at"])
        quiet = _transcript_age(a, aid, now)
        quiet = age if quiet is None else quiet
        if age > timedelta(minutes=stale) and quiet > timedelta(minutes=stale):
            out.append({"agent_id": aid, "agent_type": a.get("type", ""), "started": a["at"],
                        "quiet_minutes": int(quiet.total_seconds() // 60)})
    return out


def _key(n: int | None, text: str) -> str:
    return f"№{n}" if n is not None else "s:" + hashlib.sha256(text.encode()).hexdigest()[:8]


def _label(n: int | None, text: str) -> str:
    words = re.sub(r"[`*_,]", "", ROW.sub("", text)).split()
    short = " ".join(words[:5])
    label = (f"№{n} " if n is not None else "") + short
    return label if len(label) <= 40 else label[:39].rstrip() + "…"


def steps(state: dict, cfg: dict | None, queue: bool = True) -> list[dict]:
    from buddie import mandate as man
    m = man.Mandate(cfg) if cfg else None
    out, seen = [], set()

    def add(n, text, origin, parent_outcome):
        key = _key(n, text)
        if key in seen:
            return
        seen.add(key)
        step = {"key": key, "n": n, "text": text[:300], "from": origin, "basis_ok": None if parent_outcome is None
                else parent_outcome != "FAIL"}
        if m and n is not None and n in m.table:
            row = m.table[n]
            v = m.verdict_now(n)
            b = man.parse(cfg, row["basis"])
            # a status «ждёт условия» whose time conditions all came due no longer waits (lab NEXT №83, as chain.py debt)
            mark = cfg.get("waiting") or WAITING
            waiting = mark in row["status"] and man.waits(dict(cfg, waiting=mark), row, m.appeared(n), now_iso()) is not None
            step.update(verdict=v["verdict"], reasons=v["reasons"], fix=bool(b and b["kind"] == "fix"),
                        waiting=waiting)
        else:
            why = "no queue row (№N) for this step" if m else "no queue (buddie.toml [mandate]): the person decides"
            step.update(verdict="ask", reasons=[why], fix=bool(FIX.match(text)), waiting=False)
        if step["basis_ok"] is False:
            step["verdict"] = "ask"
            step["reasons"] = step["reasons"] + ["its parent's receipt is FAIL: basis not confirmed"]
        step["shown"] = state["shown"].get(key)
        out.append(step)

    taken = {k for x in state["summaries"].values() for k in x.get("chosen", [])}
    seen |= taken  # a chosen step was launched; one not chosen stays and comes back marked with when it was shown
    for r in state["results"]:
        for line in r["next"]:
            n = ROW.search(line)
            add(int(n.group(1)) if n else None, line, r["agent_id"], r["outcome"])
    if m and queue:
        for n in sorted(m.table):
            if m.table[n]["status"].startswith(cfg["proposed"]):
                add(n, m.table[n]["text"], "queue", None)
    return out


def options(next_steps: list[dict]) -> list[dict]:
    """At most three asks for the card, fixes first, then the oldest: shown longest ago, then the lowest row."""
    asks = [s for s in next_steps if s["verdict"] == "ask" and not s["waiting"]]
    asks.sort(key=lambda s: (not s["fix"], s["shown"] or "9999", s["n"] if s["n"] is not None else 10 ** 9))
    out = [{"key": s["key"], "label": _label(s["n"], s["text"]),
            "description": (s["text"][:140] + ("…" if len(s["text"]) > 140 else ""))
                           + (" (основание не подтверждено)" if s["basis_ok"] is False else "")}
           for s in asks[:MAX_OPTIONS]]
    return out + [NOTHING] if out else []


def build(state: dict, cfg: dict | None = None, *, queue: bool = True, stale: int = STALE_MINUTES,
          now: datetime | None = None) -> dict:
    done = [r for r in state["results"] if not r["summarized"]]
    lost = lost_agents(state, now, stale)
    nxt = steps(state, cfg, queue)
    effects = [dict(a, **{"from": r["agent_id"]}) for r in done for a in r["anchors"]
               if a.get("status") == BROKEN or re.match(r"^pr:.*=(open|draft)\b", a.get("anchor", ""))
               or re.match(r"^ci:.*=(failure|pending)$", a.get("anchor", ""))]
    opts = options(nxt)
    sid = hashlib.sha256(json.dumps([[r["agent_id"] for r in done], [s["key"] for s in nxt]]).encode()).hexdigest()[:12]
    debt = {"launch": [s["key"] for s in nxt if s["verdict"] == "auto" and not s["waiting"]],
            "summary": [s["key"] for s in nxt if s["verdict"] == "ask" and not s["waiting"] and not s["shown"]],
            "waiting": [s["key"] for s in nxt if s["waiting"]]}
    out = {"summary_id": sid, "at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "live": [a for a in state["live"] if a not in {x["agent_id"] for x in lost}],
           "done": [{"agent_id": r["agent_id"], "agent_type": r["agent_type"], "head": r["head"],
                     "outcome": r["outcome"], "line": r["line"],
                     "anchors": [a["anchor"] for a in r["anchors"] if a.get("anchor")]} for r in done],
           "lost": lost, "next": nxt, "debt": debt, "effects": effects, "options": opts,
           "card": card(sid, opts) if opts else None}
    out["text"] = render(out)
    return out


def card(sid: str, opts: list[dict]) -> dict:
    """The AskUserQuestion input as is: one question, 2–4 options, several may be picked; «Other» is added by
    Claude Code itself (a row number from the queue, or a task of the person's own)."""
    return {"questions": [{"question": "Что запустить дальше?", "header": "Шаги", "multiSelect": True,
                           "options": [{"label": o["label"], "description": o["description"]} for o in opts]}],
            "metadata": {"source": f"buddie:{sid}"}}


def render(s: dict) -> str:
    out = [f"Сводка buddie {s['summary_id']}: результатов {len(s['done'])}, живых сабагентов {len(s['live'])}."]
    if s["done"]:
        out.append("Сделано:")
        out += [f"- {d['agent_type'] or d['agent_id']}: {d['head']} — {d['outcome']}"
                + (f" (`⚓ {d['anchors'][0]}`)" if d["anchors"] else "") for d in s["done"]]
    if s["lost"]:
        out.append("Потеряно:")
        out += [f"- {a['agent_type'] or 'сабагент'} {a['agent_id']}: нет ответа {a['quiet_minutes']} мин"
                for a in s["lost"]]
    by = {x["key"]: x for x in s["next"]}
    if s["debt"]["launch"]:
        out.append("Запускаю сам (вердикт auto):")
        out += [f"- {k}: {by[k]['text'][:120]}" for k in s["debt"]["launch"]]
    if s["effects"]:
        out.append("Открытые эффекты:")
        out += [f"- `{e['anchor']}` {e.get('status', '')}".rstrip() for e in s["effects"]]
    rest = [x for x in s["next"] if x["verdict"] == "ask" or x["waiting"]]
    if rest:
        out.append("Ждут решения:")
        out += [f"- {x['key']}: {x['text'][:120]}" + (f" (показан с {x['shown'][:16]})" if x["shown"] else "")
                + (" (ждёт условия)" if x["waiting"] else "") for x in rest]
    if s["card"]:
        out.append(f"Карточка: {len(s['options']) - 1} шаг(а) и «Ничего не запускать»; запуск выбранного с якорем "
                   f"`⚓ choice:{s['summary_id']}=<шаг>`.")
    return "\n".join(out)


def summarize(session: str | None, repos: list[Path], *, queue: bool = True, stale: int = STALE_MINUTES,
              record: bool = True) -> dict:
    """The summary of a session (None: the latest one; no state: the queue alone), remembered for its card."""
    from buddie import mandate as man
    session = session or latest_session()
    state = load(session) if session else empty()
    out = build(state, man.find_config(repos), queue=queue, stale=stale)
    out["session"] = session
    if record and session and out["card"]:
        with editing(session) as s:
            s["summaries"][out["summary_id"]] = {"at": out["at"], "done": [d["agent_id"] for d in out["done"]],
                                                 "options": [{"key": o["key"], "label": o["label"]}
                                                             for o in out["options"]]}
    return out


# --- the choice: anchor -------------------------------------------------------------------------------------------

def choices(paths=None) -> list[dict]:
    """The `choice` lines of the journal (files or dirs of *.jsonl; default the hook's own)."""
    from buddie.hook import journal_paths
    files = []
    for p in map(Path, paths if paths is not None else journal_paths()):
        files += sorted(p.glob("*.jsonl")) if p.is_dir() else [p] if p.is_file() else []
    out = []
    for f in files:
        for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(e, dict) and isinstance(e.get("choice"), dict):
                out.append(e)
    return out


def _norm(step: str) -> str:
    return re.sub(r"^№\s?", "", step.strip()).casefold()


def check_choice(anchor: str, ctx: dict | None = None) -> dict:
    out = {"anchor": anchor, "kind": "choice"}
    m = CHOICE.match(anchor)
    if not m:
        return dict(out, status=BROKEN, why="expected choice:<summary_id>=<step>")
    from buddie import decisions
    ctx = ctx or {}
    found = [e for e in choices(ctx.get("journal")) + decisions.choices(ctx.get("transcript"), ctx.get("journal"))
             if e["choice"].get("id") == m["id"]]
    if not found:
        return dict(out, status=UNCHECKABLE, why=f"no choice {m['id']} in this machine's journal or this session's "
                                                "transcript")
    want = _norm(m["step"])
    for e in found:
        c = e["choice"]
        if "picked" in c:  # a receipts-only line: hashes and numbers, no words
            if _step_hash(want) in c["picked"] or want in c.get("other_rows", []):
                return dict(out, status=HOLDS, at=e.get("at"))
            continue
        keys = {_norm(o["label"]): _norm(o["key"]) for o in c.get("options", [])}
        picked = {_norm(k) for k in c.get("chosen", [])}
        if keys.get(want, want) in picked or any(re.search(rf"(?<!\w){re.escape(want)}(?!\w)", t.casefold())
                                                 for t in c.get("other", []) if want):
            return dict(out, status=HOLDS, at=e.get("at"))
    last = found[-1]["choice"]
    chosen = ", ".join(last.get("chosen", []) + last.get("other", [])) or (
        "another step (the journal keeps receipts only)" if "picked" in last else "nothing")
    if all(e["choice"].get("card") is False for e in found):  # a decision card whose options nobody recorded
        return dict(out, status=UNCHECKABLE, why=f"choice {m['id']} picked {chosen}; the card's options are in no "
                                                 "transcript or journal, so its steps are unknown")
    return dict(out, status=BROKEN, why=f"choice {m['id']} picked {chosen}, not {m['step']}")
