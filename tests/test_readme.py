"""The README is the landing page on GitHub and PyPI, and three pages carry what it leaves out: the verification guide
(docs/verification.md), every install (docs/getting-started.md) and the limits (docs/limitations.md). Their examples
run and print what they show, their links and images lead to files that exist, the demos agree with real output, and
their badges and claims stay within what is true (PR #38)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
VERIFICATION = (ROOT / "docs" / "verification.md").read_text(encoding="utf-8")
GETTING = (ROOT / "docs" / "getting-started.md").read_text(encoding="utf-8")
LIMITS = (ROOT / "docs" / "limitations.md").read_text(encoding="utf-8")
PAGES = {"README.md": README, "docs/verification.md": VERIFICATION, "docs/getting-started.md": GETTING,
         "docs/limitations.md": LIMITS}
EXAMPLE = re.compile(r"<!-- (?:readme|doc)-example: (?P<name>[a-z]+) -->\n```bash\n(?P<cmds>.*?)```\n\n```\n(?P<out>.*?)```",
                     re.S)
COMMANDS = {"buddie": [sys.executable, "-m", "buddie"], "buddie-verbatim": [sys.executable, "-m", "buddie.verbatim.cli"]}


def _env(tmp_path, **extra):
    return dict(os.environ, VERBATIM_STORE=str(tmp_path / "store"), BUDDIE_GITHUB="0", BUDDIE_FETCH="0",
                PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
                # the checkout's buddie, installed or not (CI's os job runs from a clone, as `python3 run.py` does)
                PYTHONPATH=os.pathsep.join(filter(None, [str(ROOT), os.environ.get("PYTHONPATH")])), **extra)


def _section(text: str, heading: str) -> str:
    return text.split(f"\n{heading}\n", 1)[1].split("\n## ", 1)[0]


def _examples():
    found = {(page, m["name"]): (m["cmds"].splitlines(), m["out"]) for page, text in PAGES.items()
             for m in EXAMPLE.finditer(text)}
    assert set(found) == {("README.md", "work"), ("docs/verification.md", "quickstart"),
                          ("docs/verification.md", "work")}, set(found)
    return found


@pytest.mark.parametrize("page,name", [("README.md", "work"), ("docs/verification.md", "quickstart"),
                                       ("docs/verification.md", "work")])
def test_the_examples_print_what_the_pages_show(page, name, tmp_path):
    """Each example's commands, run as written from a clone (`cd buddie/...` is the clone's directory), print exactly
    the output block under them, and the check exits 1 on FAIL."""
    cmds, out = _examples()[(page, name)]
    env = _env(tmp_path)
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


def test_the_readme_verification_card_shows_the_real_runs_words():
    """The card above the README's work example says only what that example prints, and its alt text and SVG
    description say the same."""
    _, out = _examples()[("README.md", "work")]
    svg = (ROOT / "assets/demo/verification.svg").read_text(encoding="utf-8")
    for words in ("run:pytest -q => 41 passed", "1 failed, 40 passed in 3.1s", "effects 0/1 hold, 1 broken"):
        assert words in out, words
        assert words.replace(">", "&gt;") in svg, words
        assert words in _alt("assets/demo/verification.svg"), words
    assert "FAIL" in svg and "exit 1" in svg
    report = (ROOT / "examples/work/report.md").read_text(encoding="utf-8")
    assert "Fixed the date parser; the test suite is green" in report and "the test suite is green" in svg


def test_the_receipt_excerpt_is_the_quickstarts_receipt(tmp_path):
    """The JSON shown under the quickstart is a subset of the receipt `--json` writes for it: every key and value
    shown is in the real one."""
    shown = json.loads(re.search(r"<!-- doc-receipt: quickstart -->\n```json\n(.*?)```", VERIFICATION, re.S)[1])
    env = _env(tmp_path)
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


def _diagnostics_demo():
    m = re.search(r"<!-- readme-diagnostics -->\n```bash\n(?P<cmd>.*?)\n```\n\n```\n(?P<out>.*?)```", README, re.S)
    return m["cmd"], m["out"].splitlines()


def _readme_grants(tmp_path) -> Path:
    toml = re.search(r"<!-- readme-grants -->\n```toml\n(.*?)```", README, re.S)[1]
    home = tmp_path / "config"
    (home / "buddie").mkdir(parents=True)
    (home / "buddie" / "environment.toml").write_text(toml, encoding="utf-8")
    return home


def test_the_readme_grants_file_grants_exactly_the_demos_categories(tmp_path):
    from buddie import diagnostics
    home = _readme_grants(tmp_path)
    grants = diagnostics.load_grants(home / "buddie" / "environment.toml")
    cmd, _ = _diagnostics_demo()
    assert grants.status == "active" and grants.roots == ()
    assert grants.allow == set(re.findall(r"--category ([a-z_.]+)", cmd)) == {"system.os", "hardware.gpu",
                                                                              "software.python"}


def test_the_readme_diagnostics_demo_runs_and_is_shaped_as_buddie_prints_it(tmp_path):
    """The demo's command, run here with the README's grants, exits 0 and prints the same header and categories. The
    observed values are one machine's and are not compared; the excerpt's lines have the shape `diagnostics.lines`
    prints, under categories that exist, with bases buddie records."""
    from buddie import diagnostics, probes
    cmd, shown = _diagnostics_demo()
    home = _readme_grants(tmp_path)
    args = [a.strip('"') for a in re.findall(r'"[^"]*"|\S+', cmd)]
    assert args[:2] == ["buddie", "snapshot"]
    args[args.index("--json") + 1] = str(tmp_path / "diagnostics.json")
    env = _env(tmp_path, APPDATA=str(home), XDG_CONFIG_HOME=str(home))
    p = subprocess.run(COMMANDS["buddie"] + args[1:], cwd=tmp_path, env=env, capture_output=True, text=True,
                       encoding="utf-8", timeout=120, stdin=subprocess.DEVNULL)
    assert p.returncode == 0, p.stderr[-2000:]
    printed = p.stdout.splitlines()
    doc = json.loads((tmp_path / "diagnostics.json").read_text(encoding="utf-8"))
    assert diagnostics.problems(doc) == [] and doc["supplied"]["task"] == "configure local development environment"
    if doc["authorization"]["policy"] == "absent":  # a protected policy on this machine changes the header's words
        assert printed[0] == shown[0]
    categories = [ln.strip().split(":")[0] for ln in shown if re.match(r"^  [a-z]", ln)]
    assert categories == doc["request"]["categories"] == ["system.os", "hardware.gpu", "software.python"]
    assert all(f"  {c}: " in "\n".join(printed) for c in categories)
    current = None
    for line in shown[1:]:
        if m := re.match(r"^  ([a-z_.]+): collected$", line):
            current = m[1]
            continue
        m = re.match(r"^    ([a-z_]+): .+  \[([a-z_]+)\]$", line)
        assert m and m[2] in probes.BASES, line
        assert m[1] in diagnostics.REGISTRY[current].observations, line
    assert "buddie_runtime" in doc["categories"]["software.python"]["observations"]
    assert "name" in doc["categories"]["system.os"]["observations"]


def test_the_readme_diagnostics_card_shows_the_excerpts_values():
    _, shown = _diagnostics_demo()
    excerpt = "\n".join(shown)
    svg = (ROOT / "assets/demo/environment.svg").read_text(encoding="utf-8")
    alt = _alt("assets/demo/environment.svg")
    for value in ("Windows 11", "NVIDIA GeForce GTX 1650", "3.14.6", "os_interface", "fixed_program", "[buddie]"):
        assert value in excerpt, value
        assert value.strip("[]") in svg and value.strip("[]") in alt, value
    assert "vram_bytes 4294967296" in excerpt and "4 GiB" in svg  # 4294967296 bytes is 4 GiB
    for category in ("system.os", "hardware.gpu", "software.python"):
        assert category in svg and category in alt


def test_the_mcp_tools_table_names_the_tools_the_servers_list():
    from buddie import mcp, remote
    table = _section(GETTING, "## MCP tools")
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
    cutting a release). While the described version is unreleased, the README says what the registries give instead
    and how to get the described one."""
    import buddie
    released, prepared = _changelog_versions()
    status = _section(README, "### Release status")
    assert f"| **{released}** |" in status
    if buddie.__version__ in prepared:
        assert f"| **{buddie.__version__}**, prepared, not yet released |" in status
        assert f"give {released}" in status and "pip install git+https://github.com/tsyyan/buddie" in status
    else:
        assert buddie.__version__ == released and "not yet released" not in README
    # no claim about which branch holds what, which a merge would make false
    assert not re.search(r"\bmain\b|PR #\d", status), "names a branch's or PR's state"
    assert not re.search(r"(?<!until )\b2\.0(\.0)? (is|has been) (released|published|available)", README, re.I)
    for where in ("Claude Desktop", "Any MCP client"):
        section = GETTING.split(f"### {where}", 1)[1].split("\n### ", 1)[0]
        assert f"({released} today)" in section, where


