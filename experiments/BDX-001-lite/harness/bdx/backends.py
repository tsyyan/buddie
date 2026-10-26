"""Model backends. Each takes one prepared run and returns what happened; none keeps state between runs.

claude-cli   `claude -p` (Claude Code headless), a fresh process in an empty temporary directory per run, with
             the default system prompt replaced, every built-in tool off, no settings sources (so no plugins, hooks
             or CLAUDE.md), no other MCP servers, no session persistence, and the run's own MCP server (B, C) as the
             only tool. The init event is checked against that: a run whose tool list differs is a harness failure.
             Uses the account the CLI is logged in with: it costs usage, so it runs only when asked to.
scripted     a fixed script of tool calls and a fixed answer, for the harness tests. Not a model; its runs are
             refused by the results writer.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from bdx import ROOT, tools

SERVER = ROOT / "harness" / "bdx" / "mcp_server.py"


class HarnessFailure(Exception):
    pass


HOST_CONTEXT = ("without --bare, claude -p attaches the host's environment block (platform, OS version, shell, "
                "working directory, today's date) and the account's e-mail to every conversation, even with "
                "--system-prompt (results/smoke/ENV_LEAK.md); --bare removes it but accepts only ANTHROPIC_API_KEY")


def claude_cli(run: dict, model: str, timeout: int = 900, max_turns: int = 12,
               allow_host_context: bool = False) -> dict:
    exe = shutil.which("claude")
    if exe is None:
        raise HarnessFailure("claude CLI not found on PATH")
    bare = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not bare and not allow_host_context:
        raise HarnessFailure(HOST_CONTEXT)
    cond, sid, rid = run["condition"], run["scenario"], run["run_id"]
    with tempfile.TemporaryDirectory(prefix="bdx-run-") as tmp:
        tmp = Path(tmp)
        log = tmp / "calls.jsonl"
        servers = {}
        allowed = []
        if cond in ("B", "C"):
            servers["diag"] = {"type": "stdio", "command": sys.executable,
                               "args": [str(SERVER), "--scenario", sid, "--condition", cond, "--run-id", rid,
                                        "--log", str(log)]}
            allowed = [f"mcp__diag__{t['name']}" for t in tools.specs(cond, run["_scenario"])]
        cfg = tmp / "mcp.json"
        cfg.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
        work = tmp / "work"
        work.mkdir()
        flags = ["-p", "--output-format", "stream-json", "--verbose", "--model", model,
                 "--system-prompt", run["prompts"]["system"], "--tools", "", "--strict-mcp-config",
                 "--mcp-config", str(cfg), "--setting-sources", "", "--disable-slash-commands",
                 "--no-session-persistence", "--max-turns", str(max_turns)] + (["--bare"] if bare else [])
        if allowed:
            flags += ["--allowedTools", ",".join(allowed)]
        env = {k: v for k, v in os.environ.items() if not k.startswith(("BUDDIE", "VERBATIM"))}
        started = time.time()
        proc = subprocess.run([exe, *flags], input=run["prompts"]["user"].encode("utf-8"), cwd=work,
                              capture_output=True, timeout=timeout, env=env)
        duration = time.time() - started
        events = []
        for line in proc.stdout.decode("utf-8", "replace").splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass
        calls = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    init_tools = sorted(init.get("tools") or [])
    servers_seen = sorted(s.get("name", "?") for s in init.get("mcp_servers") or [])
    isolation = {"init_tools": init_tools, "mcp_servers": servers_seen, "expected_tools": sorted(allowed),
                 "bare": bare, "host_context_injected": not bare,
                 "plugins": init.get("plugins"), "ok": init_tools == sorted(allowed)
                 and servers_seen == (["diag"] if allowed else [])}
    out = {"duration_s": round(duration, 3), "exit_code": proc.returncode,
           "stderr_tail": proc.stderr.decode("utf-8", "replace")[-2000:],
           "final_text": result.get("result"), "usage": result.get("usage"),
           "cost_usd": result.get("total_cost_usd"), "num_turns": result.get("num_turns"),
           "model_reported": init.get("model"), "cli_version": init.get("claude_code_version"),
           "isolation": isolation, "tool_calls": calls, "events": events,
           "flags": ["<prompts.system>" if f == run["prompts"]["system"] else f for f in flags]}
    if not init:
        raise HarnessFailure(f"no init event (exit {proc.returncode}): {out['stderr_tail'][-500:]}")
    if not isolation["ok"]:
        out["failure"] = "isolation_violation"
    elif result.get("subtype") != "success" or not result.get("result"):
        out["failure"] = f"no final answer ({result.get('subtype')})"
    return out


def scripted(run: dict, script: dict) -> dict:
    """script: {"calls": [[tool, args], ...], "answer": "..."}: calls the router directly, no model involved."""
    router = tools.Router(run["_scenario"], run["condition"], run["run_id"])
    started = time.time()
    for name, args in script.get("calls", []):
        router.call(name, args)
    return {"duration_s": round(time.time() - started, 3), "exit_code": 0, "final_text": script["answer"],
            "usage": None, "cost_usd": None, "num_turns": None, "model_reported": "scripted (not a model)",
            "cli_version": None, "isolation": {"ok": True, "scripted": True}, "tool_calls": router.calls,
            "events": [], "flags": []}
