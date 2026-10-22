"""PR #30: verification profiles. A profile resolves to an explicit, deterministic set of checks run by the one
verify core; what it leaves out is never reported as verified; an unknown name is an error, never a fallback; and
in the hook it only lowers default gate levels, under every explicit level and the protected policy's floors."""
from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

from buddie import cli, config, core, effects, hook, mcp, modules, policy, profiles, remote, resolved, verify
from buddie.core import Check, Provenance
from buddie.verbatim.store import Store

URL = "https://news.example.org/outage"
PAGE = ("<p>" + "Background paragraph about the service. " * 40 + "</p><p>The company said the outage began at 14:59 "
        "UTC and was resolved within two hours.</p>").encode()
QUOTE = "the outage began at 14:59 UTC and was resolved within two hours"
HELLO = hashlib.sha256(b"hello\n").hexdigest()[:12]
GOOD_Q = f"The vendor wrote that “{QUOTE}” ([r]({URL}))."
HOLDS = f"`⚓ data.txt#{HELLO}`"
# a false quote in an answer that otherwise holds (the final rule, which no profile touches, wants an anchor)
BAD_Q = GOOD_Q.replace("14:59", "14:58") + " " + HOLDS
BROKEN = "`⚓ data.txt#" + "0" * 12 + "`"
ANCHORS = {Check.FILE_ANCHOR, Check.COMMIT_ANCHOR, Check.FACT_ANCHOR, Check.PR_ANCHOR, Check.CI_ANCHOR,
           Check.RUN_ANCHOR, Check.CHOICE_ANCHOR, Check.OTHER_ANCHOR}


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A repo with data.txt, a store holding the cited page, the hook's environment pointed at both."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "data.txt").write_bytes(b"hello\n")
    Store(tmp_path / "store").add(URL, PAGE, content_type="text/html")
    for k in ("BUDDIE_GATES", "BUDDIE_FINAL", "BUDDIE_NUMBERS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in (("BUDDIE_FETCH", "0"), ("BUDDIE_GITHUB", "0"), ("BUDDIE_LOG", str(tmp_path / "hook.jsonl")),
                 ("BUDDIE_STATE", str(tmp_path / "pending")), ("BUDDIE_REPOS", str(repo)), ("BUDDIE_LESSONS", "0"),
                 ("VERBATIM_STORE", str(tmp_path / "store")), ("BUDDIE_PROMISES", "0")):
        monkeypatch.setenv(k, v)
    return repo, tmp_path


def toml(repo: Path, text: str) -> None:
    (repo / "buddie.toml").write_text(text, encoding="utf-8")


def stop(repo: Path, text: str, monkeypatch, capsys) -> tuple[int, str]:
    event = {"hook_event_name": "Stop", "session_id": "s", "cwd": str(repo), "last_assistant_message": text}
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(event).encode("utf-8"))))
    code = hook.main()
    return code, capsys.readouterr().err


def last(tmp: Path) -> dict:
    return json.loads((tmp / "hook.jsonl").read_text(encoding="utf-8").splitlines()[-1])


def admin(tmp: Path, monkeypatch, text: str) -> None:
    place = tmp / "system" / "policy.toml"
    place.parent.mkdir(exist_ok=True)
    place.write_text(text, encoding="utf-8")
    monkeypatch.setattr(policy, "location", lambda: place)
    monkeypatch.setattr(policy, "protection_problem", lambda p: None)


# --- 1, 2, 7: resolution ------------------------------------------------------------------------------------------

def test_the_built_in_profiles_resolve_to_these_exact_sets():
    developer, research, complete = (profiles.resolve(n) for n in ("developer", "research", "complete"))
    assert [m.id for m in developer.modules] == ["github", "execution"]
    assert developer.checks == ANCHORS | {Check.WORK_CLAIM}
    assert [m.id for m in research.modules] == ["sources"] and research.checks == {Check.QUOTE, Check.NUMBER}
    assert [m.id for m in complete.modules] == list(modules.IDS) and complete.checks == set(Check)
    assert profiles.gate_levels(developer) == {"quotes": "off", "numbers": "off"}
    assert profiles.gate_levels(research) == {"anchors": "off", "work": "off", "prose": "off"}
    assert profiles.gate_levels(complete) == {}


