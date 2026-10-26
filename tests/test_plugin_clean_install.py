"""A copied git-source plugin starts outside the checkout without pip or optional credentials."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_git_source_plugin_runs_mcp_and_hook_without_credentials(tmp_path):
    installed = tmp_path / "plugin with spaces"
    paths = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True).stdout
    for raw in paths.split(b"\0"):
        if not raw:
            continue
        path = raw.decode("utf-8")
        target = installed / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
    cwd = tmp_path / "session"
    cwd.mkdir()
    env = {k: v for k, v in os.environ.items() if k.upper() in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE")}
    env.update(BUDDIE_FETCH="0", BUDDIE_GITHUB="0", BUDDIE_LOG="0", BUDDIE_SHARED_LOG="0", BUDDIE_STATE="0",
               VERBATIM_STORE=str(cwd / "store"), CLAUDE_PLUGIN_ROOT=installed.as_posix(), PYTHONIOENCODING="utf-8")
    manifest = json.loads((installed / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    assert manifest["userConfig"]["github_token"]["sensitive"] is True
    assert manifest["userConfig"]["github_token"]["required"] is False
    server = json.loads((installed / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["buddie"]
    # Resolve the declared interpreter to this test's Python, as an installation's PATH would. Use its real args.
    assert server["command"] == "python3"
    args = [a.replace("${CLAUDE_PLUGIN_ROOT}", str(installed)) for a in server["args"]]
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "verify_report", "arguments": {
            "text": "Ready for review.", "fetch": False, "github": False}}},
    ]
    out = subprocess.run([sys.executable, *args], cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8",
                         input="".join(json.dumps(m) + "\n" for m in messages), timeout=60)
    assert out.returncode == 0, out.stderr
    replies = [json.loads(line) for line in out.stdout.splitlines()]
    assert replies[0]["result"]["serverInfo"]["version"] == manifest["version"]
    assert {t["name"] for t in replies[1]["result"]["tools"]} == {
        "verify_report", "snap", "source_text", "summary", "environment_snapshot"}
    assert not replies[2]["result"].get("isError", False)
    hooks = json.loads((installed / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
    command = hooks["Stop"][0]["hooks"][0]["command"]
    if shutil.which("sh"):
        out = subprocess.run(["sh", "-c", command], cwd=cwd, env=env, capture_output=True, text=True,
                             input=json.dumps({"hook_event_name": "Stop", "cwd": str(cwd),
                                               "last_assistant_message": "Ready for review."}), timeout=60)
        assert out.returncode == 0, out.stderr
    assert not (installed / ".git").exists()
