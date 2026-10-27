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

from buddie.config import final_mark  # noqa: F401 - hook.final_mark, as before
from buddie.event import TEXT_KEYS, tool_text  # noqa: F401
from buddie.logbook import SHARED_ROOT, journal_paths, log, log_targets  # noqa: F401 - hook.log, as before

DISCLOSED = re.compile(r"^\s*buddie\s*:", re.I | re.M)
EFFECT_KINDS = ("pr", "ci", "run")
HANDBACK = "SubagentHandback"
# returns about a check that could not be done as configured: a text the agent writes afterwards cannot show it was
# checked, so a re-entered Stop after one of them tells the person (systemMessage) that the answer went out unchecked
UNCHECKED = {"internal_error": "buddie could not run its check",
             "config": "the project's buddie.toml cannot be used",
             "policy": "the protected policy cannot be used",
             "typed_mismatch": "buddie's findings did not line up with its items"}


def final_answer(text: str, event: dict | None = None, ctx=None) -> bool:
    """Whether `text` is a final answer (ctx: the event's ResolvedEventContext, whose final mark is already read)."""
    event = event or {}
    mark = ctx.final_mark if ctx is not None else final_mark(event)
    if mark is None:
        return event.get("hook_event_name") == "Stop"
    return bool(mark) and re.search(mark, text) is not None


def unbacked(pred: dict, text: str | None = None) -> list[str]:
    """Why a final answer does not carry its numbers: no anchor at all, or count lines without one. Whether it
    carries an anchor is read from `text` when given: a profile that does not check anchors leaves the receipt's
    list empty, and that is not the answer having none (without a profile every anchor is in it, so both agree)."""
    from buddie.anchors import ANCHOR
    out = []
    if not pred["anchors"] and not (text is not None and ANCHOR.search(text)):
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


# what the model reads first when its text is returned: it may not know buddie (a plugin someone just installed)
RETURNED = ("buddie (a plugin that checks claims against their sources, without a model) sent this text back: the "
            "items below do not hold. Nothing else in the text was judged.")
FIX = ("Fix each item: copy a quote character for character from its page (buddie's source_text tool, after snap), "
       "or correct the anchor (ready anchors are listed above when buddie could compute them). If an item cannot be "
       "fixed, keep it and add a line starting with 'buddie:' that tells the reader what is unverified and why.")

SEND = re.compile(r"(?:^|__)(?:reply|post_message|send_message)$|^SendMessage$")


def handed_in(event: dict, ctx=None) -> bool:
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
                if final_answer(tool_text(c.get("input") or {}), dict(event, hook_event_name="PreToolUse"), ctx):
                    sent[c.get("id")] = True
            elif c.get("type") == "tool_result" and sent.pop(c.get("tool_use_id"), False) and not c.get("is_error"):
                passed = True
    return passed


def unchecked_return(event: dict) -> list[str]:
    """What the last return of this session's Stop was about, of the kinds that mean it was not checked as
    configured (UNCHECKED); [] when there is none or the state is off."""
    from buddie import journal
    before = journal.take_pending(event.get("session_id"), event.get("tool_name") or event.get("hook_event_name"),
                                  _state_root())
    return sorted({UNCHECKED[i["kind"]] for i in before or [] if i.get("kind") in UNCHECKED})


def _state_root() -> str | None:
    """Where the return state lives: as the environment says, unless a protected policy keeps tracking on."""
    from buddie import resolved
    from buddie.policy import current
    return resolved.state_root(current().effective)


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


def receipt_for(text: str, event: dict, numbers: str = "gap", ctx=None) -> tuple[dict, list]:
    """The receipt of `text`, and the snapshot stores its quotes were judged against (numbers: verify's mode,
    BUDDIE_NUMBERS overrides it)."""
    receipt, stores, _ = assess_for(text, event, numbers, ctx)
    return receipt, stores


