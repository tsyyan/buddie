"""Tool-response routing: each call is answered from the right device's recording, within the budget."""
import json
import subprocess
import sys

import pytest

from bdx import BUDGET, ROOT, fixtures, scenarios, tools
from buddie import diagnostics

SC = scenarios.load()


def router(sid, cond):
    return tools.Router(SC[sid], cond, f"{sid}-{cond}-test")


def test_shell_answer_is_the_recorded_output():
    r = router("HW-2", "B")
    text, err = r.call("run_diagnostics", {"device": "device-1", "commands": ["cat /sys/fs/cgroup/memory.max",
                                                                              "free -b"]})
    assert not err
    assert "$ cat /sys/fs/cgroup/memory.max\n2147483648\n[exit code: 0]" in text
    assert "free: command not found" in text and "[exit code: 127]" in text
    assert text.startswith("device: device-1\ncollected_at: 2026-10-26T")
    assert r.calls[0]["items"] == ["cat /sys/fs/cgroup/memory.max", "free -b"]


def test_shell_refuses_commands_outside_the_menu():
    r = router("OS-1", "B")
    _, err = r.call("run_diagnostics", {"device": "device-1", "commands": ["Remove-Item -Recurse C:\\"]})
    assert err


@pytest.mark.parametrize("cond,name,args", [
    ("B", "run_diagnostics", {"device": "device-1", "commands": ["hostname"]}),
    ("C", "environment_snapshot", {"device": "device-1", "categories": ["system.os"]}),
])
def test_budget_is_the_same_for_b_and_c(cond, name, args):
    r = router("CTX-3", cond)
    results = [r.call(name, args) for _ in range(BUDGET + 1)]
    assert [e for _, e in results] == [False] * BUDGET + [True]
    assert "budget exhausted" in results[-1][0]


def test_wrong_tool_and_wrong_device():
    r = router("OS-1", "C")
    assert r.call("run_diagnostics", {"device": "device-1", "commands": ["hostname"]})[1]
    assert r.call("environment_snapshot", {"device": "device-9", "categories": ["system.os"]})[1]


def test_buddie_answer_is_a_consistent_narrower_document():
    data, err = fixtures.buddie_answer("linux-container-2g", {"categories": ["hardware.memory", "system.os"],
                                                              "task": "check RAM"}, "0" * 32)
    assert not err and diagnostics.problems(data) == []
    assert list(data["categories"]) == ["system.os", "hardware.memory"]
    full = fixtures.env("linux-container-2g")["buddie"]
    assert data["categories"]["hardware.memory"] == full["categories"]["hardware.memory"]
    assert data["supplied"] == {"task": "check RAM"}
    assert data["authorization"]["effective"] == ["hardware.memory", "system.os"]


def test_buddie_tools_filter_and_rejections():
    data, err = fixtures.buddie_answer("linux-x64", {"categories": ["software.tools", "nonsense.cat"],
                                                     "tools": ["jq", "ffmpeg", "notatool"]}, "0" * 32)
    assert not err and diagnostics.problems(data) == []
    obs = data["categories"]["software.tools"]["observations"]
    assert set(obs) == {"jq", "ffmpeg", "notatool"}
    assert obs["jq"]["value"] == "1.7" and obs["notatool"]["reason"] == "not_in_catalog"
    assert data["request"]["rejected"][0]["reason"] == "unknown_category"
    none, _ = fixtures.buddie_answer("linux-x64", {"categories": ["software.tools"]}, "0" * 32)
    assert none["categories"]["software.tools"]["reason"] == "no_tools_given"


def test_buddie_errors_and_list_follow_the_adapter():
    assert fixtures.buddie_answer("win-laptop", {"consent": True, "categories": ["system.os"]}, "0" * 32)[1]
    assert fixtures.buddie_answer("win-laptop", {"categories": []}, "0" * 32)[1]
    cat, err = fixtures.buddie_answer("win-laptop", {"list": True}, "0" * 32)
    assert not err and cat["platform"] == "windows"


def test_all_categories_reproduce_the_recording():
    for env in fixtures.environments():
        full = fixtures.env(env)["buddie"]
        data, _ = fixtures.buddie_answer(env, {"categories": list(full["request"]["categories"]),
                                               "tools": full["request"]["tools"]}, full["request"]["id"])
        assert data["categories"] == full["categories"]
        assert data["authorization"] == full["authorization"]


def test_two_devices_route_separately():
    r = router("CTX-1", "C")
    t1, _ = r.call("environment_snapshot", {"device": "device-1", "categories": ["system.os"]})
    t2, _ = r.call("environment_snapshot", {"device": "device-2", "categories": ["system.os"]})
    assert "Windows 11" in t1 and "Ubuntu" not in t1
    assert "Ubuntu" in t2 and "Windows" not in t2


def test_cached_scenario_carries_the_collection_time():
    r = router("CTX-2", "C")
    text, _ = r.call("environment_snapshot", {"device": "device-1", "categories": ["software.runtimes"]})
    assert "collected_at: 2026-10-26T" in text and "24.19.0" in text
    assert SC["CTX-2"].today == "2026-12-14"


def test_text_matches_buddies_mcp_rendering():
    data, err = fixtures.buddie_answer("win-laptop", {"categories": ["system.os"]}, "0" * 32)
    text = fixtures.buddie_text(data, err)
    assert text.splitlines()[0].startswith("buddie snapshot: diagnostics of 1 categor")
    assert json.loads(text[text.index("\n{") + 1:]) == data


def test_mcp_server_stdio_roundtrip(tmp_path):
    log = tmp_path / "calls.jsonl"
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "environment_snapshot",
                        "arguments": {"device": "device-1", "categories": ["hardware.memory"]}}}]
    proc = subprocess.run([sys.executable, str(ROOT / "harness" / "bdx" / "mcp_server.py"), "--scenario", "HW-2",
                           "--condition", "C", "--run-id", "t", "--log", str(log)],
                          input="\n".join(json.dumps(m) for m in msgs).encode(), capture_output=True, timeout=60)
    replies = [json.loads(x) for x in proc.stdout.decode().splitlines()]
    assert [r["id"] for r in replies] == [1, 2, 3]
    assert replies[1]["result"]["tools"][0]["name"] == "environment_snapshot"
    assert "2147483648" in replies[2]["result"]["content"][0]["text"]
    logged = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert logged[0]["items"] == ["hardware.memory"] and logged[0]["counted"]
