"""The README is the landing page on GitHub and PyPI: its examples run and print what it shows, its links lead to
files that exist, and its badges and claims stay within what is true (PR #38)."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
EXAMPLE = re.compile(r"<!-- readme-example: (?P<name>[a-z]+) -->\n```bash\n(?P<cmds>.*?)```\n\n```\n(?P<out>.*?)```",
                     re.S)
COMMANDS = {"buddie": [sys.executable, "-m", "buddie"], "buddie-verbatim": [sys.executable, "-m", "buddie.verbatim.cli"]}


def _examples():
    found = {m["name"]: (m["cmds"].splitlines(), m["out"]) for m in EXAMPLE.finditer(README)}
    assert set(found) == {"quickstart", "work"}, found
    return found


@pytest.mark.parametrize("name", ["quickstart", "work"])
def test_the_readme_examples_print_what_the_readme_shows(name, tmp_path):
    """Each example's commands, run as written from a clone (`cd buddie/...` is the clone's directory), print exactly
    the output block under them, and the check exits 1 on FAIL."""
    cmds, out = _examples()[name]
    env = dict(os.environ, VERBATIM_STORE=str(tmp_path / "store"), BUDDIE_GITHUB="0", BUDDIE_FETCH="0",
               PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    cwd, printed, code = ROOT, "", None
    for cmd in cmds:
        word, *args = cmd.split(" ", 1)
        if word == "cd":
            cwd = ROOT / args[0].removeprefix("buddie/")
            continue
        argv = COMMANDS[word] + (args[0].split(" ") if args else [])
        p = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120,
                           stdin=subprocess.DEVNULL)
        printed, code = p.stdout, p.returncode
    assert printed == out, printed
    assert code == 1  # FAIL


def test_the_readme_links_lead_to_files_that_exist():
    missing = []
    for target in re.findall(r"\]\(([^)\s]+)\)", README):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        path = target.split("#", 1)[0]
        if path and not (ROOT / path).exists():
            missing.append(target)
    assert missing == []


def test_the_readme_anchors_lead_to_its_own_headings():
    slugs = {re.sub(r"[^\w\- ]", "", h.strip().lower()).replace(" ", "-") for h in re.findall(r"(?m)^#{2,3} (.+)$", README)}
    assert {a for a in re.findall(r"\]\(#([^)]+)\)", README)} <= slugs


def test_the_readme_carries_the_registry_name_and_honest_badges():
    assert "<!-- mcp-name: io.github.tsyyan/buddie -->" in README  # the MCP Registry checks it on PyPI
    badges = re.findall(r"\[!\[([^\]]+)\]\(([^)]+)\)\]\(([^)]+)\)", README)
    assert [b[0] for b in badges] == ["CI", "PyPI", "Python", "License", "Release", "MCP Registry", "Plugin"]
    # no scores, ratings, download counts or approval marks
    for label, image, _ in badges:
        assert not re.search(r"score|rating|rated|download|trust|verified|approved|official", image + label, re.I)


def test_the_opening_does_not_claim_truth():
    opening = README.split("## Why buddie exists", 1)[0]
    assert "verifies the evidence behind AI agent reports" in opening
    assert "does not tell whether an answer is true" in opening
    assert not re.search(r"(checks|verifies|proves) that what an AI agent tells you is true", README, re.I)