def assess_for(text: str, event: dict, numbers: str = "gap", ctx=None) -> tuple[dict, list, list]:
    """receipt_for with the typed findings the receipt's outcome came from (verify.assess). ctx: the event's
    ResolvedEventContext, whose repos and [mandate] config are used instead of being looked up again."""
    from buddie import evidence
    from buddie.effects import github_get
    from buddie.event import repos_of
    from buddie.verify import assess, assess_selected
    cwd = Path(event.get("cwd") or os.getcwd())
    network = ctx.network_allowed if ctx is not None else True  # a protected policy may forbid it, nothing grants it
    github = github_get if network and os.environ.get("BUDDIE_GITHUB", "1") != "0" else None
    repos = list(ctx.repos) if ctx is not None else repos_of(event)
    # the snapshot stores the session used, or (policy: stores = "observed") one made for this check alone
    with evidence.store_for(cwd, repos, event.get("transcript_path")) as (store, chosen):
        args = dict(name=event.get("tool_name") or event.get("hook_event_name") or "answer", repos=repos, store=store,
                    fetch=network and os.environ.get("BUDDIE_FETCH", "1") != "0", github=github,
                    transcript=event.get("transcript_path"), mandate=ctx.mandate if ctx is not None else True,
                    numbers=effective_numbers(numbers))
        # no profile: verify.assess, every check, as before profiles; a profile: exactly the checks its levels
        # leave on after the policy's floors, none if none is (an empty selection is not "all")
        selection = ctx.effective() if ctx is not None else None
        receipt, found, _ = assess(text, **args) if selection is None else assess_selected(text, selection=selection,
                                                                                          **args)
    return (receipt, evidence.Chosen([s.path for s in chosen if s.origin is not evidence.Origin.OBSERVED],
                                     chosen.unavailable), found)


def observed_only() -> bool:
    from buddie.evidence import limits
    lim = limits()
    return lim is not None and lim.stores == "observed"


def effective_numbers(numbers: str) -> str:
    """verify's numbers mode: the level's, unless BUDDIE_NUMBERS names one."""
    return os.environ.get("BUDDIE_NUMBERS", numbers)


def stop_text(event: dict) -> str:
    """The final answer at Stop: the event's own last_assistant_message (Claude Code and Codex send it; Claude Code's
    docs say the transcript is written asynchronously and may not hold the turn's last message yet), else the last
    assistant text of a Claude Code transcript."""
    sent = event.get("last_assistant_message")
    if isinstance(sent, str) and sent.strip():
        return sent
    path = event.get("transcript_path")
    return last_answer(path) if path and Path(path).is_file() else ""


def outgoing(event: dict) -> str:
    """The text that leaves the session with this event: the final answer at Stop, the tool's text at PreToolUse."""
    if event.get("hook_event_name") == "Stop":
        return stop_text(event)
    return tool_text(event.get("tool_input") or {})


def run(event: dict, err=None, out=None) -> int:
    from buddie import context, decisions, promises, resolved, summary
    err = err or sys.stderr
    ctx = resolved.resolve(event)  # once per event: the repos, their buddie.toml, the settings and their sources
    if ctx.transcript.value != "on":
        # the person turned transcript reading off: nothing below opens the session log
        event = {**event, "transcript_path": None, "agent_transcript_path": None}
        ctx = ctx.with_event(event)
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
        summary.on_stop_subagent(event, text, receipt_for(text, event, ctx=ctx)[0] if text.strip() else None)
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
    if context.spawning(event) and spawn_held(event, err, out, ctx):
        return 2
    if promises.is_launch(event):
        return promises.gate(event, err)

    def passed() -> list[str]:
        promises.record(event, outgoing(event), words=ctx.journal_text)
        if name != "Stop":
            return []
        lv, why = ctx.level, []
        for cls, demand in (("summary", summary.on_stop), ("promises", promises.on_stop)):
            if lv[cls] != "off" and (w := demand(event)):
                why.append(w) if lv[cls] == "block" else warn([w], out)
        return why

    code, why = gate(event, err, passed, out, ctx)
    if why:
        print("\n\n".join(why), file=err)
        return 2
    return code


