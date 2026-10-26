"""BDX-001 Lite harness: replays recorded environments to an agent under three conditions (A: no diagnostics,
B: a fixed diagnostic-shell menu, C: buddie's environment_snapshot) and records what the agent did.

The harness consumes buddie as an observer, through what its adapters already produce (the CLI's recorded
diagnostics documents, mcp.TOOLS' schema, diagnostics.lines / problems / validate): nothing in buddie is changed or
registered, and buddie's verification-module registry is not touched (PR #54: observers are not verification modules).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]      # experiments/BDX-001-lite
REPO = ROOT.parents[1]                          # the buddie checkout
CONDITIONS = ("A", "B", "C")
BUDGET = 4                                      # diagnostic tool calls per run, B and C alike
MAX_ITEMS = 8                                   # commands (B) per call; C's own schema allows up to 32 categories
