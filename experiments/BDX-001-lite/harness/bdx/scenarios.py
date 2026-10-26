"""Agent-facing scenarios. This module never reads ../evaluation (ground truth stays out of the prompt path)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from bdx import ROOT

PATH = ROOT / "scenarios" / "scenarios.json"


@dataclass(frozen=True)
class Scenario:
    id: str
    category: str
    title: str
    today: str
    user_message: str
    devices: tuple
    bindings: dict = field(compare=False)      # device -> {"env", "mode"}: the tool router's, never rendered


def load() -> dict[str, Scenario]:
    raw = json.loads(PATH.read_text(encoding="utf-8"))
    out = {}
    for s in raw["scenarios"]:
        sc = Scenario(s["id"], s["category"], s["title"], s["today"], s["user_message"], tuple(s["devices"]),
                      s["bindings"])
        if set(sc.bindings) != set(sc.devices):
            raise ValueError(f"{sc.id}: bindings do not match devices")
        out[sc.id] = sc
    return out


def smoke() -> list[str]:
    return json.loads(PATH.read_text(encoding="utf-8"))["smoke"]