def spawn_held(event: dict, err, out=None, ctx=None) -> bool:
    """The context gate on a subagent launch (NEXT №106): past the limit the launch is returned, unless its prompt
    carries a `buddie:` line (the user asked for it); in the intro mode it only warns. The launch has no text to
    verify, so this runs before the launch gate and the journal line is its own."""
    from buddie import config, context, resolved
    from buddie.promises import strings
    from buddie.summary import now_iso
    ctx = ctx if ctx is not None else resolved.resolve(event)
    path, cfg = ctx.config_path, ctx.config
    if ctx.level["context"] == "off":
        return False
    tokens = context.last_context(event.get("transcript_path"))
    heavy = context.over(event, False, tokens)
    if not heavy:
        return False
    disclosed = bool(DISCLOSED.search("\n".join(strings(event.get("tool_input") or {}))))
    tour = config.intro(path, cfg) if ctx.intro_allowed else None
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


def gate(event: dict, err, passed=lambda: [], out=None, ctx=None) -> tuple[int, list[str]]:
    """The gate's exit code, and when it lets the text out, what `passed` returns (the reasons to return a Stop
    anyway). The journal line is written after `passed`, so it carries the exit code the hook really returns.
    Each blocking item goes by its class's level in buddie.toml [gates] (buddie/config.py): block returns the
    text, warn lets it out with a systemMessage, off drops it; in the intro mode nothing is returned."""
    from buddie import config, context, journal, resolved
    from buddie.effects import github_get
    from buddie.suggest import ready_anchors
    ctx = ctx if ctx is not None else resolved.resolve(event)
    name = event.get("hook_event_name")
    if name == "Stop":
        text = "" if event.get("stop_hook_active") else stop_text(event)
    else:
        text = tool_text(event.get("tool_input") or {})
    if not text.strip():
        why = passed()
        if why:
            demanded(event, why)
        elif name == "Stop" and event.get("stop_hook_active") and (left := unchecked_return(event)):
            # Claude Code re-enters Stop after a return; the gate never holds it (that is what ends the loop), so
            # the answer the model gives now goes out unchecked. The person hears it from buddie, not from the agent
            warn([f"buddie: this answer was not checked ({', '.join(left)}). buddie returned it once and does not "
                  "hold a re-entered Stop; read it as unverified."], out)
            beat(event, empty=True, active=True, exit=0, status="unchecked_disclosed", by="buddie",
                 unchecked=sorted(left))
        elif name == "Stop":
            beat(event, empty=True, active=bool(event.get("stop_hook_active")), exit=0)
        return 0, why
    github = github_get if ctx.network_allowed and os.environ.get("BUDDIE_GITHUB", "1") != "0" else None
    path, cfg = ctx.config_path, ctx.config
    lv = ctx.level
    numbers = effective_numbers(config.numbers_mode(lv["numbers"]))
    receipt, stores, found = assess_for(text, event, numbers, ctx)
    pred = receipt["predicate"]
    final = final_answer(text, event, ctx)
    tokens = context.last_context(event.get("transcript_path"))
    heavy = lv["context"] != "off" and context.over(event, final, tokens, lambda t: final_answer(t, event, ctx))
    extra = ([{"kind": "context", "line": None, "text": ""}] if heavy else []) \
        + [{"kind": "config", "line": None, "text": ""} for _ in ctx.config_errors] \
        + ([{"kind": "policy", "line": None, "text": ""}] if ctx.policy and ctx.policy.status.value == "invalid" else [])
    prose = prose_claims(text, pred) if final and not (name == "Stop" and handed_in(event, ctx)) else []
    # each item with its class: verify's items by the check of the finding behind each (gate_items), the gate's own
    # items by what makes them. A class the levels do not know blocks, as an unclassified item always did
    typed, mismatch = gate_items(pred, found, numbers)
    every = typed + [(i, "final") for i in (unbacked(pred, text) if final else [])] \
        + [(i, "prose") for i in prose] + ([(heavy, "context")] if heavy else []) \
        + [(config_item(e), "config") for e in ctx.config_errors] \
        + ([(policy_item(ctx.policy), "policy")] if ctx.policy and ctx.policy.status.value == "invalid" else [])
    level = [lv.get(cls or "", "block") for _, cls in every]
    blocking = [i for (i, _), lvl in zip(every, level) if lvl == "block"]
    warned = [i for (i, _), lvl in zip(every, level) if lvl == "warn"]
    blocked = [cls for (_, cls), lvl in zip(every, level) if lvl == "block"]
    if mismatch:
        extra.append({"kind": "typed_mismatch", "line": None, "text": ""})
    # a broken effect anchor is a false claim about work, not a miss to disclose: only fixing or removing it lets the
    # text through (NEXT №62; №40 13:55 sent `pr:…=open` for a merged PR with a `buddie:` line and passed). Work
    # claimed in prose in a final answer is the same (NEXT №63, audit/15 «в main влиты №40, №58…» with no pr:)
    hard = "prose" in blocked or lv["anchors"] == "block" and any(
        a.get("kind") in EFFECT_KINDS and a["status"] == "BROKEN" for a in pred["anchors"])
    tour = config.intro(path, cfg) if ctx.intro_allowed else None
    if tour:  # the intro mode: what would be returned only warns (audit/20 §3.3)
        warned, blocking, hard = warned + blocking, [], False
        if final:
            tour["seen"] = config.count_final(path)
    session, tool = event.get("session_id"), event.get("tool_name") or name
    before = journal.take_pending(session, tool, ctx.state_root)
    # a 'buddie:' line may say up front what cannot be checked (a count made by hand, a missing anchor). What buddie
    # checked against its source and found false (a quote not on its page, an anchor or a number that does not hold)
    # it covers only once buddie has returned the text: written before, it pre-empts the check (an eval run,
    # 2026-10-20: a quote buddie had found altered went out under "buddie: unverified"). Returns not tracked
    # (BUDDIE_STATE=0): as before
    found_false = [c for c in blocked if c in ("quotes", "anchors", "numbers", "config", "policy", None)]
    preempted = (bool(DISCLOSED.search(text)) and bool(found_false) and before is None
                 and journal.tracks_returns(ctx.state_root))
    # a protected policy may say no `buddie:` line lets a returned answer out: then only a fix does
    disclosed = bool(DISCLOSED.search(text)) and not preempted and ctx.disclosure_allowed
    code = 2 if hard or (blocking and not disclosed) else 0
    items = journal.flagged(pred, text, final) + extra if code else []
    entry = {"at": pred["checked_at"], "session": session, "event": name, "tool": event.get("tool_name"),
             "final": final, "context": tokens, "work": pred["summary"]["work"],
             "quotes": pred["summary"]["quotes"], "stores": len(stores),
             "outcome": pred["outcome"], "sha256": receipt["subject"][0]["digest"]["sha256"], "exit": code,
             "effects": {f"{a['kind']}:{a['status']}": sum(1 for b in pred["anchors"] if b.get("kind") == a["kind"]
                                                           and b["status"] == a["status"])
                         for a in pred["anchors"] if a.get("kind")}}
    if code:
        entry["reasons"] = journal.reasons(items)
    if getattr(stores, "unavailable", None):
        entry["stores_unavailable"] = sorted({why for _, why in stores.unavailable})
    if ctx.config_errors:
        entry["config_errors"] = [{"path": str(e.path), "reason": e.reason} for e in ctx.config_errors]
    if mismatch:
        entry["typed_mismatch"] = mismatch
    if ctx.profile is not None:
        entry["profile"] = {"name": ctx.profile.profile, "checks": list(ctx.run_checks())}
    if ctx.policy is not None and (ctx.policy.status.value != "absent" or ctx.refused):
        entry["policy"] = {"status": ctx.policy.status.value, **({"refused": list(ctx.refused)} if ctx.refused else {})}
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
    journal.keep_pending(session, tool, items, ctx.state_root)
    if warned and not code:
        head = (f"buddie (intro, final {tour['seen']} of {tour['finals']}): would have returned this answer for"
                if tour else "buddie warns:")
        tail = (["A false return? `buddie intro --false` restarts the count; `buddie enforce` ends the intro."]
                if tour else [])
        warn([head] + [f"- {i}" for i in warned] + tail, out)
    if not code:
        return 0, why
    print(RETURNED, file=err)
    print(pred["line"], file=err)
    for item in blocking:
        print(f"- {item}", file=err)
    if "quotes" in blocked and observed_only():
        print("Quotes were judged only against pages fetched in this check (the protected policy's [evidence] "
              "stores = \"observed\"): snapshots the session took do not count.", file=err)
    elif "quotes" in blocked:
        print("Quotes were judged against the snapshots in " + (", ".join(map(str, stores)) or "no session store")
              + " (newest with bytes per URL; a URL in none of them was fetched now).", file=err)
    if "quotes" in blocked and getattr(stores, "unavailable", None):
        print("The sources/ stores a repo changed could not all be listed, so they may be missing from the above: "
              + "; ".join(f"{repo} ({why})" for repo, why in stores.unavailable)
              + ". git was not run unsafely for them (docs/security.md).", file=err)
    ready = ready_anchors(text, items, transcript=event.get("transcript_path"), github=github)
    if ready:
        print("Ready anchors, checked now (copy as is onto the line):", file=err)
        for item in ready:
            print(item, file=err)
    print(FIX, file=err)
    if preempted and not hard:
        print("The 'buddie:' line in this text was written before buddie checked it, so it does not count yet: buddie "
              "found the items above. Fix them; a 'buddie:' line about an item counts once you have seen it here.",
              file=err)
    if hard:
        print("A 'buddie:' line does not cover a broken pr:/ci:/run: anchor or work claimed in prose: correct the "
              "anchor or add one (the ready anchors above), or remove the claim and say in prose what is not done.",
              file=err)
    return 2, []