def test_custom_takes_modules_and_checks_in_any_order_and_resolves_the_same():
    a = profiles.resolve("custom", ["execution"], ["quote", "pr_anchor"])
    b = profiles.resolve(None, ["execution", "execution"], ["pr_anchor", " quote "])  # no profile: custom
    assert a == b and a.profile == "custom"
    assert a.check_ids == ("quote", "pr_anchor", "run_anchor", "choice_anchor", "work_claim")  # core.Check order
    assert [m.id for m in a.modules] == ["sources", "github", "execution"]  # each module with a selected check
    assert "number" in a.excluded and profiles.gate_levels(a) == {"numbers": "off"}


def test_no_profile_means_everything_as_before():
    assert profiles.resolve() is None and profiles.resolve(None, None, None) is None
    assert profiles.from_config({}) is None and profiles.gate_levels(None) == {}


# --- 3, E: unknown configuration is an error ----------------------------------------------------------------------

@pytest.mark.parametrize("args, why", [
    (("strict",), "unknown profile 'strict'"),
    (("Developer",), "unknown profile"),
    (("custom",), "needs modules or checks"),
    (("custom", [], []), "needs modules or checks"),
    (("custom", ["sources", "openai"]), "unknown module(s): openai"),
    (("custom", None, ["quote", "llm_judge"]), "unknown check 'llm_judge'"),
    (("developer", ["sources"]), "selects its own modules"),
    (("research", None, ["pr_anchor"]), "selects its own modules"),
])
def test_an_unknown_or_contradictory_selection_is_an_error(args, why):
    with pytest.raises(profiles.UnknownProfile, match=why.replace("(", r"\(").replace(")", r"\)")):
        profiles.resolve(*args)


@pytest.mark.parametrize("section", ['[verify]\nprofile = "strict"\n', '[verify]\nprofile = "custom"\n',
                                     '[verify]\nprofile = 3\n', '[verify]\nchecks = "quote"\n',
                                     '[verify]\nprofile = "research"\nmode = "fast"\n', 'verify = "research"\n'])
def test_a_buddie_toml_with_a_bad_verify_section_is_unusable_and_the_gate_returns(world, monkeypatch, capsys,
                                                                                  section):
    repo, tmp = world
    toml(repo, section)
    assert config.problem(repo / "buddie.toml") is not None
    code, err = stop(repo, f"Done. {HOLDS}", monkeypatch, capsys)  # a true answer: returned for the file alone
    assert code == 2 and "buddie.toml" in err
    assert last(tmp)["config_errors"]


# --- D: left out is not verified ----------------------------------------------------------------------------------

def test_what_a_profile_leaves_out_is_counted_never_verified(world):
    repo, tmp = world
    text = f"{GOOD_Q}\nThe file changed. {BROKEN}\nMerged. `⚓ pr:o/r#1=open`"
    receipt, found, covered = verify.assess_selected(text, repos=[repo], store=tmp / "store", fetch=False,
                                                     mandate=False, profile="research")
    assert [f.check for f in found] == [Check.QUOTE]  # the broken anchor was not checked...
    assert receipt["predicate"]["anchors"] == [] and receipt["predicate"]["blocking"] == []
    assert core.outcome(found, covered) is core.Outcome.GAPS  # ...so the core outcome is not PASS
    excluded = {s.what: s.count for s in covered.skipped if s.what.startswith("excluded:")}
    assert excluded == {"excluded:file_anchor": 1, "excluded:pr_anchor": 1}
    note = profiles.note(profiles.resolve("research"), covered)
    assert "not checked: number" not in note and "in the text and not checked: 1 file_anchor, 1 pr_anchor" in note


