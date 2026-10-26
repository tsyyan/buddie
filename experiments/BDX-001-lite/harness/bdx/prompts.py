"""Prompts: one base instruction for every condition, plus one paragraph naming the condition's tool."""
from __future__ import annotations

from bdx import BUDGET
from bdx.scenarios import Scenario

BASE = """You are a technical assistant helping a user with a problem on their own computer. Give the user concrete \
instructions they can follow on their machine. If you need information from the user before you can give \
instructions that will work for them, you may ask instead. Today's date is {today}.

{tools}

End your answer with a fenced code block tagged `result` that holds one JSON object:
{{"outcome": "recommendation" or "clarification",
  "commands": [the exact commands you want the user to run, in order; [] if none],
  "environment_facts": [{{"fact": "...", "source": "observed" | "user" | "assumed"}}, ...],
  "question": "your question to the user, or null"}}"""

TOOLS = {
    "A": "You have no tools for inspecting the user's computer.",
    "B": "You can run diagnostic commands on the user's device with the run_diagnostics tool (a fixed list of "
         "read-only commands). The user's devices: {devices}. You may call the tool at most {budget} times.",
    "C": "You can request environment observations of the user's device with the environment_snapshot tool "
         "(buddie). The user's devices: {devices}. You may call the tool at most {budget} times.",
}


def system(condition: str, s: Scenario) -> str:
    tools = TOOLS[condition].format(devices=", ".join(s.devices), budget=BUDGET)
    return BASE.format(today=s.today, tools=tools)


def user(s: Scenario) -> str:
    return s.user_message
