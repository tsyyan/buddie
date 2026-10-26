"""Smoke test of an installed or unpacked compact plugin (scripts/plugin_package.py), as Claude Code would run it.

    python scripts/smoke_plugin.py PLUGIN_DIR --manifest plugin-manifest.json

PLUGIN_DIR is the plugin as installed (Claude Code's plugin cache) or unpacked. It must hold exactly the manifest's
files, byte for byte, and nothing else (no .git, tests, experiments, results, docs or scripts). Then, from a clean
environment, a working directory outside the plugin, no pip install and no GitHub token:
  - the MCP server that .mcp.json declares answers initialize (the manifest's version), tools/list (this
    repository's tool list for the same commit) and a verify_report call
  - with an optional GitHub token set, well-formed or malformed, the server still answers and the token appears in
    no output (it is never sent: GitHub is off)
  - each hook command hooks.json declares for SessionStart and Stop runs and exits 0
plugin.json's userConfig keeps the token optional and sensitive. Exit 0, or 1 with each failure on stderr.
Standard library only; nothing is fetched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEVER = ("tests/", "experiments/", "results/", "evals/", "docs/", "scripts/", ".github/", "examples/",
         "integrations/", ".git/", ".codex-plugin/", "PROVENANCE.json")
FAKE_TOKEN = "ghp_" + "S" * 36  # a fake, well-formed token: it must never be printed
BAD_TOKEN = "ghp_has space\nand newline"
KEEP_ENV = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE", "COMSPEC", "PATHEXT")


def files_of(directory: Path) -> dict[str, bytes]:
    return {p.relative_to(directory).as_posix(): p.read_bytes() for p in sorted(directory.rglob("*"))
            if p.is_file() or p.is_symlink()}


def check_files(directory: Path, manifest: dict) -> list[str]:
    problems = []
    if any(p.is_symlink() for p in directory.rglob("*")):
        problems.append("the plugin holds a symlink")
    got = files_of(directory)
    want = {f["path"]: f for f in manifest["files"]}
    problems += [f"missing {p}" for p in sorted(set(want) - set(got))]
    problems += [f"unexpected {p}" for p in sorted(set(got) - set(want))]
    problems += [f"{p} differs from the manifest" for p in sorted(set(want) & set(got))
                 if hashlib.sha256(got[p]).hexdigest() != want[p]["sha256"]]
    problems += [f"{p} is a development or research file" for p in got if p.startswith(NEVER)]
    return problems


def _env(cwd: Path, plugin: Path, **extra) -> dict:
    env = {k: v for k, v in os.environ.items() if k.upper() in KEEP_ENV}
    env.update(BUDDIE_FETCH="0", BUDDIE_GITHUB="0", BUDDIE_LOG="0", BUDDIE_SHARED_LOG="0", BUDDIE_STATE="0",
               VERBATIM_STORE=str(cwd / "store"), CLAUDE_PLUGIN_ROOT=plugin.as_posix(), PYTHONIOENCODING="utf-8",
               **extra)
    return env


def _mcp(plugin: Path, cwd: Path, python: str, env: dict) -> tuple[list[dict], str]:
    server = json.loads((plugin / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["buddie"]
    args = [a.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin)) for a in server["args"]]
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "verify_report", "arguments": {
            "text": "CI passed. ⚓ `ci:octo/app@9653a7c=success`", "fetch": False, "github": False}}},
    ]
    out = subprocess.run([python, *args], cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8",
                         input="".join(json.dumps(m) + "\n" for m in messages), timeout=120)
    replies = [json.loads(line) for line in out.stdout.splitlines() if line.strip()]
    return replies, out.stdout + out.stderr


def check_mcp(plugin: Path, manifest: dict, python: str, tools: list[str]) -> list[str]:
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        for label, extra in (("no token", {}), ("a token", {"CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN": FAKE_TOKEN}),
                             ("a malformed token", {"CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN": BAD_TOKEN,
                                                    "BUDDIE_GITHUB_TOKEN": BAD_TOKEN})):
            try:
                replies, output = _mcp(plugin, cwd, python, _env(cwd, plugin, **extra))
            except (subprocess.TimeoutExpired, ValueError) as error:
                problems.append(f"MCP with {label}: {error}")
                continue
            if len(replies) != 3:
                problems.append(f"MCP with {label}: {len(replies)} replies, expected 3: {output[-400:]}")
                continue
            if replies[0].get("result", {}).get("serverInfo", {}).get("version") != manifest["version"]:
                problems.append(f"MCP with {label}: initialize does not report {manifest['version']}")
            listed = [t["name"] for t in replies[1].get("result", {}).get("tools", [])]
            if listed != tools:
                problems.append(f"MCP with {label}: tools/list is {listed}, expected {tools}")
            call = replies[2].get("result", {})
            if call.get("isError") or "outcome" not in json.dumps(call.get("structuredContent", {})):
                problems.append(f"MCP with {label}: verify_report did not return a receipt")
            for secret in (FAKE_TOKEN, BAD_TOKEN, "S" * 36):
                if secret in output:
                    problems.append(f"MCP with {label}: the token appears in the server's output")
    return problems


def check_hooks(plugin: Path) -> list[str]:
    sh = shutil.which("sh")
    if not sh:
        return ["no sh on PATH: the hooks (sh run.sh) cannot be checked here"]
    hooks = json.loads((plugin / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        env = _env(cwd, plugin)
        events = {"SessionStart": {"hook_event_name": "SessionStart", "cwd": str(cwd), "session_id": "smoke"},
                  "Stop": {"hook_event_name": "Stop", "cwd": str(cwd), "session_id": "smoke",
                           "last_assistant_message": "Ready for review."}}
        for event, payload in events.items():
            for group in hooks.get(event, []):
                for hook in group.get("hooks", []):
                    command = hook["command"].replace("${CLAUDE_PLUGIN_ROOT}", plugin.as_posix())
                    out = subprocess.run([sh, "-c", command], cwd=cwd, env=env, capture_output=True, text=True,
                                         encoding="utf-8", input=json.dumps(payload), timeout=120)
                    if out.returncode != 0:
                        problems.append(f"hook {event} exited {out.returncode}: {out.stderr[-400:]}")
    return problems


def check_config(plugin: Path) -> list[str]:
    option = json.loads((plugin / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))["userConfig"]
    token = option.get("github_token", {})
    if token.get("sensitive") is not True or token.get("required") is not False:
        return ["userConfig.github_token must stay optional and sensitive"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("plugin", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable, help="the interpreter .mcp.json's python3 resolves to")
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    sys.path.insert(0, str(ROOT))
    from buddie import mcp  # this checkout's tool list: the same commit the package was built from
    plugin = args.plugin.resolve()
    problems = check_files(plugin, manifest) + check_config(plugin)
    if not problems:
        problems += check_mcp(plugin, manifest, args.python, [t["name"] for t in mcp.TOOLS]) + check_hooks(plugin)
    for p in problems:
        print(f"smoke_plugin: {p}", file=sys.stderr)
    if not problems:
        print(f"smoke_plugin: {plugin}: {len(manifest['files'])} files as recorded; MCP, optional token and hooks ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
