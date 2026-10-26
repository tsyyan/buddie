"""Run an installed buddie the way a person does, from outside the repository (docs/release.md, the candidate).

    python scripts/smoke_install.py VENV_PYTHON VERSION

VENV_PYTHON is the interpreter of a clean venv the wheel or sdist was installed into. Checks: the version both
entry points report, `buddie-verbatim --help`, the stdio MCP server's initialize and tools/list, and the README's
quickstart (a report with a misquote: exit 1, outcome FAIL) run against an offline snapshot.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ["verify_report", "snap", "source_text", "summary", "environment_snapshot", "feedback_start",
         "feedback_resolve", "feedback_accept"]


def run(cmd: list[str], cwd: Path, env: dict, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, env=env, input=stdin, capture_output=True, text=True, encoding="utf-8",
                          timeout=120)


def main(python: str, version: str) -> int:
    bindir = Path(python).parent
    exe = ".exe" if os.name == "nt" else ""
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        env = dict(os.environ, VERBATIM_STORE=str(cwd / "store"), BUDDIE_GITHUB="0", PYTHONIOENCODING="utf-8")
        env.pop("PYTHONPATH", None)
        out = run([python, "-m", "buddie", "--version"], cwd, env)
        assert out.stdout.strip() == f"buddie {version}", (out.stdout, out.stderr)
        out = run([str(bindir / f"buddie{exe}"), "--version"], cwd, env)
        assert out.stdout.strip() == f"buddie {version}", (out.stdout, out.stderr)
        out = run([str(bindir / f"buddie-verbatim{exe}"), "--help"], cwd, env)
        assert out.returncode == 0, out.stderr
        # the installed package, not this checkout
        out = run([python, "-c", "import buddie; print(buddie.__file__)"], cwd, env)
        assert ROOT not in Path(out.stdout.strip()).resolve().parents, out.stdout

        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
        out = run([python, "-m", "buddie", "serve"], cwd, env, "".join(json.dumps(m) + "\n" for m in msgs))
        replies = [json.loads(line) for line in out.stdout.splitlines()]
        assert replies[0]["result"]["serverInfo"]["version"] == version, replies[0]
        assert [t["name"] for t in replies[1]["result"]["tools"]] == TOOLS, replies[1]

        quick = ROOT / "examples" / "quickstart"
        shutil.copy(quick / "report.md", cwd / "report.md")
        out = run([str(bindir / f"buddie-verbatim{exe}"), "add", "https://status.example.com/incidents/42",
                   str(quick / "page.html")], cwd, env)
        assert out.returncode == 0, out.stderr
        out = run([python, "-m", "buddie", "verify", "report.md", "--no-fetch", "--json", "r.json"], cwd, env)
        outcome = json.loads((cwd / "r.json").read_text(encoding="utf-8"))["predicate"]["outcome"]
        assert (out.returncode, outcome) == (1, "FAIL"), (out.returncode, outcome, out.stderr)
    print(f"installed buddie {version}: both entry points, MCP tools {', '.join(TOOLS)}, quickstart FAIL as documented")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
