"""manifest.json (the Claude Desktop bundle) agrees with the code: version, tools, entry point, ignored files."""
from __future__ import annotations

import json
from pathlib import Path

from buddie import __version__, mcp

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))


def test_version_and_tools_match_the_server():
    assert MANIFEST["version"] == __version__
    assert [t["name"] for t in MANIFEST["tools"]] == [t["name"] for t in mcp.TOOLS]


def test_entry_point_and_icon_ship_in_the_bundle():
    ignored = {line.strip().rstrip("/") for line in (ROOT / ".mcpbignore").read_text(encoding="utf-8").splitlines()
               if line.strip() and not line.startswith("#")}
    shipped = {MANIFEST["server"]["entry_point"], MANIFEST["icon"].split("/")[0], "buddie", "verbatim", "LICENSE"}
    assert not shipped & ignored
    assert (ROOT / MANIFEST["icon"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert "${__dirname}/run.py" in MANIFEST["server"]["mcp_config"]["args"]