def gate_items(pred: dict, found: list, numbers: str) -> tuple[list[tuple[str, str | None]], dict | None]:
    """predicate.blocking with each item's gate class, from the finding behind it (verify.blocking_findings and
    config.CLASS_OF_CHECK), and None, or the mismatch when the findings do not line up with the items. Then no
    item gets a class: each blocks whatever the levels say (no level demotes what cannot be told apart), and the
    gate journals {findings, items}. The words' class (config.classify) is never the decision."""
    from buddie import config, verify
    behind = verify.blocking_findings(found, numbers)
    if len(behind) != len(pred["blocking"]):
        return [(i, None) for i in pred["blocking"]], {"findings": len(behind), "items": len(pred["blocking"])}
    return [(i, config.CLASS_OF_CHECK.get(f.check)) for i, f in zip(pred["blocking"], behind)], None


def policy_item(loaded) -> str:
    """The gate's item for a protected policy that is there but cannot be used (buddie/policy.py)."""
    return (f"buddie's protected policy cannot be used: {loaded.path}: {loaded.error}. buddie runs on its strictest "
            "limits until an administrator fixes or removes that file. This is not a fact of the text: keep the "
            "answer and add a line starting with 'buddie:' telling the reader the policy is broken")


def config_item(error) -> str:
    """The gate's item for a buddie.toml that cannot be used (resolved.ResolvedEventContext.config_errors)."""
    return (f"buddie.toml cannot be used: {error.path}: {error.reason}. None of its settings applied: the checks ran "
            "on buddie's defaults, without its [gates], [mandate] or [intro]. Fix the file, or keep the answer and add a "
            "line starting with 'buddie:' telling the reader the project's buddie settings were not applied")