def test_the_install_commands_match_the_manifests():
    market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    plugin = f"{market['plugins'][0]['name']}@{market['name']}"
    for text in (README, GETTING):
        assert f"/plugin install {plugin}" in text and f"codex plugin add {plugin}" in text
        assert "/plugin marketplace add tsyyan/buddie" in text and "codex plugin marketplace add tsyyan/buddie" in text
    assert f"claude plugin install {plugin}" in GETTING
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))["packages"][0]
    args = " ".join(a["value"] for a in server["packageArguments"])
    assert f"{server['runtimeHint']} {server['identifier']} {args}" == "uvx buddie serve"
    assert "uvx buddie serve" in README and "uvx buddie serve" in GETTING
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'(?m)^name = "buddie"$', project) and "pip install buddie" in README
    assert re.search(r'(?m)^requires-python = ">=3\.11"$', project) and "Python 3.11 or newer" in README
    assert (ROOT / "run.py").is_file() and "python3 run.py verify REPORT.md --repo ." in GETTING
    # the grants file the README names is the one buddie reads
    from buddie import diagnostics
    assert diagnostics.grants_location().name == "environment.toml" and "`environment.toml`" in README
    assert "~/.config/buddie/" in README and "%APPDATA%\\buddie\\" in README


def _help(*sub) -> str:
    return subprocess.run(COMMANDS["buddie"] + [*sub, "--help"], capture_output=True, text=True, timeout=60,
                          stdin=subprocess.DEVNULL, cwd=ROOT).stdout


