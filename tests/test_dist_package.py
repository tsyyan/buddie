"""scripts/dist_package.py: one root for Claude Code, Codex, Gemini CLI and Copilot CLI, no shared hook file."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import dist_package as dp  # noqa: E402

pytestmark = pytest.mark.skipif(subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                               capture_output=True).returncode != 0, reason="needs the git checkout")


@pytest.fixture(scope="module")
def built():
    return dp.build(ROOT, "HEAD")


def test_every_client_has_its_manifest_and_one_version(built):
    _, manifest, files = built
    v = manifest["version"]
    for path in dp.VERSIONED:
        assert json.loads(files[path])["version"] == v, path
    assert set(dp.SOURCES.values()) <= set(files)


def test_no_hook_file_at_the_path_three_clients_read(built):
    _, _, files = built
    assert "hooks/hooks.json" not in files
    assert json.loads(files[".claude-plugin/plugin.json"])["hooks"] == "./hooks/claude-code.json"
    assert set(json.loads(files["hooks/claude-code.json"])["hooks"]) >= {"Stop", "PreToolUse", "SessionStart"}
    assert json.loads(files[".codex-plugin/plugin.json"])["hooks"] == "./hooks/codex.json"
    assert "${PLUGIN_ROOT}" in files["hooks/codex.json"].decode()


def test_gemini_and_copilot_start_the_packaged_server(built):
    _, _, files = built
    gem = json.loads(files["gemini-extension.json"])
    assert gem["mcpServers"]["buddie"]["args"][-2:] == ["${extensionPath}${/}run.py", "serve"]
    assert gem["contextFileName"] in files
    cop = json.loads(files[".github/plugin/plugin.json"])
    assert cop["mcpServers"]["buddie"]["args"][-2:] == ["${PLUGIN_ROOT}/run.py", "serve"]


def test_the_package_is_the_same_bytes_twice(built):
    data, manifest, _ = built
    assert dp.build(ROOT, "HEAD")[0] == data and manifest["package"]["size"] == len(data)