EVENT_PROGRAMS = 40.0  # seconds all of an event's git (and the free command) may take together; the gating hooks
                       # have 60 to 120 seconds before the host stops them
EVENT_PATTERNS = 10.0  # seconds all of an event's buddie.toml patterns may take together (buddie/patterns.py)


def main() -> int:
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8"))  # Claude Code sends UTF-8 (Windows: not the locale's)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    from buddie import evidence, patterns, policy, runner
    try:
        with policy.snapshot():  # one reading of the protected policy for the whole event
            try:
                # the policy's network for the event's fetches (isolated or as set); one time budget for every
                # program the event starts, so a slow repository cannot hold the hook past the host's timeout
                with evidence.collector(), runner.deadline(EVENT_PROGRAMS), patterns.budget(EVENT_PATTERNS):
                    return run(event)
            except Exception as error:
                return failed(event, error)
    except Exception as error:  # noqa: BLE001 - not even the snapshot: failed() reads the policy itself
        return failed(event, error)


def guarded_text(event: dict) -> str:
    """The text this event lets out when the gate guards it: the final answer at a Stop that is not a re-entry, a
    text tool's message at PreToolUse. Empty for every other event (SessionStart, PostToolUse, a launch...)."""
    name = event.get("hook_event_name")
    try:
        if name == "Stop" and not event.get("stop_hook_active"):
            return stop_text(event)
        if name == "PreToolUse" and SEND.search(str(event.get("tool_name") or "")):
            return tool_text(event.get("tool_input") or {})
    except Exception:  # noqa: BLE001 - not even the text can be had: there is nothing to hold
        return ""
    return ""


