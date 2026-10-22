"""What a hook event names, read the same way by every part that needs it: the text a tool sends, and the repos
around the session. Moved out of hook.py and promises.py so that config.py and context.py need neither."""
from __future__ import annotations

from pathlib import Path

TEXT_KEYS = ("text", "message", "body", "content")


def tool_text(tool_input: dict) -> str:
    return "\n\n".join(v for k in TEXT_KEYS if isinstance(v := tool_input.get(k), str))


def repos_of(event: dict) -> list[Path]:
    """BUDDIE_REPOS (the hook's environment), else the git checkout around the event's cwd; a protected policy with
    [evidence] repos = "event" sets BUDDIE_REPOS aside (buddie/evidence.py)."""
    from buddie.evidence import repos
    return [s.path for s in repos(event)]