def test_the_cli_flags_commands_and_subcommands_the_pages_name_exist():
    text = "\n".join(PAGES.values())
    verify_flags = set(re.findall(r"--[a-z][a-z-]+", _help("verify")))
    snapshot_flags = set(re.findall(r"--[a-z][a-z-]+", _help("snapshot")))
    # a flag in a command line belongs to that subcommand; a flag in a code span elsewhere to `buddie verify`
    for sub, flags in (("verify", verify_flags), ("snapshot", snapshot_flags)):
        for line in re.findall(rf"(?m)buddie {sub}( [^`\n]*)", text):
            used = set(re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", line))
            assert used <= flags, (sub, used - flags)
    spans = set(re.findall(r"`[^`]*?(--[a-z][a-z-]+)", re.sub(r"`buddie snapshot[^`]*`", "", text))) - {"--scope"}
    assert spans and spans <= verify_flags | snapshot_flags, spans - verify_flags - snapshot_flags
    top = _help()
    blocks = "\n".join(re.findall(r"(?ms)^```[a-z]*\n(.*?)^```$", text))
    for sub in re.findall(r"`buddie ([a-z]+)", text) + re.findall(r"(?m)^buddie ([a-z]+)", blocks):
        assert re.search(rf"(?m)^\s+{sub}\b", top), sub
    for command in re.findall(r"`/buddie:([a-z]+)`", text):
        assert (ROOT / "commands" / f"{command}.md").is_file(), command


def _slug(heading: str) -> str:
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


@pytest.mark.parametrize("page", list(PAGES))
def test_the_links_lead_to_files_and_headings_that_exist(page):
    base = (ROOT / page).parent
    text = PAGES[page]
    missing = []
    for target in re.findall(r"\]\(([^)\s]+)\)", text) + re.findall(r'<img src="([^"]+)"', text):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        path, _, anchor = target.partition("#")
        file = (base / path).resolve() if path else ROOT / page
        if not file.exists() or ROOT not in file.parents:
            missing.append(target)
        elif anchor and file.suffix == ".md":
            heads = re.findall(r"(?m)^#{1,4} (.+)$", file.read_text(encoding="utf-8"))
            if anchor not in {_slug(h) for h in heads}:
                missing.append(target)
    assert missing == []


def _images():
    return re.findall(r'<img src="([^"]+)" alt="([^"]*)"', README)


def _alt(src: str) -> str:
    return dict(_images())[src]


def test_the_readme_images_exist_are_described_and_light_enough():
    """Every image is a file in this repository at a relative path, with alt text that says what it shows; PNGs are
    small enough for a phone, and the SVGs are static: no script, no external reference, a title."""
    images = _images()
    assert [src for src, _ in images] == ["assets/brand/buddie-logo.png", "assets/brand/readme-hero.png",
                                          "assets/demo/verification.svg", "assets/demo/environment.svg"]
    assert len(re.findall(r"<img ", README)) == len(images) and "![" not in README.replace("[![", "")
    for src, alt in images:
        file = ROOT / src
        assert file.is_file(), src
        assert alt.strip() and (len(alt) >= 40 or src.endswith("logo.png")), src
        if file.suffix == ".png":
            data = file.read_bytes()
            assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) <= 500_000, (src, len(data))
            width = int.from_bytes(data[16:20], "big")
            assert width <= 1600, (src, width)
        else:
            svg = file.read_text(encoding="utf-8")
            assert "<title" in svg and 'role="img"' in svg, src
            assert not re.search(r"<script|<foreignObject|\bon[a-z]+=|href=|url\(|@import", svg, re.I), src
            width = int(re.search(r'<svg[^>]* width="(\d+)"', svg)[1])
            assert width <= 800, (src, width)  # its text stays readable when GitHub scales it to a phone
    # the social preview is a repository setting, not part of the page
    assert "social-preview" not in README


