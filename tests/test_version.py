"""One version everywhere: buddie/__init__.py is the source, the plugin manifest, pyproject and CITATION.cff follow it.

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
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    assert {"pyproject": pyproject[1], "citation": citation[1], "plugin": plugin} == dict.fromkeys(
        ("pyproject", "citation", "plugin"), __version__)
