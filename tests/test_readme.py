"""The README is the landing page on GitHub and PyPI: its examples run and print what it shows, its links lead to
files that exist, and its badges and claims stay within what is true (PR #38)."""
from __future__ import annotations

import json
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
               PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
               # the checkout's buddie, installed or not (CI's os job runs from a clone, as `python3 run.py` does)
               PYTHONPATH=os.pathsep.join(filter(None, [str(ROOT), os.environ.get("PYTHONPATH")])))
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
        assert p.returncode in (0, 1), p.stderr[-2000:]
    assert printed == out, printed
    assert code == 1  # FAIL


def test_the_receipt_excerpt_is_the_quickstarts_receipt(tmp_path):
    """The JSON shown under the quickstart is a subset of the receipt `--json` writes for it: every key and value
    shown is in the real one."""
    shown = json.loads(re.search(r"<!-- readme-receipt: quickstart -->\n```json\n(.*?)```", README, re.S)[1])
    env = dict(os.environ, VERBATIM_STORE=str(tmp_path / "store"), BUDDIE_GITHUB="0", BUDDIE_FETCH="0",
               PYTHONUTF8="1", PYTHONPATH=os.pathsep.join(filter(None, [str(ROOT), os.environ.get("PYTHONPATH")])))
    cwd = ROOT / "examples" / "quickstart"
    for argv in (COMMANDS["buddie-verbatim"] + ["add", "https://status.example.com/incidents/42", "page.html"],
                 COMMANDS["buddie"] + ["verify", "report.md", "--no-fetch", "--json", str(tmp_path / "r.json")]):
        subprocess.run(argv, cwd=cwd, env=env, capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
    real = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))

    def within(part, whole, at="$"):
        if isinstance(part, dict):
            for k, v in part.items():
                assert k in whole, f"{at}.{k} is not in the receipt"
                within(v, whole[k], f"{at}.{k}")
        elif isinstance(part, list):
            for i, v in enumerate(part):
                within(v, whole[i], f"{at}[{i}]")
        else:
            assert part == whole, (at, part, whole)
    within(shown, real)


def test_the_readme_names_the_mcp_tools_the_servers_list():
    from buddie import mcp, remote
    table = README.split("## MCP tools", 1)[1].split("\n## ", 1)[0]
    named = re.findall(r"(?m)^\| `([a-z_]+)` \|", table)
    assert named == [t["name"] for t in mcp.TOOLS]  # every stdio server
    assert [t["name"] for t in remote.tools()] == named[:3]  # "the remote server has the first three"


def _changelog_versions():
    heads = re.findall(r"(?m)^## buddie (\d+\.\d+\.\d+) \(([^)]*)\)", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    released = [v for v, when in heads if re.match(r"\d{4}-\d{2}-\d{2}", when)]
    return released[0], [v for v, when in heads if "not released" in when]


def test_the_readme_names_the_released_and_the_described_versions():
    """The README's release status tells apart the version people install from the registries and the one it
    describes, in words that hold before and after this branch merges; a release has to update it (docs/release.md,
    cutting a release)."""
    import buddie
    released, prepared = _changelog_versions()
    status = README.split("## Release status", 1)[1].split("\n## ", 1)[0]
    assert f"| **{released}** |" in status
    if buddie.__version__ in prepared:
        assert f"| **{buddie.__version__}**, prepared, not yet released |" in status
    else:
        assert buddie.__version__ == released
    # no claim about which branch holds what, which a merge would make false
    assert not re.search(r"\bmain\b|PR #\d", status), "names a branch's or PR's state"
    for where in ("Claude Desktop", "Any MCP client"):
        section = README.split(f"### {where}", 1)[1].split("\n### ", 1)[0]
        assert f"({released} today)" in section, where


def test_the_install_commands_match_the_manifests():
    market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    plugin = f"{market['plugins'][0]['name']}@{market['name']}"
    assert f"/plugin install {plugin}" in README and f"claude plugin install {plugin}" in README
    assert f"codex plugin add {plugin}" in README
    assert "/plugin marketplace add tsyyan/buddie" in README and "codex plugin marketplace add tsyyan/buddie" in README
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))["packages"][0]
    args = " ".join(a["value"] for a in server["packageArguments"])
    assert f"{server['runtimeHint']} {server['identifier']} {args}" == "uvx buddie serve" and "uvx buddie serve" in README
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'(?m)^name = "buddie"$', project) and "pip install buddie" in README
    assert (ROOT / "run.py").is_file() and "python3 run.py verify REPORT.md --repo ." in README