def test_the_readme_uses_only_markdown_and_html_github_keeps():
    tags = set(re.findall(r"</?([a-zA-Z]+)", re.sub(r"```.*?```", "", README, flags=re.S)))
    assert tags <= {"div", "img"}, tags
    assert not re.search(r"\bstyle=|<style|<script|class=", README)
    assert README.count('<div align="center">') == README.count("</div>") == 2
    # one logo, and the product's name is not repeated as a heading above or below it
    assert README.count("buddie-logo.png") == 1 and not re.search(r"(?m)^#{1,2} buddie\.?\s*$", README, re.I)


def test_the_readme_carries_the_registry_name_and_honest_badges():
    assert README.startswith("<!-- mcp-name: io.github.tsyyan/buddie -->")  # the MCP Registry checks it on PyPI
    badges = re.findall(r"\[!\[([^\]]+)\]\(([^)]+)\)\]\(([^)]+)\)", README)
    assert [b[0] for b in badges] == ["CI", "Python", "License"]
    expected = {"CI": ("github.com/tsyyan/buddie/actions/workflows/ci.yml/badge.svg", "actions/workflows/ci.yml"),
                "Python": ("img.shields.io/pypi/pyversions/buddie", "pypi.org/project/buddie"),
                "License": ("img.shields.io/github/license/tsyyan/buddie", "LICENSE")}
    for label, image, target in badges:
        assert expected[label][0] in image and expected[label][1] in target, label
        # no scores, ratings, download counts or approval marks
        assert not re.search(r"score|rating|rated|download|trust|verified|approved|official", image + label, re.I)


