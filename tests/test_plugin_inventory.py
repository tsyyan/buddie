"""Inventory the actual committed plugin, including unwanted review surface."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_inventory_uses_committed_files_and_reports_inspection_limits(tmp_path):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    git("init", "-q")
    for path, data in {
        "run.py": b"print('hello')\n", "buddie/mcp.py": b"# local runtime\n",
        "PRIVACY.md": b"Privacy\n", "assets/icon.png": b"\x89PNG\r\n\x1a\n",
        "tests/test_fixture.py": b"# test\n", "scripts/tool.py": b"# dev\n",
        "results/large.json": b" " * 262145,
    }.items():
        dest = tmp_path / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    git("add", ".")
    git("-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
        "commit", "-qm", "fixture")
    (tmp_path / "untracked-secret.txt").write_text("not shipped", encoding="utf-8")
    def inventory(*args):
        return subprocess.run([sys.executable, str(ROOT / "scripts/plugin_inventory.py"), "--repo", str(tmp_path), *args],
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
    first, second = inventory(), inventory()
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    result = json.loads(first.stdout)
    rows = {row["path"]: row for row in result["files"]}
    assert set(rows) == {"run.py", "buddie/mcp.py", "PRIVACY.md", "assets/icon.png", "tests/test_fixture.py",
                         "scripts/tool.py", "results/large.json"}
    assert rows["run.py"]["category"] == "runtime-required"
    assert rows["PRIVACY.md"]["category"] == "documentation"
    assert rows["assets/icon.png"]["category"] == "assets"
    assert rows["tests/test_fixture.py"]["category"] == "tests"
    assert rows["scripts/tool.py"]["category"] == "development-only"
    assert rows["results/large.json"]["category"] == "experimental-results"
    assert result["inspection_holds"] == [{"path": "results/large.json", "reason": "non-image/font over 256 KiB"}]
    assert inventory("--check").returncode == 1
