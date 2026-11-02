"""Where buddie's journal lines go, and writing one (moved out of hook.py so that the parts the hook calls, the
summary, the decision cards and the promises, write the journal without importing the hook).

One JSON line per entry to $BUDDIE_LOG, default ~/.cache/buddie/hook.jsonl (BUDDIE_LOG=0 turns it off), and where a
project shared folder exists (/mnt/project-files, a cloud container's) to <BUDDIE_SHARED_LOG>/<session_id>.jsonl,
default /mnt/project-files/buddie/hook (0 turns it off): one file per session, so sessions never write the same file.
journal.py reads these lines back. Nothing here reads or writes a file until a function is called.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

SHARED_ROOT = Path("/mnt/project-files")


def default_log() -> Path:
    return Path.home() / ".cache" / "buddie" / "hook.jsonl"


def log_targets(session: str | None) -> list[Path]:
    """The journal files. A protected policy with [evidence] journal = "fixed" sets BUDDIE_LOG and BUDDIE_SHARED_LOG
    aside: the journal stays in its default places and cannot be turned off from the hook's environment. That keeps
    the record where the person looks for it; it does not keep the agent, the same OS user, from editing it."""
    from buddie import policy
    limits = policy.current().effective
    env = {} if limits is not None and limits.journal == "fixed" else os.environ
    out = []
    target = env.get("BUDDIE_LOG", str(default_log()))
    if target not in ("", "0"):
        out.append(Path(target))
    shared = env.get("BUDDIE_SHARED_LOG")
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


def journal_paths() -> list[Path]:
    """Where past sessions' journal lines are: the local log, and the whole shared folder when there is one."""
    out = []
    for target in log_targets(None):
        out.append(target.parent if target.name == "nosession.jsonl" else target)
    return out
