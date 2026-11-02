"""env: anchors: a claim about this machine against what buddie observes on it, under the person's grants."""
from __future__ import annotations

import sys

import pytest

from buddie import anchors, env_anchors as env, findings, mcp, remote
from buddie.core import Check, Fact
from buddie.verify import assess_selected


def doc(**cats) -> dict:
    """A diagnostics document with these categories: {"system.os": {"version": "24.04"}}; None is unavailable."""
    out = {}
    for cid, values in cats.items():
        out[cid.replace("__", ".")] = {"status": "collected", "observations": {
            k: ({"status": "observed", "value": v, "concerns": "runtime", "observed_at": "2026-11-02T00:00:00Z"}
                if v is not None else {"status": "unavailable", "value": None, "reason": "not_found_on_path"})
            for k, v in values.items()}}
    return {"categories": out, "observations_concern": "runtime"}


DOC = doc(system__os={"version": "24.04", "family": "Linux"}, system__shell={"default": "bash", "pwsh": None},
          software__python={"interpreters": [{"version": "3.12.3", "implementation": "cpython"},
                                             {"version": "3.11.18", "implementation": "cpython"}]},
          software__tools={"ffmpeg": "6.1.1-3ubuntu5"}, system__permissions={"elevated": False})


@pytest.mark.parametrize("claimed, observed, holds", [
    ("24.04", "24.04", True), ("bash", "Bash", True), ("3.12", "3.12.3", True), ("3.1", "3.12.3", False),
    ("6.1", "6.1.1-3ubuntu5", True), ("6", "61.0", False), ("v20", "v20.11.1", True), ("20", "v20.11.1", True),
    ("3.12", [{"version": "3.11.18"}, {"version": "3.12.3"}], True), ("3.13", [{"version": "3.12.3"}], False),
    ("false", False, True), ("zsh", "bash", False), ("8", 8, True)])
def test_a_value_holds_by_equality_or_a_version_prefix(claimed, observed, holds):
    assert env.matches(claimed, observed) is holds


@pytest.mark.parametrize("anchor, status, part", [
    ("env:system.os.version=24.04", "HOLDS", None),
    ("env:software.python.interpreters=3.12", "HOLDS", None),
    ("env:software.tools.ffmpeg=6.1", "HOLDS", None),
    ("env:system.permissions.elevated=false", "HOLDS", None),
    ("env:system.os.version=22.04", "BROKEN", "observed system.os.version = 24.04"),
    ("env:system.shell.default=zsh", "BROKEN", "= bash"),
    ("env:system.shell.pwsh=7.4", "UNCHECKABLE", "not_found_on_path"),  # not on PATH is not "absent"
    ("env:hardware.gpu.adapters=nvidia", "UNCHECKABLE", "hardware.gpu was not observed"),
    ("env:system.os.distro=ubuntu", "BROKEN", "system.os has no distro; it has family"),
    ("env:system.osx.version=1", "BROKEN", "no category system.osx"),
])
def test_each_anchor_against_a_document(anchor, status, part):
    row = env.check(anchor, DOC)
    assert row["status"] == status, row
    assert part is None or part in row["why"]
    if status == "HOLDS":
        assert row["concerns"] == "runtime"  # what buddie's process saw, said in the row


def test_no_machine_observed_is_uncheckable_never_holds():
    assert env.check("env:system.os.version=24.04", False)["why"] == env.OFF
    assert env.check("env:system.os.version=24.04", {"error": "two collections running"})["status"] == "UNCHECKABLE"


def test_one_collection_for_every_env_anchor_with_tools_named():
    calls = []

    def collect(categories, *, task, tools):
        calls.append((categories, tools))
        return DOC

    text = ("You have Ubuntu ⚓ `env:system.os.version=24.04` and bash ⚓ `env:system.shell.default=bash`.\n"
            "ffmpeg is there ⚓ `env:software.tools.ffmpeg=6.1`; ⚓ `env:nope.x.y=1` is not a category.")
    rows = anchors.check_text(text, [], {"collect": collect})
    assert calls == [(["system.os", "system.shell", "software.tools"], ["ffmpeg"])]
    assert [r["status"] for r in rows] == ["HOLDS", "HOLDS", "HOLDS", "BROKEN"]


