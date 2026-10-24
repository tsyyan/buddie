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


def test_the_citation_date_is_the_changelogs_release_date_or_absent():
    """CITATION.cff's date-released belongs to its version: absent while the CHANGELOG section of this version says
    it is not released, and the same date as the section's once the release commit dates it (docs/release.md,
    "Cutting a release"). An earlier version's date would read as this one's."""
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    dated = re.search(r"^date-released: (\S+)", citation, re.M)
    head = re.search(rf"^## buddie {re.escape(__version__)} \(([^)]*)\)", (ROOT / "CHANGELOG.md").read_text(
        encoding="utf-8"), re.M)
    assert head, f"CHANGELOG.md has no section for {__version__}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", head[1]):
        assert dated and dated[1] == head[1], (head[1], dated and dated[1])
    else:
        assert "not released" in head[1] and dated is None, (head[1], dated and dated[1])
