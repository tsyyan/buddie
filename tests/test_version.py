"""One version everywhere: buddie/__init__.py is the source; pyproject, CITATION.cff and the three manifests
(Claude Code plugin, Codex plugin, Claude Desktop bundle) follow it.

The lab export used to write these lines (NEXT №91); since this repository is the source, the check lives here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from buddie import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_one_version_everywhere():
    pyproject = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    citation = re.search(r"^version: (\S+)", (ROOT / "CITATION.cff").read_text(encoding="utf-8"), re.M)
    found = {"pyproject": pyproject[1], "citation": citation[1]}
    for name in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", "manifest.json",
                 "integrations/chatgpt/plugin.json"):
        found[name] = json.loads((ROOT / name).read_text(encoding="utf-8"))["version"]
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    found["server.json"], found["server.json package"] = server["version"], server["packages"][0]["version"]
    assert found == dict.fromkeys(found, __version__)


def test_readme_names_the_registry_entry():
    """registry.modelcontextprotocol.io accepts server.json only when the PyPI README (ours) carries its name."""
    name = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))["name"]
    assert f"mcp-name: {name}" in (ROOT / "README.md").read_text(encoding="utf-8")
