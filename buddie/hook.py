"""Gate before an answer leaves the session (Claude Code hooks; Grok Build reads the same plugin format).

PreToolUse on a tool that sends text to people or to another session (reply, post_message, send_message):
the text is in tool_input. Stop: the final answer is the last assistant message of the transcript.

FAIL (a quote not in its source, a broken anchor) blocks with exit 2: the reason goes to the model, which fixes the
text and sends again. The model may also send it unchanged with a line that starts with `buddie:` saying what was
not fixed and why: then the misses are disclosed to the reader and the gate lets it through. GAPS and PASS never
block. A Stop hook already re-entered (stop_hook_active) never blocks, so the gate cannot loop.

A final answer (text with the mark `Следующий шаг:`, the project's last line of a thread result; BUDDIE_FINAL sets
another regex, empty turns it off) must also carry its numbers: at least one anchor, and no line stating a count or
a share without one. Otherwise the gate checks nothing (NEXT №21: thread answers had no anchors, every receipt was
EMPTY), so it blocks the same way and the same `buddie:` line lets it through.

Every run appends one JSON line (time, tool, outcome, exit code) to $BUDDIE_LOG, default ~/.cache/buddie/hook.jsonl,
so a passing gate leaves a trace too; BUDDIE_LOG=0 turns it off. A cloud container's home is gone when the session
ends, so where a project shared folder exists (/mnt/project-files) the same line also goes to
<BUDDIE_SHARED_LOG>/<session_id>.jsonl, default /mnt/project-files/buddie/hook (0 turns it off): one file per
session, so sessions never write the same file. Each line counts the work claims of the text (NEXT №43): effect
anchors, how many BROKEN, and lines that claim work in prose with no anchor; dogfood/effects/measure.py sums them.

Effect anchors (pr:, ci:, run:, buddie/effects.py) are judged against GitHub and this session's transcript_path.

Env: BUDDIE_FETCH=0 checks only what is already in the store; BUDDIE_REPOS=dir:dir sets the repos for anchors;
BUDDIE_GITHUB=0 leaves pr:/ci: anchors UNCHECKABLE instead of asking GitHub.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

TEXT_KEYS = ("text", "message", "body", "content")
DISCLOSED = re.compile(r"^\s*buddie\s*:", re.I | re.M)
FINAL_MARK = "Следующий шаг:"
SHARED_ROOT = Path("/mnt/project-files")


def final_answer(text: str) -> bool:
    mark = os.environ.get("BUDDIE_FINAL", FINAL_MARK)
    return bool(mark) and re.search(mark, text) is not None


def unbacked(pred: dict) -> list[str]:
    """Why a final answer does not carry its numbers: no anchor at all, or count lines without one."""
    out = []
    if not pred["anchors"]:
        out.append("final answer has no anchor: anchor its result (⚓ path@commit, ⚓ path#sha256, ⚓ fact=value, "
                   "⚓ pr:OWNER/REPO#N=merged, ⚓ ci:OWNER/REPO@SHA=success or ⚓ run:CMD => OUTPUT)")
    out += [f"number without anchor, {u}" for u in pred["unanchored"]]
    return out


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
        parts = [c.get("text", "") for c in content if c.get("type") == "text"] if isinstance(content, list) else []
        if any(p.strip() for p in parts):
            text = "\n".join(parts)
    return text


def run(event: dict, err=None) -> int:
    from buddie.anchors import find_repos
    from buddie.effects import github_get
    from buddie.verify import verify
    err = err or sys.stderr
    name = event.get("hook_event_name")
    if name == "Stop":
        if event.get("stop_hook_active") or not event.get("transcript_path"):
            return 0
        text = last_answer(event["transcript_path"])
    else:
        text = tool_text(event.get("tool_input") or {})
    if not text.strip():
        return 0
    cwd = Path(event.get("cwd") or os.getcwd())
    env_repos = [Path(p) for p in os.environ.get("BUDDIE_REPOS", "").split(os.pathsep) if p]
    receipt = verify(text, name=event.get("tool_name") or name or "answer", repos=env_repos or find_repos(cwd),
                     fetch=os.environ.get("BUDDIE_FETCH", "1") != "0",
                     github=github_get if os.environ.get("BUDDIE_GITHUB", "1") != "0" else None,
                     transcript=event.get("transcript_path"), numbers=os.environ.get("BUDDIE_NUMBERS", "gap"))
    pred = receipt["predicate"]
    final = final_answer(text)
    blocking = pred["blocking"] + (unbacked(pred) if final else [])
    code = 2 if blocking and not DISCLOSED.search(text) else 0
    log({"at": pred["checked_at"], "session": event.get("session_id"), "event": name, "tool": event.get("tool_name"),
         "final": final, "work": pred["summary"]["work"],
         "outcome": pred["outcome"], "sha256": receipt["subject"][0]["digest"]["sha256"], "exit": code,
         "effects": {f"{a['kind']}:{a['status']}": sum(1 for b in pred["anchors"] if b.get("kind") == a["kind"]
                                                       and b["status"] == a["status"])
                     for a in pred["anchors"] if a.get("kind")}})
    if not code:
        return 0
    print(pred["line"], file=err)
    for item in blocking:
        print(f"- {item}", file=err)
    print("Fix each item (copy the quote from the source text: buddie source_text / verbatim text; refresh the "
          "anchor or add one), or keep it and add a line starting with 'buddie:' that tells the reader what is "
          "unverified and why.", file=err)
    return 2


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    try:
        return run(event)
    except Exception as error:  # a broken gate must not stop the session; say so and let the answer through
        print(f"buddie hook error (answer not checked): {type(error).__name__}: {error}", file=sys.stderr)
        return 0
