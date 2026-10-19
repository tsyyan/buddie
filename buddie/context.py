"""The context gate (NEXT №58): a thread past 200 thousand tokens of context hands in its result.

The project rule (№32) says a thread whose context is over 200k takes no new subtasks: it hands in its result and
the next step goes to a new thread. As text the rule did not hold (№40, audit/09_sources/turn_cost_40.md: two
threads ran at 320-350k for hours and made $34 of $105), because a thread does not see its own context.

The hook sees it: the last main-chain API call in transcript_path carries `usage`, and its input, cache read and
cache write tokens are the context that call read. Over the limit, a reply that is not a final answer is returned
with a reminder; a final answer (the mark `Следующий шаг:`) and a hand-over to another session pass, and a
`buddie:` line (the user asked for this reply) lets it through like any other return.

Inside a turn (NEXT №106): by №59 (audit/09_sources/turn_cost_59.md) the gate on `reply` never fired, while seven
turns that crossed the limit midway made $40.28 (№57: 124 API calls, 51 subagents) and threads woken above it did
$12.09 more answering only by `send_message`. So past the limit a subagent launch (`Agent`, `Task`) is returned too,
and a hand-over stops passing once the thread has handed in its result before the current turn (it was woken
again): only a final answer of this turn, or a `buddie:` line, lets such a `send_message` out.

Env: BUDDIE_CONTEXT_LIMIT sets the limit in tokens (default 200000; 0 turns the gate off).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

LIMIT = 200_000
HANDOVER = ("send_message", "SendMessage")  # passing the next step on to the coordinator is the way out
SPAWN = ("Agent", "Task")  # a subagent launched past the limit is more work in a thread that should hand in


def limit() -> int:
    try:
        return int(os.environ.get("BUDDIE_CONTEXT_LIMIT", LIMIT))
    except ValueError:
        return LIMIT


def last_context(transcript: str | None) -> int | None:
    """Tokens the last main-chain API call of the session read (input + cache read + cache write), or None."""
    if not transcript:
        return None
    try:
        raw = Path(transcript).read_text(encoding="utf-8")
    except OSError:
        return None
    found = None
    for line in raw.splitlines():
        if '"usage"' not in line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant" or entry.get("isSidechain"):
            continue
        usage = (entry.get("message") or {}).get("usage")
        if isinstance(usage, dict):
            found = sum(int(usage.get(k) or 0) for k in
                        ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    return found


def spawning(event: dict) -> bool:
    return event.get("hook_event_name") == "PreToolUse" and event.get("tool_name") in SPAWN


def woken(transcript: str | None, final) -> bool:
    """The thread handed in a final answer (`final(text)`) before its current turn and was woken again: the last
    user turn of the main chain comes after the last final answer. A tool result is not a turn."""
    from buddie.hook import tool_text
    if not transcript:
        return False
    try:
        raw = Path(transcript).read_text(encoding="utf-8")
    except OSError:
        return False
    last_final = last_turn = None
    for i, line in enumerate(raw.splitlines()):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict) or entry.get("isSidechain") or entry.get("isMeta"):
            continue
        content = (entry.get("message") or {}).get("content")
        if entry.get("type") == "user":
            if isinstance(content, str) or isinstance(content, list) and any(
                    isinstance(c, dict) and c.get("type") != "tool_result" for c in content):
                last_turn = i
        elif entry.get("type") == "assistant" and isinstance(content, list):
            texts = [c.get("text") or "" for c in content if isinstance(c, dict) and c.get("type") == "text"] + [
                tool_text(c.get("input") or {}) for c in content if isinstance(c, dict) and c.get("type") == "tool_use"]
            if any(t and final(t) for t in texts):
                last_final = i
    return last_final is not None and last_turn is not None and last_turn > last_final


def over(event: dict, final: bool, tokens: int | None, transcript_final=None) -> str | None:
    """The reminder when this reply should be the thread's result instead, else None. `transcript_final` (text ->
    is it a final answer) lets a hand-over be checked for a thread woken after its result (NEXT №106)."""
    cap = limit()
    if not cap or tokens is None or tokens <= cap or final:
        return None
    if event.get("hook_event_name") != "PreToolUse":
        return None
    k = tokens // 1000
    if spawning(event):
        return (f"context {k}k tokens is over {cap // 1000}k (project rule №32): do not launch a subagent now. "
                "Hand in what is done as the final answer (anchors, «Следующий шаг:», send the step to the "
                "coordinator); the subagent's task goes to a new thread as the next step. If the user asked for this "
                f"very launch, add a line 'buddie: контекст треда {k} тыс., запуск по просьбе пользователя' "
                "to its prompt.")
    if any(h in (event.get("tool_name") or "") for h in HANDOVER):
        if not (transcript_final and woken(event.get("transcript_path"), transcript_final)):
            return None
        return (f"context {k}k tokens is over {cap // 1000}k and this thread already handed in its result before "
                "this turn (project rule №32): do no new work in it. Answer in a few lines what the sender needs, "
                "and put any further work into a NEXT.md row for a new thread. If this message is a new result, "
                f"end it with «Следующий шаг:»; if the user asked for it, add a line 'buddie: контекст треда {k} "
                "тыс., дальше лучше новым тредом'.")
    return (f"context {k}k tokens is over {cap // 1000}k (project rule №32): take no new subtasks. "
            "Hand in the result now as the final answer (anchors, «Следующий шаг:», send the step to the "
            "coordinator); the next step goes to a new thread. If the user asked for this very reply, keep it and "
            f"add a line 'buddie: контекст треда {k} тыс., дальше лучше новым тредом'.")