def test_a_selected_check_without_evidence_keeps_its_gap(world):
    repo, tmp = world
    receipt, found, _ = verify.assess_selected(GOOD_Q.replace(URL, "https://gone.example/page"), repos=[repo],
                                               store=tmp / "store", fetch=False, mandate=False, profile="research")
    assert receipt["predicate"]["outcome"] == "GAPS" and found[0].fact is core.Fact.UNDETERMINED


def test_quotes_and_numbers_can_be_chosen_apart(world):
    repo, tmp = world
    text = f"The company said it was resolved within two hours ([r]({URL})). {GOOD_Q}"
    _, only_numbers, covered = verify.assess_selected(text, repos=[repo], store=tmp / "store", fetch=False,
                                                      mandate=False, checks=["number"])
    assert {f.check for f in only_numbers} <= {Check.NUMBER}
    assert any(s.what == "excluded:quote" and s.count for s in covered.skipped)
    assert any(s.what == "check:quote" and s.capability for s in covered.skipped)


# --- 8: legacy ----------------------------------------------------------------------------------------------------

def test_no_profile_is_the_same_receipt_as_verify(world):
    repo, tmp = world
    text = f"{GOOD_Q}\n{HOLDS}"
    full = verify.verify(text, repos=[repo], store=tmp / "store", fetch=False, now="t", mandate=False)
    for kw in ({}, {"profile": "complete"}, {"modules": list(modules.IDS)}):
        assert verify.assess_selected(text, repos=[repo], store=tmp / "store", fetch=False, now="t", mandate=False,
                                      **kw)[0] == full


def test_the_hook_without_a_profile_runs_every_check_and_journals_no_profile(world, monkeypatch, capsys):
    repo, tmp = world
    toml(repo, '[gates]\nquotes = "block"\n')
    assert resolved.resolve({"cwd": str(repo)}).run_checks() is None
    assert stop(repo, BAD_Q, monkeypatch, capsys)[0] == 2
    assert "profile" not in last(tmp)


# --- the hook: a profile is levels, below every explicit one and the policy ---------------------------------------

def test_in_the_hook_a_profile_lowers_only_default_levels(world, monkeypatch, capsys):
    repo, tmp = world
    toml(repo, '[verify]\nprofile = "developer"\n')
    ctx = resolved.resolve({"cwd": str(repo)})
    assert ctx.level["quotes"] == ctx.level["numbers"] == "off" and ctx.level["anchors"] == "block"
    assert Check.QUOTE.value not in ctx.run_checks()  # its pages are not even fetched
    assert stop(repo, BAD_Q, monkeypatch, capsys)[0] == 0  # quotes are off in this project: not checked
    assert last(tmp)["profile"]["name"] == "developer" and "quote" not in last(tmp)["profile"]["checks"]
    assert stop(repo, f"Done. {BROKEN}", monkeypatch, capsys)[0] == 2  # what it keeps, it checks
    toml(repo, '[verify]\nprofile = "developer"\n[gates]\nquotes = "block"\n')  # an explicit level wins
    assert stop(repo, BAD_Q, monkeypatch, capsys)[0] == 2


@pytest.mark.parametrize("cls", ["quotes", "anchors"])
def test_a_policy_floor_brings_back_what_a_profile_turned_off(world, monkeypatch, capsys, cls):
    """C: the agent can write buddie.toml; choosing a narrower profile there does not get under the floor."""
    repo, tmp = world
    narrow = "developer" if cls == "quotes" else "research"
    toml(repo, f'[verify]\nprofile = "{narrow}"\n')
    bad = BAD_Q if cls == "quotes" else f"Done. {BROKEN}"
    assert stop(repo, bad, monkeypatch, capsys)[0] == 0  # without a policy: the project's choice
    admin(tmp, monkeypatch, f'version = 1\n[gates]\n{cls} = "block"\n')
    with policy.snapshot():
        ctx = resolved.resolve({"cwd": str(repo)})
        assert ctx.levels[cls] == config.Setting("block", config.Source.PROTECTED) and f"gates.{cls}" in ctx.refused
        assert any(config.CLASS_OF_CHECK[Check(c)] == cls for c in ctx.run_checks())
    assert stop(repo, bad, monkeypatch, capsys)[0] == 2