def test_a_bare_env_anchor_is_an_anchor():
    assert anchors.ANCHOR.findall("Python ⚓ env:software.python.interpreters=3.12, ready.") == [
        "env:software.python.interpreters=3.12"]


def test_findings_name_the_check_the_module_and_the_evidence():
    row = dict(env.check("env:system.os.version=24.04", DOC), line=3)
    f = findings.anchor(row)
    assert f.check is Check.ENV_ANCHOR and f.fact is Fact.SUPPORTED
    assert f.evidence[0].kind == "environment" and f.evidence[0].provenance.value == "agent_writable"
    assert findings.anchor(env.check("env:system.os.version=1", DOC)).fact is Fact.CONTRADICTED


def test_a_report_with_a_wrong_machine_fact_fails_and_the_receipt_says_where(tmp_path):
    text = "Your system: Ubuntu ⚓ `env:system.os.version=22.04`, Python ⚓ `env:software.python.interpreters=3.12`."
    receipt, found, _ = assess_selected(text, repos=[], store=tmp_path / "s", fetch=False, environment=DOC)
    pred = receipt["predicate"]
    assert pred["outcome"] == "FAIL" and "anchors 1/2 hold, 1 broken" in pred["line"]
    assert pred["blocking"] == ["anchor line 1 ⚓ env:system.os.version=22.04: observed system.os.version = 24.04"]
    assert {f.check for f in found} == {Check.ENV_ANCHOR}
    off, _, _ = assess_selected(text, repos=[], store=tmp_path / "s", fetch=False, environment=False)
    assert off["predicate"]["outcome"] == "GAPS"


def test_the_research_profile_leaves_env_anchors_out(tmp_path):
    text = "Ubuntu ⚓ `env:system.os.version=22.04`."
    receipt, found, covered = assess_selected(text, repos=[], store=tmp_path / "s", fetch=False, profile="research",
                                              environment=DOC)
    assert not found and receipt["predicate"]["outcome"] == "EMPTY"
    assert any(s.what == "module:environment" for s in covered.skipped)


def test_the_remote_server_observes_no_machine(monkeypatch):
    monkeypatch.setattr(env, "observe", lambda *a, **k: pytest.fail("the remote server must not collect"))
    receipt, _ = remote.verify_report({"text": "Ubuntu ⚓ `env:system.os.version=24.04`.", "fetch": False,
                                       "github": False})
    row = receipt["predicate"]["anchors"][0]
    assert row["status"] == "UNCHECKABLE" and row["why"] == env.OFF


@pytest.mark.skipif(sys.platform == "win32", reason="the grants file lives under APPDATA there; covered on POSIX")
def test_end_to_end_the_persons_grants_decide(tmp_path, monkeypatch):
    """A real collection: without a grants file nothing is observed (UNCHECKABLE); with the baseline it holds."""
    import platform
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "c"))
    arch = platform.machine().lower()
    text = f"This machine ⚓ `env:system.os.architecture={arch}`."
    args = {"text": text, "fetch": False, "github": False, "repos": [], "store": str(tmp_path / "s")}
    got, _, *_ = mcp.verify_report(args)
    assert got["predicate"]["anchors"][0]["status"] == "UNCHECKABLE"
    from buddie import cli
    assert cli.main(["snapshot", "--grant-baseline"]) == 0
    got, _, *_ = mcp.verify_report(args)
    row = got["predicate"]["anchors"][0]
    assert row["status"] in ("HOLDS", "BROKEN") and row["observed"]  # observed now; the value is the machine's
    if row["status"] == "BROKEN":  # an architecture spelled another way (amd64 for x86_64): said, not passed
        assert row["why"].startswith("observed system.os.architecture")
