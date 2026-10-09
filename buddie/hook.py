"""Gate before an answer leaves the session (Claude Code hooks; Grok Build reads the same plugin format).

PreToolUse on a tool that sends text to people or to another session (reply, post_message, send_message):
the text is in tool_input. Stop: the final answer is the last assistant message of the transcript.

FAIL (a quote not in its source, a broken anchor) blocks with exit 2: the reason goes to the model, which fixes the
text and sends again. The model may also send it unchanged with a line that starts with `buddie:` saying what was
not fixed and why: then the misses are disclosed to the reader and the gate lets it through. A broken effect anchor
(pr:, ci:, run:) is the exception (NEXT №62): it states work that did not happen, so only a corrected or removed
anchor lets the text through. GAPS and PASS never block. A Stop hook already re-entered (stop_hook_active) never blocks, so the gate cannot loop.

A final answer (by default the last assistant message at Stop; a project that hands in results through a tool names
their mark: BUDDIE_FINAL, else `final_mark` of [mandate] in the repo's buddie.toml, as lab's `Следующий шаг:`; with a
mark, text carrying it is final at any event; an empty BUDDIE_FINAL turns the rule off) must also carry its numbers: at least one anchor, and no line stating a count or
a share without one. Otherwise the gate checks nothing (NEXT №21: thread answers had no anchors, every receipt was
EMPTY), so it blocks the same way and the same `buddie:` line lets it through.
Nor may it claim work in prose (NEXT №63): a line saying merged, CI green, tests passed or ran with no pr:/ci:/run:
anchor on it is returned with the anchors that hold now (buddie/suggest.py), and as with a broken effect anchor a
`buddie:` line does not let it through; the anchor or the claim's removal does.
A Stop whose turn already sent a final answer through a text tool the gate let out is not checked for prose: its
text reaches no one (NEXT №128).

Every run appends one JSON line (time, tool, outcome, exit code) to $BUDDIE_LOG, default ~/.cache/buddie/hook.jsonl,
so a passing gate leaves a trace too; BUDDIE_LOG=0 turns it off. A cloud container's home is gone when the session
ends, so where a project shared folder exists (/mnt/project-files) the same line also goes to
<BUDDIE_SHARED_LOG>/<session_id>.jsonl, default /mnt/project-files/buddie/hook (0 turns it off): one file per
session, so sessions never write the same file. Each line counts the work claims of the text (NEXT №43): effect
anchors, how many BROKEN, and lines that claim work in prose with no anchor; dogfood/effects/measure.py sums them.
A journal line is a receipt: counts, verdicts, the exit code and the sha256 of the text, never the text. Promise and
choice lines keep words of the conversation only with [journal] text = true (buddie/config.py, NEXT №104).

Effect anchors (pr:, ci:, run:, buddie/effects.py) are judged against GitHub and this session's transcript_path.

Web quotes are judged against the snapshots the session itself took (NEXT №37, buddie/stores.py): $BUDDIE_STORES,
$VERBATIM_STORE, stores named in its tool calls, ./.verbatim of the cwd and the repos, `sources/` the repos changed.
Only a URL in none of them is fetched now. The journal line counts quote verdicts and the stores used.
The closed loop (0.5, buddie/journal.py, NEXT №55): each returned line logs `reasons` (what it was returned for);
the attempt after a return logs `gate`, how it got through (proof, removal, disclosure...). A return also offers
ready anchors that already hold (buddie/suggest.py). SessionStart prints the lessons of past sessions' journal
into the new session's context (at most ten lines; BUDDIE_LESSONS=0 turns it off).
SessionStart and a Stop with no text to check each
write a heartbeat line (`beat`, NEXT №118), so the journal shows the hooks fire; the gate's counts skip it.

The context gate (buddie/context.py, NEXT №58): past 200k tokens of context (the last API call in transcript_path)
a reply that is not a final answer is returned with a reminder to hand in the result; each line logs `context`.
Past the limit a subagent launch (Agent, Task) is returned as well, and so is a send_message of a thread woken
after it handed in its result (NEXT №106).

The summary (0.6, buddie/summary.py, NEXT №61): SubagentStart/SubagentStop keep the live subagents and their results
(a receipt of each last message, its «Следующий шаг:» lines); a Stop with none live and results not yet summarized
returns the turn once, asking for `summary` and its choice card; PostToolUse on AskUserQuestion writes the options
and the person's answer to the journal (`choice`), which the anchor choice:<id>=<step> is checked against. A project's
decision card (ask_decision, NEXT №109) is answered in a later turn: each run reads the transcript for the cards and
the picks and writes the new ones to the journal (`card`, `choice`), and PostToolUse on ask_decision writes the card
at once (buddie/decisions.py).

Launch gate and promises (0.7, buddie/promises.py, NEXT №69): PreToolUse on a launch tool of buddie.toml [launch]
lets a launch of queue row N through only with `⚓ NEXT.md@<commit>` whose queue gives N the verdict auto, or with
`⚓ choice:<id>=№N`; a text the gate let out is read for promises («запущу №N после влития lab#M», «сводка будет»),
journaled as `promise` lines; SessionStart prints the open ones of all sessions, Stop returns the turn once per
promise of this session whose condition holds.

Levels and the intro mode (0.8, buddie/config.py, NEXT №93): buddie.toml [gates] sets each class of claims (anchors,
quotes, final, prose, numbers, work, summary, promises) to block, warn or off; a warning leaves with the text as a
systemMessage. [intro] finals = N (`buddie init`) makes every return a warning until N final answers have passed
without a reported false return. Defaults are in buddie/config.py: work anchors, quotes and the final answer block,
prose and numbers warn, summary and promises are off.

Env: BUDDIE_GATES=class=level,... overrides [gates]; BUDDIE_FETCH=0 checks only what is already in the store; BUDDIE_REPOS=dir:dir sets the repos for anchors;
BUDDIE_GITHUB=0 leaves pr:/ci: anchors UNCHECKABLE instead of asking GitHub; BUDDIE_STORES=dir:dir adds snapshot stores.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

TEXT_KEYS = ("text", "message", "body", "content")
DISCLOSED = re.compile(r"^\s*buddie\s*:", re.I | re.M)
EFFECT_KINDS = ("pr", "ci", "run")
SHARED_ROOT = Path("/mnt/project-files")
HANDBACK = "SubagentHandback"


def final_mark(event: dict) -> str | None:
    """The regex of a final answer: BUDDIE_FINAL, else final_mark of the first buddie.toml [mandate] around the
    session, else None (the plugin's default, 0.7.4: the last message at Stop is the final answer)."""
    env = os.environ.get("BUDDIE_FINAL")
    if env is not None:
        return env
    from buddie.mandate import CONFIG
    from buddie.promises import repos_of
    for repo in repos_of(event):
        path = repo / CONFIG
        if path.is_file():
            import tomllib
            try:
                mark = tomllib.loads(path.read_text(encoding="utf-8")).get("mandate", {}).get("final_mark")
            except (OSError, tomllib.TOMLDecodeError):
                continue
            if mark is not None:
                return mark
    return None


def final_answer(text: str, event: dict | None = None) -> bool:
    event = event or {}
    mark = final_mark(event)
    if mark is None:
        return event.get("hook_event_name") == "Stop"
    return bool(mark) and re.search(mark, text) is not None


def unbacked(pred: dict) -> list[str]:
    """Why a final answer does not carry its numbers: no anchor at all, or count lines without one."""
    out = []
    if not pred["anchors"]:
        out.append("final answer has no anchor: anchor its result (⚓ path@commit, ⚓ path#sha256, ⚓ fact=value, "
                   "⚓ pr:OWNER/REPO#N=merged, ⚓ ci:OWNER/REPO@SHA=success or ⚓ run:CMD => OUTPUT)")
    out += [f"number without anchor, {u}" for u in pred["unanchored"]]
    return out


def prose_claims(text: str, pred: dict) -> list[str]:
    """Lines of a final answer that claim work done (merged, CI green, tests passed, ran) with no pr:/ci:/run:
    anchor on the line (NEXT №63)."""
    lines = text.splitlines()
    return [f"work claimed in prose, line {n}: “{lines[n - 1].strip()[:120]}”: anchor it on the line "
            "(⚓ pr:OWNER/REPO#N=merged@SHA, ⚓ ci:OWNER/REPO@SHA=success, ⚓ run:CMD => OUTPUT) or drop the claim"
            for n in pred.get("prose_lines", ())]


def log_targets(session: str | None) -> list[Path]:
    out = []
    target = os.environ.get("BUDDIE_LOG", str(Path.home() / ".cache" / "buddie" / "hook.jsonl"))
    if target not in ("", "0"):
        out.append(Path(target))
    shared = os.environ.get("BUDDIE_SHARED_LOG")
    if shared is None and SHARED_ROOT.is_dir():
        shared = str(SHARED_ROOT / "buddie" / "hook")
    if shared not in (None, "", "0"):
        name = re.sub(r"[^\w.-]", "_", session or "nosession")
        out.append(Path(shared) / f"{name}.jsonl")
    return out


def log(entry: dict) -> None:
    for target in log_targets(entry.get("session")):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass


def tool_text(tool_input: dict) -> str:
    return "\n\n".join(v for k in TEXT_KEYS if isinstance(v := tool_input.get(k), str))


def last_answer(transcript: str) -> str:
    text = ""
    for raw in Path(transcript).read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content")
        content = content if isinstance(content, list) else []
        # a cloud subagent ends with the SubagentHandback tool, its report in input.message, and its SubagentStop
        # has no last_assistant_message (NEXT №70, dogfood/summary-live)
        parts = [c.get("text", "") for c in content if c.get("type") == "text"] + [
            c["input"]["message"] for c in content if c.get("type") == "tool_use" and c.get("name") == HANDBACK
            and isinstance((c.get("input") or {}).get("message"), str)]
        if any(p.strip() for p in parts):
            text = "\n".join(parts)
    return text


SEND = re.compile(r"(?:^|__)(?:reply|post_message|send_message)$|^SendMessage$")


def handed_in(event: dict) -> bool:
    """Whether this turn already sent a final answer through a text tool (reply, send_message…) that the gate let
    out: its tool_use has a tool_result that is not an error. Then the Stop text after it reaches no one, and it is
    not checked for prose (NEXT №128: 3 of 8 prose returns of №82 were on such Stop text)."""
    from buddie.decisions import _turn_text
    path = event.get("transcript_path")
    if not path or not Path(path).is_file():
        return False
    sent, passed = {}, False
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        if _turn_text(entry) is not None:  # a new turn: what the last one sent does not count
            sent, passed = {}, False
            continue
        content = (entry.get("message") or {}).get("content")
        for c in content if isinstance(content, list) else []:
            if not isinstance(c, dict):
                continue
            if entry.get("type") == "assistant" and c.get("type") == "tool_use" and SEND.search(str(c.get("name"))):
                if final_answer(tool_text(c.get("input") or {}), dict(event, hook_event_name="PreToolUse")):
                    sent[c.get("id")] = True
            elif c.get("type") == "tool_result" and sent.pop(c.get("tool_use_id"), False) and not c.get("is_error"):
                passed = True
    return passed


def journal_paths() -> list[Path]:
    """Where past sessions' journal lines are: the local log, and the whole shared folder when there is one."""
    out = []
    for target in log_targets(None):
        out.append(target.parent if target.name == "nosession.jsonl" else target)
    return out


def beat(event: dict, **extra) -> None:
    """A heartbeat line (NEXT №118): SessionStart and a Stop with no text to check write one, so the journal shows
    that these hooks fire. `beat` keeps it out of the gate's counts (journal.entries skips it)."""
    from buddie.summary import now_iso
    log({"at": now_iso(), "session": event.get("session_id"), "event": event.get("hook_event_name"), "beat": True,
         **extra})


def session_start(event: dict, out=None) -> int:
    from buddie import promises
    from buddie.journal import entries, lessons
    beat(event, source=event.get("source"), exit=0)
    if os.environ.get("BUDDIE_LESSONS", "1") != "0":
        if text := lessons(entries(journal_paths()), skip_session=event.get("session_id")):
            print(text, file=out or sys.stdout)
    if text := promises.session_start(event):
        print(text, file=out or sys.stdout)
    return 0


def receipt_for(text: str, event: dict, numbers: str = "gap") -> tuple[dict, list]:
    """The receipt of `text`, and the snapshot stores its quotes were judged against (numbers: verify's mode,
    BUDDIE_NUMBERS overrides it)."""
    from buddie.anchors import find_repos
    from buddie.effects import github_get
    from buddie.stores import UnionStore, session_stores
    from buddie.verify import verify
    cwd = Path(event.get("cwd") or os.getcwd())
    env_repos = [Path(p) for p in os.environ.get("BUDDIE_REPOS", "").split(os.pathsep) if p]
    github = github_get if os.environ.get("BUDDIE_GITHUB", "1") != "0" else None
    repos = env_repos or find_repos(cwd)
    stores = session_stores(cwd, repos, event.get("transcript_path"))
    return verify(text, name=event.get("tool_name") or event.get("hook_event_name") or "answer", repos=repos,
                  store=UnionStore(None, stores), fetch=os.environ.get("BUDDIE_FETCH", "1") != "0", github=github,
                  transcript=event.get("transcript_path"), numbers=os.environ.get("BUDDIE_NUMBERS", numbers)), stores


def outgoing(event: dict) -> str:
    """The text that leaves the session with this event: the final answer at Stop, the tool's text at PreToolUse."""
    if event.get("hook_event_name") == "Stop":
        path = event.get("transcript_path")
        return last_answer(path) if path and Path(path).is_file() else ""
    return tool_text(event.get("tool_input") or {})


def run(event: dict, err=None, out=None) -> int:
    from buddie import config, context, decisions, promises, summary
    err = err or sys.stderr
    name = event.get("hook_event_name")
    if name == "SessionStart":
        return session_start(event)
    if name == "SubagentStart":
        summary.on_start(event)
        return 0
    if name == "SubagentStop":
        if summary.internal(event):
            return 0
        text = event.get("last_assistant_message") or (
            last_answer(event["agent_transcript_path"]) if Path(event.get("agent_transcript_path") or "").is_file()
            else "")
        summary.on_stop_subagent(event, text, receipt_for(text, event)[0] if text.strip() else None)
        return 0
    if name == "PostToolUse":
        if event.get("tool_name") == "AskUserQuestion":
            summary.on_choice(event)
        elif decisions.TOOL.search(event.get("tool_name") or ""):
            decisions.on_post(event)
        return 0
    if event.get("transcript_path"):
        try:
            decisions.sync(event)
        except Exception as error:  # the journal is a convenience; a failure here must not skip the gate below
            print(f"buddie: decision cards not journaled: {type(error).__name__}: {error}", file=err)
    if context.spawning(event) and spawn_held(event, err, out):
        return 2
    if promises.is_launch(event):
        return promises.gate(event, err)

    def passed() -> list[str]:
        promises.record(event, outgoing(event))
        if name != "Stop":
            return []
        lv, why = config.levels(config.of_event(event)[1]), []
        for cls, demand in (("summary", summary.on_stop), ("promises", promises.on_stop)):
            if lv[cls] != "off" and (w := demand(event)):
                why.append(w) if lv[cls] == "block" else warn([w], out)
        return why

    code, why = gate(event, err, passed, out)
    if why:
        print("\n\n".join(why), file=err)
        return 2
    return code


def spawn_held(event: dict, err, out=None) -> bool:
    """The context gate on a subagent launch (NEXT №106): past the limit the launch is returned, unless its prompt
    carries a `buddie:` line (the user asked for it); in the intro mode it only warns. The launch has no text to
    verify, so this runs before the launch gate and the journal line is its own."""
    from buddie import config, context
    from buddie.promises import strings
    from buddie.summary import now_iso
    tokens = context.last_context(event.get("transcript_path"))
    heavy = context.over(event, False, tokens)
    if not heavy:
        return False
    path, cfg = config.of_event(event)
    disclosed = bool(DISCLOSED.search("\n".join(strings(event.get("tool_input") or {}))))
    tour = config.intro(path, cfg)
    held = not disclosed and not tour
    entry = {"at": now_iso(), "session": event.get("session_id"), "event": "PreToolUse", "tool": event.get("tool_name"),
             "context": tokens, "exit": 2 if held else 0}
    if held:
        entry["reasons"] = {"context": 1}
        print(heavy, file=err)
    elif tour and not disclosed:
        entry["intro"] = tour
        warn([f"buddie (intro, final {tour['seen']} of {tour['finals']}): would have returned this launch for",
              f"- {heavy}"], out)
    log(entry)
    return held


def demanded(event: dict, why: list[str]) -> None:
    """A Stop the gate let through but run() returns for a summary or a promise: its journal line says exit 2 too
    (NEXT №72; the live run of №70 logged such a Stop with exit 0)."""
    from buddie.summary import now_iso
    log({"at": now_iso(), "session": event.get("session_id"), "event": event.get("hook_event_name"),
         "tool": event.get("tool_name"), "exit": 2, "demand": [w.splitlines()[0] for w in why]})


def warn(lines: list[str], out=None) -> None:
    """What the gate let out but would say (a class at "warn", or the intro mode): a systemMessage for the person."""
    print(json.dumps({"systemMessage": "\n".join(lines)}, ensure_ascii=False), file=out or sys.stdout)


def gate(event: dict, err, passed=lambda: [], out=None) -> tuple[int, list[str]]:
    """The gate's exit code, and when it lets the text out, what `passed` returns (the reasons to return a Stop
    anyway). The journal line is written after `passed`, so it carries the exit code the hook really returns.
    Each blocking item goes by its class's level in buddie.toml [gates] (buddie/config.py): block returns the
    text, warn lets it out with a systemMessage, off drops it; in the intro mode nothing is returned."""
    from buddie import config, context, journal
    from buddie.effects import github_get
    from buddie.suggest import ready_anchors
    name = event.get("hook_event_name")
    if name == "Stop":
        if event.get("stop_hook_active") or not event.get("transcript_path"):
            text = ""
        else:
            text = last_answer(event["transcript_path"])
    else:
        text = tool_text(event.get("tool_input") or {})
    if not text.strip():
        why = passed()
        if why:
            demanded(event, why)
        elif name == "Stop":
            beat(event, empty=True, active=bool(event.get("stop_hook_active")), exit=0)
        return 0, why
    github = github_get if os.environ.get("BUDDIE_GITHUB", "1") != "0" else None
    path, cfg = config.of_event(event)
    lv = config.levels(cfg)
    receipt, stores = receipt_for(text, event, config.numbers_mode(lv["numbers"]))
    pred = receipt["predicate"]
    final = final_answer(text, event)
    tokens = context.last_context(event.get("transcript_path"))
    heavy = context.over(event, final, tokens, lambda t: final_answer(t, event))
    extra = [{"kind": "context", "line": None, "text": ""}] if heavy else []
    prose = prose_claims(text, pred) if final and not (name == "Stop" and handed_in(event)) else []
    every = pred["blocking"] + (unbacked(pred) if final else []) + prose + ([heavy] if heavy else [])
    level = {item: lv.get(config.classify(item) or "", "block") for item in every}
    blocking = [i for i in every if level[i] == "block"]
    warned = [i for i in every if level[i] == "warn"]
    # a broken effect anchor is a false claim about work, not a miss to disclose: only fixing or removing it lets the
    # text through (NEXT №62; №40 13:55 sent `pr:…=open` for a merged PR with a `buddie:` line and passed). Work
    # claimed in prose in a final answer is the same (NEXT №63, audit/15 «в main влиты №40, №58…» with no pr:)
    hard = any(level[i] == "block" for i in prose) or lv["anchors"] == "block" and any(
        a.get("kind") in EFFECT_KINDS and a["status"] == "BROKEN" for a in pred["anchors"])
    tour = config.intro(path, cfg)
    if tour:  # the intro mode: what would be returned only warns (audit/20 §3.3)
        warned, blocking, hard = warned + blocking, [], False
        if final:
            tour["seen"] = config.count_final(path)
    code = 2 if hard or (blocking and not DISCLOSED.search(text)) else 0
    items = journal.flagged(pred, text, final) + extra if code else []
    session, tool = event.get("session_id"), event.get("tool_name") or name
    before = journal.take_pending(session, tool)
    entry = {"at": pred["checked_at"], "session": session, "event": name, "tool": event.get("tool_name"),
             "final": final, "context": tokens, "work": pred["summary"]["work"],
             "quotes": pred["summary"]["quotes"], "stores": len(stores),
             "outcome": pred["outcome"], "sha256": receipt["subject"][0]["digest"]["sha256"], "exit": code,
             "effects": {f"{a['kind']}:{a['status']}": sum(1 for b in pred["anchors"] if b.get("kind") == a["kind"]
                                                           and b["status"] == a["status"])
                         for a in pred["anchors"] if a.get("kind")}}
    if code:
        entry["reasons"] = journal.reasons(items)
    if warned:
        entry["warned"] = len(warned)
    if tour:
        entry["intro"] = tour
    if before:
        entry["gate"] = journal.passage(before, text, journal.flagged(pred, text, final) + extra, code)
    why = [] if code else passed()
    if why and tour:
        warned, why = warned + [w.splitlines()[0] for w in why], []
    if why:
        entry["exit"], entry["demand"] = 2, [w.splitlines()[0] for w in why]
    log(entry)
    journal.keep_pending(session, tool, items)
    if warned and not code:
        head = (f"buddie (intro, final {tour['seen']} of {tour['finals']}): would have returned this answer for"
                if tour else "buddie warns:")
        tail = (["A false return? `buddie intro --false` restarts the count; `buddie enforce` ends the intro."]
                if tour else [])
        warn([head] + [f"- {i}" for i in warned] + tail, out)
    if not code:
        return 0, why
    print(pred["line"], file=err)
    for item in blocking:
        print(f"- {item}", file=err)
    if any(item.startswith("quote ") for item in blocking):
        print("Quotes were judged against the snapshots in " + (", ".join(map(str, stores)) or "no session store")
              + " (newest with bytes per URL; a URL in none of them was fetched now).", file=err)
    ready = ready_anchors(text, items, transcript=event.get("transcript_path"), github=github)
    if ready:
        print("Ready anchors, checked now (copy as is onto the line):", file=err)
        for item in ready:
            print(item, file=err)
    print("Fix each item (copy the quote from the source text: buddie source_text / verbatim text; refresh the "
          "anchor or add one), or keep it and add a line starting with 'buddie:' that tells the reader what is "
          "unverified and why.", file=err)
    if hard:
        print("A 'buddie:' line does not cover a broken pr:/ci:/run: anchor or work claimed in prose: correct the "
              "anchor or add one (the ready anchors above), or remove the claim and say in prose what is not done.",
              file=err)
    return 2, []


def main() -> int:
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8"))  # Claude Code sends UTF-8 (Windows: not the locale's)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    try:
        return run(event)
    except Exception as error:  # a broken gate must not stop the session; say so and let the answer through
        print(f"buddie hook error (answer not checked): {type(error).__name__}: {error}", file=sys.stderr)
        return 0
