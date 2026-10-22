"""Codex: its Stop event carries the final answer in last_assistant_message, and its transcript_path is a Codex
session log, not a Claude Code transcript (integrations/codex, docs/install-codex.md)."""
from __future__ import annotations

import io
import json

from pathlib import Path

from buddie import hook
from buddie.verify import verify
from test_buddie import BAD, store  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]
CODEX_LOG = [  # the shape of ~/.codex/sessions/.../rollout-*.jsonl, codex-cli 0.153
    {"type": "session_meta", "payload": {"id": "019a", "cwd": "/w"}},
    {"type": "response_item", "payload": {"type": "custom_tool_call", "call_id": "c1", "name": "exec",
                                          "input": "text(await tools.exec_command({cmd: 'pytest -q'}))"}},
    {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c1",
                                          "output": [{"type": "input_text", "text": "41 passed"}]}},
]


def codex_stop(tmp_path, text, log=True):
    path = None
    if log:
        path = tmp_path / "rollout.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in CODEX_LOG), encoding="utf-8")
    return {"session_id": "019a", "transcript_path": str(path) if path else None, "cwd": str(tmp_path),
            "hook_event_name": "Stop", "model": "gpt-5-codex", "turn_id": "t1", "stop_hook_active": False,
            "last_assistant_message": text}


def test_stop_text_comes_from_the_event(store, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setenv("BUDDIE_FETCH", "0")
    for log in (False, True):
        assert hook.run(codex_stop(tmp_path, BAD, log), io.StringIO()) == 2
        assert hook.run(dict(codex_stop(tmp_path, BAD, log), stop_hook_active=True), io.StringIO()) == 0


def test_run_anchor_is_unchecked_on_a_codex_log(tmp_path):
    log = tmp_path / "rollout.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in CODEX_LOG), encoding="utf-8")
    receipt = verify("Tests pass. ⚓ `run:pytest -q => 41 passed`\n", repos=[], fetch=False, github=None,
                     mandate=False, transcript=str(log))
    (anchor,) = receipt["predicate"]["anchors"]
    assert anchor["status"] == "UNCHECKABLE" and "not a Claude Code session" in anchor["why"]
    assert receipt["predicate"]["outcome"] == "GAPS"


def test_codex_plugin_server_does_not_judge_against_its_own_repo(tmp_path, monkeypatch):
    from buddie import mcp
    monkeypatch.chdir(ROOT)  # where Codex starts the plugin's server: a copy of this repository
    monkeypatch.setenv("BUDDIE_DEFAULT_REPOS", "none")
    assert mcp.default_repos() == []
    manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    server = manifest["mcpServers"]["buddie"]
    assert server["env"]["BUDDIE_DEFAULT_REPOS"] == "none" and server["cwd"] == "."
    assert (ROOT / server["args"][0]).is_file()
    for path in (manifest["skills"], manifest["hooks"]):
        assert path.startswith("./") and (ROOT / path).exists()
    hooks = json.loads((ROOT / manifest["hooks"]).read_text(encoding="utf-8"))["hooks"]
    assert set(hooks) == {"Stop"} and "${PLUGIN_ROOT}/run.py" in hooks["Stop"][0]["hooks"][0]["command"]


# --- the hook command: Python isolated (-I) -----------------------------------------------------------------------

def _codex_hook(windows: bool) -> list[str]:
    """The Codex Stop hook's command as argv, with this interpreter for python3/python."""
    import shlex
    import sys
    spec = json.loads((ROOT / "integrations" / "codex" / "hooks.json").read_text(encoding="utf-8"))
    hook_def = spec["hooks"]["Stop"][0]["hooks"][0]
    line = hook_def["commandWindows" if windows else "command"].replace("${PLUGIN_ROOT}", ROOT.as_posix())
    argv = shlex.split(line)
    assert argv[0] == ("python" if windows else "python3")
    return [sys.executable, *argv[1:]]


def test_the_codex_hook_runs_python_isolated(tmp_path):
    """A project's settings can set PYTHONPATH for the hook; with -I nothing on it loads into buddie, and the hook
    still answers (run.py puts its own folder on sys.path). Without -I the injected module runs first."""
    import os
    import subprocess
    inject = tmp_path / "inject"
    inject.mkdir()
    marker = tmp_path / "loaded"
    (inject / "sitecustomize.py").write_text(f"open(r'{marker}', 'w').write('x')\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(inject), "BUDDIE_LOG": str(tmp_path / "h.jsonl"), "BUDDIE_FETCH": "0",
           "BUDDIE_GITHUB": "0", "BUDDIE_STATE": str(tmp_path / "p"), "BUDDIE_LESSONS": "0"}
    event = json.dumps({"hook_event_name": "Stop", "session_id": "s", "cwd": str(tmp_path),
                        "last_assistant_message": "Nothing to check here."}).encode()
    for windows in (False, True):
        argv = _codex_hook(windows)
        assert argv[1] == "-I"
        got = subprocess.run(argv, input=event, capture_output=True, env=env, timeout=120)
        assert got.returncode == 0 and not marker.exists(), got.stderr
    unisolated = [a for a in _codex_hook(False) if a != "-I"]
    subprocess.run(unisolated, input=event, capture_output=True, env=env, timeout=120)
    assert marker.exists()  # what -I prevents
