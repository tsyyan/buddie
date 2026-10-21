"""What a hook event names, read the same way by every part that needs it: the text a tool sends, and the repos
around the session. Moved out of hook.py and promises.py so that config.py and context.py need neither."""
from __future__ import annotations

import os
from pathlib import Path

TEXT_KEYS = ("text", "message", "body", "content")


def tool_text(tool_input: dict) -> str:
    return "\n\n".join(v for k in TEXT_KEYS if isinstance(v := tool_input.get(k), str))


def repos_of(event: dict) -> list[Path]:
    """BUDDIE_REPOS (the person's environment), else the git checkout around the event's cwd."""
    from buddie.anchors import find_repos
    env = [Path(p) for p in os.environ.get("BUDDIE_REPOS", "").split(os.pathsep) if p]
    return env or find_repos(Path(event.get("cwd") or os.getcwd()))