def test_an_anchor_a_profile_does_not_check_is_still_an_anchor_for_the_final_rule(world, monkeypatch, capsys):
    """The final rule asks whether the answer carries an anchor. Under research the anchors are not checked, so the
    receipt lists none; the answer still has one, and buddie must not say otherwise."""
    repo, tmp = world
    toml(repo, '[verify]\nprofile = "research"\n')
    code, err = stop(repo, f"{GOOD_Q} {HOLDS}", monkeypatch, capsys)
    assert code == 0 and "has no anchor" not in err and "final_no_anchor" not in last(tmp).get("reasons", {})
    code, err = stop(repo, GOOD_Q, monkeypatch, capsys)  # an answer with none is still told so
    assert code == 2 and "final answer has no anchor" in err


def test_an_invalid_policy_still_fails_closed_under_a_profile(world, monkeypatch, capsys):
    repo, tmp = world
    toml(repo, '[verify]\nprofile = "research"\n')
    admin(tmp, monkeypatch, "version = 2\n")
    code, err = stop(repo, f"Done. {HOLDS}", monkeypatch, capsys)
    assert code == 2 and last(tmp)["policy"]["status"] == "invalid"


def test_a_check_that_fails_under_a_profile_fails_closed(world, monkeypatch, capsys):
    repo, _ = world
    toml(repo, '[verify]\nprofile = "developer"\n')
    monkeypatch.setattr(verify, "_assess", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    code, err = stop(repo, f"Done. {HOLDS}", monkeypatch, capsys)
    assert code == 2 and "boom" in err


def test_the_profile_shows_in_buddie_status(world):
    repo, _ = world
    got = config.influence({"verify": {"profile": "research"}})
    assert ("verify.profile", "research", True) in [(i.setting, i.with_repo, i.weakens) for i in got]
    assert any(i.setting == "gates.anchors" and i.weakens for i in got)


# --- 10: provenance is not the profile's to change ----------------------------------------------------------------

def test_a_profile_does_not_change_provenance(world, monkeypatch):
    import urllib.request

    class Answer(io.BytesIO):
        def __init__(self, req):
            super().__init__(json.dumps({"state": "open", "head": {"sha": "abc"}}).encode())
            self.url = req.full_url

        def geturl(self):
            return self.url

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: Answer(req))

    def forged(path):
        return {"state": "open", "head": {"sha": "abc"}}
    forged.buddie_collector = True
    for github, want in ((effects.github_get, Provenance.COLLECTOR_OBSERVED), (forged, Provenance.CALLER_SUPPLIED)):
        for profile in ("developer", "complete", None):
            _, found, _ = verify.assess_selected("Merged. `⚓ pr:o/r#1=open`", repos=[], fetch=False, mandate=False,
                                                 github=github, profile=profile)
            assert found[0].evidence[0].provenance is want


# --- 9: the surfaces ----------------------------------------------------------------------------------------------

def test_cli_profiles_and_verify_with_a_profile(world, capsys):
    repo, tmp = world
    report = tmp / "r.md"
    report.write_text(f"{GOOD_Q}\nDone. {BROKEN}\n", encoding="utf-8")
    assert cli.main(["profiles"]) == 0
    listed = capsys.readouterr().out
    assert [line.split()[0] for line in listed.splitlines() if not line.startswith(" ")] == list(profiles.NAMES)
    common = ["verify", str(report), "--no-fetch", "--no-github", "--repo", str(repo), "--store", str(tmp / "store")]
    assert cli.main(common + ["--profile", "research"]) == 0  # the broken anchor is not in this profile
    out = capsys.readouterr().out
    assert "note  profile research: modules sources" in out and "1 file_anchor" in out
    assert cli.main(common) == 1  # without a profile it is checked, as before
    assert "profile" not in capsys.readouterr().out
    for bad in (["--profile", "strict"], ["--profile", "developer", "--modules", "sources"],
                ["--profile", "custom"], ["--checks", "nope"]):
        assert cli.main(common + bad) == 2
        assert "buddie verify:" in capsys.readouterr().err