def test_the_cli_flags_commands_and_subcommands_the_readme_names_exist():
    out = subprocess.run(COMMANDS["buddie"] + ["verify", "--help"], capture_output=True, text=True, timeout=60,
                         stdin=subprocess.DEVNULL, cwd=ROOT).stdout
    flags = set(re.findall(r"`[^`]*?(--[a-z][a-z-]+)", README)) - {"--scope"}
    assert flags and flags <= set(re.findall(r"--[a-z][a-z-]+", out)), flags - set(re.findall(r"--[a-z-]+", out))
    top = subprocess.run(COMMANDS["buddie"] + ["--help"], capture_output=True, text=True, timeout=60,
                         stdin=subprocess.DEVNULL, cwd=ROOT).stdout
    for sub in re.findall(r"`buddie ([a-z]+)", README):
        assert re.search(rf"(?m)^\s+{sub}\b", top), sub
    for command in re.findall(r"`/buddie:([a-z]+)`", README):
        assert (ROOT / "commands" / f"{command}.md").is_file(), command


def _slug(heading: str) -> str:
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def test_the_readme_links_lead_to_files_and_headings_that_exist():
    missing = []
    for target in re.findall(r"\]\(([^)\s]+)\)", README):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        path, _, anchor = target.partition("#")
        file = ROOT / path if path else ROOT / "README.md"
        if not file.exists():
            missing.append(target)
        elif anchor and file.suffix == ".md":
            heads = re.findall(r"(?m)^#{1,4} (.+)$", file.read_text(encoding="utf-8"))
            if anchor not in {_slug(h) for h in heads}:
                missing.append(target)
    assert missing == []


def test_the_readme_carries_the_registry_name_and_honest_badges():
    assert "<!-- mcp-name: io.github.tsyyan/buddie -->" in README  # the MCP Registry checks it on PyPI
    badges = re.findall(r"\[!\[([^\]]+)\]\(([^)]+)\)\]\(([^)]+)\)", README)
    assert [b[0] for b in badges] == ["CI", "PyPI", "Python", "License", "Release", "MCP Registry"]
    expected = {"CI": ("github.com/tsyyan/buddie/actions/workflows/ci.yml/badge.svg", "actions/workflows/ci.yml"),
                "PyPI": ("img.shields.io/pypi/v/buddie", "pypi.org/project/buddie"),
                "Python": ("img.shields.io/pypi/pyversions/buddie", "pypi.org/project/buddie"),
                "License": ("img.shields.io/github/license/tsyyan/buddie", "LICENSE"),
                "Release": ("img.shields.io/github/v/release/tsyyan/buddie", "github.com/tsyyan/buddie/releases"),
                "MCP Registry": ("registry.modelcontextprotocol.io%2Fv0%2Fservers%2Fio.github.tsyyan",
                                 "registry.modelcontextprotocol.io/v0/servers/io.github.tsyyan")}
    for label, image, target in badges:
        assert expected[label][0] in image and expected[label][1] in target, label
        # no scores, ratings, download counts or approval marks
        assert not re.search(r"score|rating|rated|download|trust|verified|approved|official", image + label, re.I)


def test_the_readme_claims_no_more_than_buddie_does():
    opening = README.split("## See it work", 1)[0]
    assert "**buddie verifies the evidence behind AI agent reports.**" in opening
    assert "No language model takes part in the check" in opening
    assert not re.search(r"(checks|verifies|proves) that what an AI agent tells you is true", README, re.I)
    # a receipt is re-checkable while its evidence lasts, not re-runnable into the same verdict forever
    assert not re.search(r"anyone can re-?run|always reproduc", README, re.I)
    assert "reproduces the verdict only while that evidence is unchanged" in README
    limits = README.split("## Limitations", 1)[1].split("\n## ", 1)[0]
    for must in ("not a truth detector", "`PASS` is scoped", "`GAPS` is not success", "Evidence ages",
                 "Advice is advice", "The gate covers what the client sends it", "The gate is not a lock",
                 "Local evidence is local", "A receipt is an evidence record"):
        assert must in limits, must
    assert "not listed in Anthropic's plugin directory yet" in README
    assert not re.search(r"(approved|listed|available) (in|on|by) Anthropic", README.replace("not listed in", ""))
    # every (2.0) feature is in this version's code
    import buddie
    from buddie import freshness, environment, policy, profiles, receipts  # noqa: F401
    assert receipts.version_of("v1") and buddie.__version__.startswith("2.")
