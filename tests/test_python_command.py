"""The plugin's "Python command" setting (python3 by default) starts the MCP server; on Windows without it, the
SessionStart hook tells the person which command works (a desktop Python from python.org has no python3)."""
from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest

from buddie import hook

ROOT = Path(__file__).resolve().parents[1]


def test_the_mcp_server_starts_with_the_persons_python_command():
    plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    option = plugin["userConfig"]["python_command"]
    assert option["type"] == "string" and option["default"] == "python3" and option["required"] is False
    assert "sensitive" not in option
    server = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["buddie"]
    assert server["command"] == "${user_config.python_command}"


def _windows(monkeypatch, works: set[str], chosen: str | None = None):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "C:/plugin")
    if chosen is None:
        monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_PYTHON_COMMAND", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_PYTHON_COMMAND", chosen)
    monkeypatch.setattr("shutil.which", lambda c: f"C:/bin/{c}.exe" if c in works | {"python3"} else None)

    def run(argv, **kw):
        name = Path(argv[0]).stem
        return subprocess.CompletedProcess(argv, 0 if name in works else 9009)
    monkeypatch.setattr(subprocess, "run", run)


def test_no_hint_outside_windows_or_outside_the_plugin(monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "/p")
    assert hook.python_hint("linux") is None
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT")
    assert hook.python_hint("win32") is None


def test_a_python_org_install_is_told_to_use_python(monkeypatch):
    _windows(monkeypatch, works={"python", "py"})  # python3 resolves to the Store stub, which fails
    hint = hook.python_hint("win32")
    assert "`python3`" in hint and "`python`" in hint and "/config" in hint


def test_a_working_setting_needs_no_hint(monkeypatch):
    _windows(monkeypatch, works={"python", "py"}, chosen="python")
    assert hook.python_hint("win32") is None
    _windows(monkeypatch, works={"python3"})
    assert hook.python_hint("win32") is None


def test_no_python_at_all_says_to_install_one(monkeypatch):
    _windows(monkeypatch, works=set())
    assert "install Python 3.11" in hook.python_hint("win32")


def test_session_start_puts_the_hint_and_the_context_in_one_json(monkeypatch, tmp_path):
    monkeypatch.setattr(hook, "python_hint", lambda: "buddie: hint")
    monkeypatch.setattr(hook, "beat", lambda *a, **k: None)
    monkeypatch.setattr(hook, "journal_paths", lambda: [])
    monkeypatch.setattr("buddie.journal.lessons", lambda *a, **k: "past lessons")
    monkeypatch.setattr("buddie.promises.session_start", lambda e: None)
    out = io.StringIO()
    assert hook.session_start({"hook_event_name": "SessionStart", "session_id": "s"}, out=out) == 0
    reply = json.loads(out.getvalue())
    assert reply["systemMessage"] == "buddie: hint"
    assert reply["hookSpecificOutput"] == {"hookEventName": "SessionStart", "additionalContext": "past lessons"}


def test_session_start_without_a_hint_prints_plain_context(monkeypatch):
    monkeypatch.setattr(hook, "python_hint", lambda: None)
    monkeypatch.setattr(hook, "beat", lambda *a, **k: None)
    monkeypatch.setattr(hook, "journal_paths", lambda: [])
    monkeypatch.setattr("buddie.journal.lessons", lambda *a, **k: "past lessons")
    monkeypatch.setattr("buddie.promises.session_start", lambda e: None)
    out = io.StringIO()
    hook.session_start({"hook_event_name": "SessionStart", "session_id": "s"}, out=out)
    assert out.getvalue() == "past lessons\n"