def test_the_readme_says_what_buddie_is_in_its_opening():
    opening = README.split("## See it in action", 1)[0]
    assert "### Verify the claim. Know the context." in opening
    assert "**Evidence and environment awareness for AI agents.**" in opening
    for capability in ("**Verify.**", "**Catch mismatches.**", "**Observe.**"):
        assert capability in _section(README, "## What Buddie does"), capability
    assert "No language model takes part in the check" in opening
    assert [h for h in re.findall(r"(?m)^## (.+)$", README)] == [
        "Why Buddie?", "What Buddie does", "See it in action", "Get started", "Documentation", "Limitations"]
    # a landing page, not a manual: the detail lives in docs/
    words = len(re.findall(r"\w+", re.sub(r"```.*?```|<[^>]+>|\([^)\s]*\)", " ", README, flags=re.S)))
    assert words <= 1300, words


def test_the_pages_claim_no_more_than_buddie_does():
    for page, text in PAGES.items():
        assert not re.search(r"(checks|verifies|proves) that what an AI agent tells you is true", text, re.I), page
        assert not re.search(r"eliminat\w* hallucination|prevents? (every|all) (incorrect|wrong|false)|"
                             r"guarantee[sd]? (the )?(truth|correct)|always block|blocks every|100 ?%", text, re.I), page
        # a receipt is re-checkable while its evidence lasts, not re-runnable into the same verdict forever
        assert not re.search(r"anyone can re-?run|always reproduc", text, re.I), page
        assert not re.search(r"(approved|listed|available) (in|on|by) Anthropic",
                             text.replace("not listed in", "")), page
    assert "reproduces the verdict only while that evidence is unchanged" in VERIFICATION
    assert "not listed in Anthropic's plugin directory yet" in GETTING
    # the gate is named only for the clients that have one
    catch = _section(README, "## What Buddie does").split("**Catch mismatches.**", 1)[1].split("\n\n", 1)[0]
    assert "In Claude Code and Codex" in catch and "Other clients" in catch
    # the README's limits: short, and each of these said
    limits = _section(README, "## Limitations")
    for must in ("not a truth detector", "stay unchecked", "`PASS` covers only what was checked",
                 "`GAPS` and `EMPTY` are not passes", "only in Claude Code and Codex",
                 "returns an answer rather than locking it", "grants file", "protected policy",
                 "no telemetry", "fetches the pages a report cites", "docs/limitations.md", "docs/security.md"):
        assert must in limits, must
    demo = README.split("### Know the environment", 1)[1].split("\n## ", 1)[0]
    for must in ("read-only", "denied", "unavailable", "not a guarantee"):
        assert must in demo, must
    # every limitation the README used to list is still written down, in full
    full = _section(LIMITS, "## Limitations")
    for must in ("not a truth detector", "`PASS` is scoped", "`GAPS` is not success", "Evidence ages",
                 "Advice is advice", "The gate covers what the client sends it", "The gate is not a lock",
                 "Local evidence is local", "A receipt is an evidence record"):
        assert must in full, must
    security = _section(LIMITS, "## Security and privacy")
    for must in ("It runs locally", "It fetches the pages a report cites", "It calls GitHub", "Your GitHub token",
                 "The Claude Code transcript", "What buddie cannot prevent"):
        assert must in security, must
    # every (2.0) feature is in this version's code
    import buddie
    from buddie import freshness, environment, policy, profiles, receipts  # noqa: F401
    assert receipts.version_of("v1") and buddie.__version__.startswith("2.")


def test_the_docs_index_lists_the_pages_the_readme_moved_out():
    index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    for page in ("getting-started.md", "verification.md", "limitations.md"):
        assert f"]({page})" in index, page