def test_mcp_takes_a_profile_and_keeps_the_receipt_as_its_result(world):
    repo, tmp = world
    schema = next(t for t in mcp.TOOLS if t["name"] == "verify_report")["inputSchema"]["properties"]
    assert schema["profile"]["enum"] == list(profiles.NAMES) and "checks" in schema

    def call(**arguments):
        return mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "verify_report", "arguments": {"text": f"{GOOD_Q}\nDone. {BROKEN}", "repos": [str(repo)],
                                                   "store": str(tmp / "store"), "fetch": False, "github": False,
                                                   **arguments}}})["result"]
    got = call(profile="research")
    assert got["structuredContent"]["_type"] == "https://in-toto.io/Statement/v1"  # the receipt, unchanged in kind
    assert "profile research" in got["content"][0]["text"] and "1 file_anchor" in got["content"][0]["text"]
    assert "profile" not in call()["content"][0]["text"].split("\n")[1]  # no profile: no note line
    bad = call(profile="strict")
    assert bad["isError"] and "unknown profile" in json.dumps(bad)


def test_the_remote_server_takes_no_profile():
    schema = next(t for t in remote.tools() if t["name"] == "verify_report")["inputSchema"]["properties"]
    assert not {"profile", "checks", "modules"} & set(schema)
    with pytest.raises(ValueError):
        remote.verify_report({"text": GOOD_Q, "profile": "research"})


# --- review follow-up: an empty effective selection is empty, not "everything" ------------------------------------

@pytest.fixture
def counted(monkeypatch):
    """Every page fetch and every GitHub GET the hook makes, counted (and answered with nothing)."""
    calls = {"fetch": 0, "github": 0}

    def fetch(self, url, timeout=30):
        calls["fetch"] += 1
        return self.record(url, {"sha256": None, "fetched_at": "t", "http_status": None, "error": "counted"})

    def github(path):
        calls["github"] += 1
        return None
    monkeypatch.setattr(Store, "fetch", fetch)
    monkeypatch.setattr(effects, "github_get", github)
    monkeypatch.setenv("BUDDIE_FETCH", "1")
    monkeypatch.setenv("BUDDIE_GITHUB", "1")
    return calls


EVERY_KIND = f"The vendor wrote that “{QUOTE}” ([r](https://other.example/page)).\nMerged. `⚓ pr:o/r#1=open`"


def test_no_profile_runs_every_legacy_check(world, counted, monkeypatch, capsys):
    repo, tmp = world
    toml(repo, '[gates]\nanchors = "block"\n')
    assert resolved.resolve({"cwd": str(repo)}).run_checks() is None  # None: the legacy path, every check
    stop(repo, EVERY_KIND, monkeypatch, capsys)
    assert counted["fetch"] >= 1 and counted["github"] >= 1


def test_a_profile_with_every_class_off_runs_no_check(world, counted, monkeypatch, capsys):
    repo, tmp = world
    toml(repo, '[verify]\nprofile = "research"\n[gates]\nquotes = "off"\nnumbers = "off"\n')
    ctx = resolved.resolve({"cwd": str(repo)})
    assert ctx.run_checks() == ()  # a profile and nothing left on: empty, not None
    stop(repo, EVERY_KIND, monkeypatch, capsys)
    assert counted == {"fetch": 0, "github": 0}  # nothing excluded was looked up
    entry = last(tmp)
    assert entry["profile"] == {"name": "research", "checks": []}
    assert entry["outcome"] != "PASS"  # nothing ran, so nothing passed
    _, found, covered = verify.assess_selected(EVERY_KIND, selection=ctx.effective(), repos=[repo], fetch=True,
                                               mandate=False, github=effects.github_get)
    assert found == [] and counted == {"fetch": 0, "github": 0}
    assert {s.what for s in covered.capabilities_off} >= {"module:sources", "module:github", "module:execution"}
    assert core.outcome(found, covered) is core.Outcome.UNKNOWN
    note = profiles.note(ctx.effective(), covered)
    assert note.startswith("No verification checks ran under the effective profile research")
    assert "1 quote" in note and "1 pr_anchor" in note