def failed(event: dict, error: Exception, err=None) -> int:
    """The hook failed. A text the gate guards was not checked, so it does not leave as if it had been: it goes back
    once with the error (exit 2). A re-entered Stop (stop_hook_active) never gets here with text, so this cannot
    loop; a `buddie:` line telling the reader it was not checked lets it out. Any other event goes on (exit 0): its
    hook only keeps the journal and the summary, and a failure there must not stop the session."""
    from buddie import journal
    err = err or sys.stderr
    why = f"{type(error).__name__}: {error}"
    text = guarded_text(event)
    session, tool = event.get("session_id"), event.get("tool_name") or event.get("hook_event_name")
    # the 'buddie:' line counts only on an attempt after buddie returned this text for a failed check (the state
    # the gate keeps per session and tool); written before, it is the agent's own word that nothing needs checking
    from buddie.policy import current
    try:
        limits, root = current().effective, _state_root()
    except Exception:  # noqa: BLE001 - not even the policy: take its strictest reading, no disclosure
        from buddie.policy import STRICTEST
        limits, root = STRICTEST, None
    allowed = limits is None or limits.disclosure
    before = journal.take_pending(session, tool, root) if text.strip() else None
    after_return = any(i.get("kind") == "internal_error" for i in before or [])
    disclosed = bool(text.strip()) and bool(DISCLOSED.search(text)) and after_return and allowed
    held = bool(text.strip()) and not disclosed
    if held:
        print(f"buddie could not check this text ({why}), so it does not go out as checked. Send it again: the next "
              "attempt is checked anew. If buddie keeps failing, keep the text and add a line starting with "
              "'buddie:' that tells the reader it was not checked (a line written before this return does not "
              "count).", file=err)
        journal.keep_pending(session, tool, [{"kind": "internal_error", "line": None, "text": ""}], root)
    else:
        print(f"buddie hook error ({'answer not checked' if text.strip() else 'nothing to check'}): {why}", file=err)
        if disclosed:
            journal.keep_pending(session, tool, None, root)
    status = "unchecked_disclosed" if disclosed else "internal_error"
    try:
        from buddie.summary import now_iso
        # the error's type and where it was raised, not its message: a message may carry the answer's words
        tb = error.__traceback__
        while tb is not None and tb.tb_next is not None:
            tb = tb.tb_next
        where = f"{Path(tb.tb_frame.f_code.co_filename).name}:{tb.tb_lineno}" if tb is not None else None
        log({"at": now_iso(), "session": session, "event": event.get("hook_event_name"), "tool": event.get("tool_name"),
             "status": status, **({"by": "agent"} if disclosed else {}), "error": type(error).__name__,
             "where": where, "exit": 2 if held else 0})
    except Exception:  # noqa: BLE001 - the journal is a convenience: the exit code is what matters
        pass
    return 2 if held else 0
