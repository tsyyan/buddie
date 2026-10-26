"""Model-free measurement: how much text each diagnostic channel returns to deliver a scenario's relevant facts.

For every scenario and device, B's answer to its relevant commands and C's answer to its relevant categories
(ground_truth.json `relevant_sources`) are built by the harness router exactly as an agent would receive them, and
their sizes are recorded. Also the size of "everything" each channel can return (all menu commands; all categories
and catalog tools). Bytes are UTF-8 bytes of the tool result text; no tokenizer is assumed.

  python evaluation/context_cost.py > results/static/context_cost.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "harness"))
from bdx import fixtures, scenarios, tools  # noqa: E402

GT = json.loads((HERE / "ground_truth.json").read_text(encoding="utf-8"))["scenarios"]


def measure() -> dict:
    out = {}
    for sid, s in scenarios.load().items():
        rel = GT[sid]["relevant_sources"]
        rows = {}
        for device, b in s.bindings.items():
            rb = tools.Router(s, "B", "cost", budget=99)
            rc = tools.Router(s, "C", "cost", budget=99)
            tb, _ = rb.call("run_diagnostics", {"device": device, "commands": rel["B"]})
            tc, _ = rc.call("environment_snapshot", {"device": device, "categories": rel["C"]})
            rows[device] = {"env": b["env"],
                            "B_relevant": {"items": rel["B"], "bytes": len(tb.encode())},
                            "C_relevant": {"items": rel["C"], "bytes": len(tc.encode())}}
        out[sid] = rows
    everything = {}
    for env in fixtures.environments():
        menu = fixtures.menu()
        b_all = sum(len(fixtures.shell_text(env, menu[i:i + 8]).encode()) for i in range(0, len(menu), 8))
        full = fixtures.env(env)["buddie"]
        data, _ = fixtures.buddie_answer(env, {"categories": full["request"]["categories"],
                                               "tools": full["request"]["tools"]}, "0" * 32)
        everything[env] = {"B_all_commands_bytes": b_all,
                           "C_all_categories_bytes": len(fixtures.buddie_text(data, False).encode())}
    return {"per_scenario": out, "everything": everything,
            "note": "bytes of tool-result text as the agent receives it (device/collected_at envelope included)"}


if __name__ == "__main__":
    print(json.dumps(measure(), indent=1))
