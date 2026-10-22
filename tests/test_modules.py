"""PR #29: the module registry. Stable ids, every check in exactly one module, deterministic order, explicit errors
for unknown modules, and no change to what verify finds when every module runs (the default, and the hook's)."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from buddie import cli, core, mcp, modules, remote, verify
from buddie.core import Check, Fact
from buddie.modules import REGISTRY, UnknownModule

ROOT = Path(__file__).resolve().parents[1]
HELLO = hashlib.sha256(b"hello\n").hexdigest()[:12]
TEXT = (f"The file holds. `⚓ data.txt#{HELLO}`\n"
        "The tests ran. `⚓ run:pytest -q => 3 passed`\n"
        "It quotes “a sentence that is in no snapshot at all” ([p](https://e.example/a)).\n")
NOW = "2026-10-22T00:00:00Z"


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    (r / "data.txt").write_bytes(b"hello\n")
    return r


def receipt_of(repo, tmp_path, selected=None):
    return verify.assess_selected(TEXT, selected, repos=[repo], store=tmp_path / "store", fetch=False, now=NOW,
                                  mandate=False)


# --- the registry -------------------------------------------------------------------------------------------------

def test_the_ids_are_stable_and_every_check_has_exactly_one_module():
    assert modules.IDS == ("sources", "github", "execution")
    owners = {c: [m.id for m in REGISTRY if c in m.checks] for c in Check}
    assert all(len(v) == 1 for v in owners.values()), owners
    assert {c: modules.module_of(c).id for c in Check} == {c: v[0] for c, v in owners.items()}
    assert owners[Check.QUOTE] == owners[Check.NUMBER] == ["sources"]
    assert {c for c, v in owners.items() if v == ["github"]} >= {Check.PR_ANCHOR, Check.CI_ANCHOR, Check.COMMIT_ANCHOR}
    assert {c for c, v in owners.items() if v == ["execution"]} >= {Check.RUN_ANCHOR, Check.WORK_CLAIM}


def test_selection_is_in_registry_order_whatever_the_order_asked():
    assert [m.id for m in modules.select(["execution", "sources", "execution"])] == ["sources", "execution"]
    assert modules.select(None) == REGISTRY == modules.parse("all") == modules.parse(None)
    assert [m.id for m in modules.parse(" github , sources")] == ["sources", "github"]


@pytest.mark.parametrize("ids", [["sources", "openai"], ["Sources"], [], [""], ["github", "plugin:x"]])
def test_an_unknown_or_empty_selection_is_an_error_not_a_smaller_check(ids):
    with pytest.raises(UnknownModule) as got:
        modules.select(ids)
    assert "known: sources, github, execution" in str(got.value)


def test_a_finding_no_module_provides_is_an_error():
    stray = core.Finding(Check.QUOTE, "x", "FOUND", Fact.SUPPORTED, core.ReasonCode.FOUND)
    with pytest.raises(LookupError):
        modules.module_of("not a check")  # type: ignore[arg-type]
    assert modules.results([stray], REGISTRY)[0].findings == (stray,)


# --- assess with modules ------------------------------------------------------------------------------------------

def test_every_module_is_what_verify_always_did(repo, tmp_path):
    full = verify.verify(TEXT, repos=[repo], store=tmp_path / "store", fetch=False, now=NOW, mandate=False)
    receipt, found, covered = receipt_of(repo, tmp_path, None)
    assert receipt == full
    assert receipt_of(repo, tmp_path, list(modules.IDS))[0] == full
    assert not any(s.what.startswith("module:") for s in covered.skipped)


def test_a_module_left_out_is_not_run_and_coverage_says_so(repo, tmp_path):
    receipt, found, covered = receipt_of(repo, tmp_path, ["github"])
    pred = receipt["predicate"]
    assert pred["quotes"] == [] and pred["numbers"] == []
    assert [a["anchor"] for a in pred["anchors"]] == [f"data.txt#{HELLO}"]  # the run: anchor is execution's
    assert {f.check for f in found} == {Check.FILE_ANCHOR}
    off = [s for s in covered.skipped if s.what.startswith("module:")]
    assert [s.what for s in off] == ["module:sources", "module:execution"] and all(s.capability for s in off)
    # every anchor checked held, but a module was off: the core outcome is GAPS, never PASS
    assert pred["outcome"] == "PASS" and core.outcome(found, covered) is core.Outcome.GAPS


def test_results_per_module_in_registry_order(repo, tmp_path):
    _, found, _ = receipt_of(repo, tmp_path, None)
    got = modules.results(found, modules.select(["execution", "github"]))
    assert [r.module for r in got] == list(modules.IDS)
    sources, github, execution = got
    assert not sources.selected and sources.outcome is None
    assert github.outcome is core.Outcome.PASS and execution.selected
    assert {f.check for f in execution.findings} == {Check.RUN_ANCHOR}


# --- the CLI, MCP and remote surfaces -------------------------------------------------------------------------------

def test_cli_lists_the_modules_and_refuses_an_unknown_one(repo, tmp_path, capsys, monkeypatch):
    assert cli.main(["modules"]) == 0
    out = capsys.readouterr().out
    assert [line.split()[0] for line in out.splitlines() if not line.startswith(" ")] == list(modules.IDS)
    report = tmp_path / "r.md"
    report.write_text(TEXT, encoding="utf-8")
    with pytest.raises(SystemExit) as got:
        cli.main(["verify", str(report), "--modules", "sources,nope"])
    assert got.value.code == 2 and "unknown module(s): nope" in capsys.readouterr().err
    monkeypatch.chdir(repo)
    assert cli.main(["verify", str(report), "--no-fetch", "--no-github", "--repo", str(repo),
                     "--modules", "github"]) == 0
    assert capsys.readouterr().out.strip().endswith("anchors 1/1 hold")


def test_mcp_takes_modules_and_the_remote_server_does_not():
    schema = next(t for t in mcp.TOOLS if t["name"] == "verify_report")["inputSchema"]["properties"]
    assert schema["modules"]["items"]["enum"] == list(modules.IDS)
    got = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                      "params": {"name": "verify_report", "arguments": {"text": TEXT, "modules": ["bogus"]}}})
    assert got["result"]["isError"] and "unknown module" in json.dumps(got)
    remote_schema = next(t for t in remote.tools() if t["name"] == "verify_report")["inputSchema"]["properties"]
    assert "modules" not in remote_schema
    with pytest.raises(ValueError):
        remote.verify_report({"text": TEXT, "modules": ["sources"]})


# --- the core stays free of transports and providers ---------------------------------------------------------------

def test_the_core_imports_no_transport_hook_or_provider():
    # -I keeps the cwd off sys.path, and CI's os jobs run from the checkout without installing buddie
    code = (f"import sys; sys.path.insert(0, {str(ROOT)!r}); "
            "import buddie.verify, buddie.modules, buddie.evidence, buddie.findings; "
            "print(' '.join(sorted(m for m in sys.modules if m.startswith('buddie'))))")
    loaded = subprocess.run([sys.executable, "-I", "-c", code], cwd=ROOT, capture_output=True, text=True,
                            check=True).stdout.split()
    assert "buddie.verify" in loaded
    for transport in ("buddie.hook", "buddie.mcp", "buddie.remote", "buddie.cli", "buddie.journal",
                      "buddie.promises", "buddie.context"):
        assert transport not in loaded
    for name in ("core", "modules", "evidence", "verify", "findings"):
        source = (ROOT / "buddie" / f"{name}.py").read_text(encoding="utf-8").lower()
        assert "openai" not in source and "chatgpt" not in source
