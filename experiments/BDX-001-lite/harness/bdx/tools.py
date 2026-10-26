"""The diagnostic tool of each condition, and the router that answers its calls from the recordings.

B and C get the same budget (BUDGET calls), the same `device` argument and the same envelope (device, collection
time). C's name, description and other arguments are buddie's own (mcp.TOOLS); the `device` argument and the
one-line remote preface are the harness's, since a remote observer would need them.
"""
from __future__ import annotations

import copy
import time

from bdx import BUDGET, MAX_ITEMS, fixtures
from bdx.scenarios import Scenario

SHELL_TOOL = "run_diagnostics"
BUDDIE_TOOL = "environment_snapshot"


def _device_schema(s: Scenario) -> dict:
    return {"type": "string", "enum": list(s.devices),
            "description": "which of the user's devices to observe"}


def specs(condition: str, s: Scenario) -> list[dict]:
    """[{name, description, input_schema}] for the condition (none for A)."""
    if condition == "A":
        return []
    if condition == "B":
        return [{
            "name": SHELL_TOOL,
            "description": "Runs read-only diagnostic commands on the user's device, in that device's default shell, "
                           "and returns each command's output and exit code. Only the listed commands are available.",
            "input_schema": {"type": "object", "additionalProperties": False, "required": ["device", "commands"],
                             "properties": {
                                 "device": _device_schema(s),
                                 "commands": {"type": "array", "minItems": 1, "maxItems": MAX_ITEMS,
                                              "items": {"type": "string", "enum": fixtures.menu()}}}},
        }]
    real = next(t for t in fixtures.mcp.TOOLS if t["name"] == BUDDIE_TOOL)
    schema = copy.deepcopy(real["inputSchema"])
    schema["properties"] = {"device": _device_schema(s), **schema["properties"]}
    schema["required"] = ["device"]
    return [{"name": BUDDIE_TOOL,
             "description": "Runs buddie on the user's device (chosen with `device`). " + real["description"],
             "input_schema": schema}]


class Router:
    """Answers one run's diagnostic calls and keeps the log the run record is made from."""

    def __init__(self, scenario: Scenario, condition: str, run_id: str, budget: int = BUDGET):
        self.s, self.condition, self.run_id, self.budget = scenario, condition, run_id, budget
        self.calls: list[dict] = []

    def call(self, name: str, args: dict) -> tuple[str, bool]:
        n = len(self.calls) + 1
        started = time.time()
        text, is_error, info = self._answer(name, args, n)
        self.calls.append({"n": n, "tool": name, "arguments": args, "is_error": is_error,
                           "response_text": text, "response_bytes": len(text.encode("utf-8")), **info,
                           "elapsed_s": round(time.time() - started, 4)})
        return text, is_error

    def _answer(self, name: str, args: dict, n: int) -> tuple[str, bool, dict]:
        expected = {"B": SHELL_TOOL, "C": BUDDIE_TOOL}.get(self.condition)
        if name != expected:
            return f"unknown tool {name}", True, {"counted": False}
        if n > self.budget:
            return (f"diagnostic budget exhausted: at most {self.budget} calls per conversation", True,
                    {"counted": False})
        args = dict(args or {})
        device = args.pop("device", None)
        if device not in self.s.devices:
            return f"device: one of {', '.join(self.s.devices)}", True, {"counted": True}
        binding = self.s.bindings[device]
        meta = fixtures.env(binding["env"])["meta"]
        head = f"device: {device}\ncollected_at: {meta['collected_at']}\n\n"
        if self.condition == "B":
            cmds = args.get("commands")
            if set(args) != {"commands"} or not isinstance(cmds, list) or not cmds or len(cmds) > 8 \
                    or any(c not in fixtures.menu() for c in cmds):
                return ("commands: 1 to 8 entries from the listed commands, and nothing else", True,
                        {"counted": True, "items": cmds if isinstance(cmds, list) else None})
            return head + fixtures.shell_text(binding["env"], cmds), False, {"counted": True, "items": cmds}
        data, is_error = fixtures.buddie_answer(binding["env"], args, fixtures.request_id(self.run_id, n))
        items = None if is_error or args.get("list") else list(data["categories"])
        return (head if not is_error else "") + fixtures.buddie_text(data, is_error), is_error, \
            {"counted": True, "items": items, "list": bool(args.get("list"))}