def test_a_partly_enabled_profile_runs_only_what_is_on(world, counted, monkeypatch, capsys):
    repo, tmp = world
    toml(repo, '[verify]\nprofile = "complete"\n[gates]\nquotes = "off"\nnumbers = "off"\n')
    assert Check.QUOTE.value not in resolved.resolve({"cwd": str(repo)}).run_checks()
    stop(repo, EVERY_KIND, monkeypatch, capsys)
    assert counted["fetch"] == 0 and counted["github"] >= 1  # anchors on: GitHub asked; quotes off: no page


def test_a_policy_floor_runs_the_checks_of_the_class_it_restores(world, counted, monkeypatch, capsys):
    repo, tmp = world
    toml(repo, '[verify]\nprofile = "research"\n[gates]\nquotes = "off"\nnumbers = "off"\n')
    admin(tmp, monkeypatch, 'version = 1\n[gates]\nanchors = "block"\n')
    with policy.snapshot():
        run = resolved.resolve({"cwd": str(repo)}).run_checks()
    assert Check.PR_ANCHOR.value in run and Check.QUOTE.value not in run
    stop(repo, EVERY_KIND, monkeypatch, capsys)
    assert counted["github"] >= 1 and counted["fetch"] == 0


def test_in_the_hook_a_custom_check_brings_its_whole_class(world, monkeypatch, capsys):
    """Decision B: the hook selects by gate class. custom with only pr_anchor turns the anchors class on, and every
    anchor check of that class runs there; the journal lists them. CLI, MCP and the API select exactly."""
    repo, tmp = world
    toml(repo, '[verify]\nprofile = "custom"\nchecks = ["pr_anchor"]\n')
    run = resolved.resolve({"cwd": str(repo)}).run_checks()
    assert set(run) == {c.value for c in ANCHORS}
    stop(repo, f"Done. {HOLDS}", monkeypatch, capsys)
    assert set(last(tmp)["profile"]["checks"]) == {c.value for c in ANCHORS}
    assert profiles.resolve("custom", None, ["pr_anchor"]).checks == {Check.PR_ANCHOR}


def test_buddie_status_says_what_the_hook_runs_and_when_it_runs_nothing(world, monkeypatch, capsys):
    repo, _ = world
    monkeypatch.chdir(repo)
    toml(repo, '[verify]\nprofile = "research"\n')
    assert cli.main(["status"]) == 0
    assert "profile: research; the hook runs: quote, number" in capsys.readouterr().out
    toml(repo, '[verify]\nprofile = "research"\n[gates]\nquotes = "off"\nnumbers = "off"\n')
    cli.main(["status"])
    assert "the hook runs: no verification check" in capsys.readouterr().out
    toml(repo, '[gates]\nquotes = "off"\n')  # no profile: no profile line, as before
    cli.main(["status"])
    assert "profile:" not in capsys.readouterr().out


def test_an_empty_selection_cannot_be_asked_for_by_name():
    """A person's custom with nothing in it is an error (resolve); an empty selection only comes from the hook's
    levels, and verify takes it as it is, never as "all"."""
    with pytest.raises(profiles.UnknownProfile):
        profiles.resolve("custom", [], [])
    empty = profiles.effective("developer", ())
    assert empty.checks == frozenset() and empty.modules == () and empty.describe() == "profile developer: no checks"
    receipt, found, _ = verify.assess_selected("Merged. `⚓ pr:o/r#1=open`", selection=empty, fetch=False,
                                               mandate=False)
    assert found == [] and receipt["predicate"]["outcome"] == "EMPTY"  # receipt-v0's own word for nothing checked
    with pytest.raises(profiles.UnknownProfile, match="not both"):
        verify.assess_selected("x", selection=empty, profile="developer")
