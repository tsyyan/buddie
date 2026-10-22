"""PR #31: receipt-v1. One verify.Assessment, rendered as receipt-v0 (unchanged) or receipt-v1, which says what ran,
what was established, what was left out and why, and how the evidence was obtained. The schema is checked here by a
small validator of the JSON Schema keywords it uses, so no dependency is needed to trust docs/receipt-v1.schema.json."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import urllib.request
from pathlib import Path

import pytest

from buddie import cli, effects, mcp, policy, profiles, receipts, remote, resolved, verify
from buddie import mandate as man
from buddie.verbatim.store import Store

ROOT = Path(__file__).resolve().parents[1]
URL = "https://news.example.org/outage"
PAGE = ("<p>" + "Background paragraph about the service. " * 40 + "</p><p>The company said the outage began at 14:59 "
        "UTC and was resolved within two hours.</p>").encode()
QUOTE = "the outage began at 14:59 UTC and was resolved within two hours"
GOOD_Q = f"The vendor wrote that “{QUOTE}” ([r]({URL}))."
BAD_Q = GOOD_Q.replace("14:59", "14:58")
HELLO = hashlib.sha256(b"hello\n").hexdigest()[:12]
HOLDS = f"`⚓ data.txt#{HELLO}`"
BROKEN = "`⚓ data.txt#" + "0" * 12 + "`"
NOW = "2026-10-22T00:00:00Z"


# --- a validator for the JSON Schema keywords receipts.SCHEMA uses -------------------------------------------------

def _types(value):
    if value is None:
        return {"null"}
    if isinstance(value, bool):
        return {"boolean"}
    if isinstance(value, int):
        return {"integer", "number"}
    return {{str: "string", float: "number", list: "array", dict: "object"}[type(value)]}


def validate(value, schema, root=None, at="$") -> list[str]:
    root = root or schema
    if "$ref" in schema:
        return validate(value, root["$defs"][schema["$ref"].rsplit("/", 1)[1]], root, at)
    out = []
    if "const" in schema and value != schema["const"]:
        out.append(f"{at}: not {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{at}: {value!r} not in enum")
    if "type" in schema:
        want = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not _types(value) & set(want):
            return out + [f"{at}: {type(value).__name__} is not {want}"]
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                out.append(f"{at}: missing {key}")
        props = schema.get("properties", {})
        for key, item in value.items():
            if key in props:
                out += validate(item, props[key], root, f"{at}.{key}")
            elif schema.get("additionalProperties") is False:
                out.append(f"{at}: unexpected {key}")
            elif isinstance(schema.get("additionalProperties"), dict):
                out += validate(item, schema["additionalProperties"], root, f"{at}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            out.append(f"{at}: fewer than {schema['minItems']} items")
        for i, item in enumerate(value):
            if "items" in schema:
                out += validate(item, schema["items"], root, f"{at}[{i}]")
    if isinstance(value, int) and not isinstance(value, bool) and value < schema.get("minimum", value):
        out.append(f"{at}: below {schema['minimum']}")
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        out.append(f"{at}: does not match {schema['pattern']}")
    return out


def valid(receipt) -> None:
    assert validate(receipt, receipts.SCHEMA) == [] and receipts.problems(receipt) == []


@pytest.fixture
def world(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "data.txt").write_bytes(b"hello\n")
    Store(tmp_path / "store").add(URL, PAGE, content_type="text/html")
    for k, v in (("VERBATIM_STORE", str(tmp_path / "store")), ("BUDDIE_LOG", str(tmp_path / "hook.jsonl")),
                 ("BUDDIE_STATE", str(tmp_path / "pending")), ("BUDDIE_REPOS", str(repo)), ("BUDDIE_FETCH", "0"),
                 ("BUDDIE_GITHUB", "0"), ("BUDDIE_LESSONS", "0"), ("BUDDIE_PROMISES", "0")):
        monkeypatch.setenv(k, v)
    return repo, tmp_path


def run(world, text, **kw):
    repo, tmp = world
    kw = {"repos": [repo], "store": tmp / "store", "fetch": False, "now": NOW, **kw}
    return verify.assessment(text, **kw)


def full_mandate(repo):
    """A [mandate] config with its (empty) queue, so work claims can be checked: without one they are unavailable
    (coverage UNKNOWN)."""
    (repo / "NEXT.md").write_text("| № | Шаг | Тема | Основание | Статус |\n|---|---|---|---|---|\n", encoding="utf-8")
    (repo / "ACCEPTED.md").write_text("| Область | Слова |\n|---|---|\n", encoding="utf-8")
    return {**man.DEFAULTS, "repo": str(repo)}


# --- the ambiguity this contract removes --------------------------------------------------------------------------

def test_a_partial_run_is_v0_pass_and_v1_says_it_was_partial(world):
    text = f"{GOOD_Q}\nThe file changed. {BROKEN}"
    a = run(world, text, profile="research")
    assert a.receipt["predicate"]["outcome"] == "PASS"  # receipt-v0, as ever: the quote holds
    r = receipts.render(a, "v1")
    valid(r)
    assert r["predicate"]["verification"]["outcome"] == "PASS"  # what ran established no failure...
    scope = r["predicate"]["scope"]
    assert scope["coverage"] == "PARTIAL"  # ...and not everything ran
    left = {e["check"]: (e["reason"], e["detected"]) for e in scope["excluded"]}
    assert left["file_anchor"] == ("profile", 1)  # the broken anchor is in the text and was not checked
    assert left["pr_anchor"] == ("profile", 0)  # countable and absent: 0, not "cannot tell"
    assert left["work_claim"] == ("profile", None)  # what counts as a work claim takes the check
    assert scope["requested"] == {"profile": "research", "checks": ["quote", "number"]}


def test_an_empty_effective_selection_is_never_a_complete_success(world):
    empty = profiles.effective("research", ())
    r = receipts.render(run(world, f"{GOOD_Q} {HOLDS}", selection=empty, requested=profiles.resolve("research")),
                        "v1")
    valid(r)
    assert r["predicate"]["verification"]["outcome"] == "NOT_RUN" and r["predicate"]["scope"]["coverage"] == "NONE"
    assert r["predicate"]["scope"]["executed"] == []
    reasons = {e["check"]: e["reason"] for e in r["predicate"]["scope"]["excluded"]}
    assert reasons["quote"] == "gate_level" and reasons["pr_anchor"] == "profile"  # turned off vs never asked for


# --- outcomes and coverage ----------------------------------------------------------------------------------------

def test_full_coverage_runs_every_check(world):
    repo, _ = world
    r = receipts.render(run(world, f"{GOOD_Q} {HOLDS}", mandate=full_mandate(repo)), "v1")
    valid(r)
    scope = r["predicate"]["scope"]
    assert scope["coverage"] == "FULL" and scope["excluded"] == [] and scope["executed"] == list(receipts.CHECKS)
    assert r["predicate"]["verification"]["outcome"] == "PASS"


def test_no_detected_claims_is_empty_even_with_full_coverage(world):
    repo, _ = world
    r = receipts.render(run(world, "Nothing to see here.", mandate=full_mandate(repo)), "v1")
    valid(r)
    assert r["predicate"]["verification"]["outcome"] == "EMPTY" and r["predicate"]["scope"]["coverage"] == "FULL"


def test_without_a_mandate_config_work_claims_are_unavailable_and_coverage_unknown(world):
    r = receipts.render(run(world, f"{GOOD_Q} {HOLDS}"), "v1")
    valid(r)
    assert r["predicate"]["scope"]["coverage"] == "UNKNOWN"
    assert r["predicate"]["scope"]["excluded"] == [{"check": "work_claim", "module": "execution",
                                                    "reason": "unavailable", "detected": None}]


@pytest.mark.parametrize("kw, reason", [({"quotes": False}, "call_option"), ({"numbers": "off"}, "call_option"),
                                        ({"mandate": False}, "call_option")])
def test_an_option_of_the_call_is_its_own_reason(world, kw, reason):
    r = receipts.render(run(world, GOOD_Q, **kw), "v1")
    valid(r)
    assert reason in {e["reason"] for e in r["predicate"]["scope"]["excluded"]}
    assert r["predicate"]["scope"]["coverage"] == "PARTIAL"


def test_custom_checks_are_the_effective_scope(world):
    r = receipts.render(run(world, f"{GOOD_Q} {HOLDS} `⚓ pr:o/r#1=open`", checks=["pr_anchor", "quote"]), "v1")
    valid(r)
    scope = r["predicate"]["scope"]
    assert scope["requested"] == {"profile": "custom", "checks": ["quote", "pr_anchor"]}
    assert scope["effective"] == scope["executed"] == ["quote", "pr_anchor"]
    assert {f["check"] for f in r["predicate"]["verification"]["findings"]} == {"quote", "pr_anchor"}


@pytest.mark.parametrize("text, v0, v1", [
    (BAD_Q, "FAIL", "FAIL"),  # contradicted
    (GOOD_Q.replace(URL, "https://gone.example/p"), "GAPS", "GAPS"),  # missing evidence
    (f"{GOOD_Q} {HOLDS}", "PASS", "PASS"),
    ("Nothing to see here.", "EMPTY", "EMPTY"),
])
def test_v0_and_v1_agree_on_the_same_assessment(world, text, v0, v1):
    a = run(world, text)
    assert a.receipt["predicate"]["outcome"] == v0
    assert receipts.render(a, "v1")["predicate"]["verification"]["outcome"] == v1


def test_an_unrecognized_status_is_v0_gaps_and_v1_unknown(world, monkeypatch):
    from buddie import anchors
    original = anchors.check_one
    monkeypatch.setattr(anchors, "check_one", lambda *a, **k: dict(original(*a, **k), status="SIDEWAYS"))
    a = run(world, f"Done. {HOLDS}")
    assert a.receipt["predicate"]["outcome"] == "GAPS"
    r = receipts.render(a, "v1")
    valid(r)
    assert r["predicate"]["verification"]["outcome"] == "UNKNOWN"
    assert r["predicate"]["verification"]["counts"]["unrecognized"] == 1


# --- policy floors and the hook's selection -----------------------------------------------------------------------

def test_the_receipt_describes_what_ran_after_a_policy_floor_not_the_preset(world, monkeypatch):
    repo, tmp = world
    (repo / "buddie.toml").write_text('[verify]\nprofile = "research"\n[gates]\nnumbers = "off"\n', encoding="utf-8")
    place = tmp / "system" / "policy.toml"
    place.parent.mkdir()
    place.write_text('version = 1\n[gates]\nanchors = "block"\n', encoding="utf-8")
    monkeypatch.setattr(policy, "location", lambda: place)
    monkeypatch.setattr(policy, "protection_problem", lambda p: None)
    with policy.snapshot():
        ctx = resolved.resolve({"cwd": str(repo)})
        a = run(world, f"{GOOD_Q} {BROKEN}", selection=ctx.effective(), requested=ctx.profile)
    r = receipts.render(a, "v1")
    valid(r)
    scope = r["predicate"]["scope"]
    assert scope["requested"]["profile"] == "research" and "file_anchor" not in scope["requested"]["checks"]
    assert "file_anchor" in scope["executed"]  # the floor's class ran: the receipt says so
    reasons = {e["check"]: e["reason"] for e in scope["excluded"]}
    assert reasons["number"] == "gate_level" and reasons["work_claim"] == "profile"
    assert r["predicate"]["verification"]["outcome"] == "FAIL"


def test_the_receipt_version_changes_nothing_that_was_checked(world):
    text = f"{GOOD_Q}\n{BROKEN}"
    a = run(world, text, profile="research")
    before, first = copy.deepcopy(a.receipt), receipts.render(a, "v1")
    assert receipts.render(a, "v0") is a.receipt and a.receipt == before  # rendering reads, never writes
    assert receipts.render(a, "v1") == first  # and gives the same receipt each time
    # without a selection the Assessment's receipt-v0 is verify()'s, byte for byte
    assert run(world, text).receipt == verify.verify(text, repos=[world[0]], store=world[1] / "store", fetch=False,
                                                     now=NOW)


# --- provenance -------------------------------------------------------------------------------------------------

def test_provenance_in_v1_is_what_the_findings_carry(world, monkeypatch):
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
    text = "Merged. `⚓ pr:o/r#1=open`"
    own = receipts.render(run(world, text, github=effects.github_get), "v1")
    handed = receipts.render(run(world, text, github=forged), "v1")
    valid(own)
    valid(handed)
    assert own["predicate"]["evidence"]["provenance"]["collector_observed"] == 1
    assert handed["predicate"]["evidence"]["provenance"] == {"caller_supplied": 1, "agent_writable": 0,
                                                             "collector_observed": 0, "unknown": 0}
    assert own["predicate"]["verification"]["outcome"] == handed["predicate"]["verification"]["outcome"]


# --- the contract -------------------------------------------------------------------------------------------------

def test_v0_stays_the_default_and_v1_says_so_in_its_predicate_type(world):
    a = run(world, GOOD_Q)
    assert receipts.render(a) is a.receipt and a.receipt["predicateType"] == receipts.V0
    r = receipts.render(a, "v1")
    assert r["predicateType"] == receipts.V1 and r["subject"] == a.receipt["subject"]
    assert "contract_version" not in json.dumps(r)  # the version has one place: predicateType


@pytest.mark.parametrize("name", ["v2", "1", "", "V1", "receipt-v1", 1])
def test_an_unknown_receipt_version_is_an_error(world, name):
    with pytest.raises(receipts.UnknownReceiptVersion):
        receipts.render(run(world, GOOD_Q), name)


def test_serialization_is_deterministic_whatever_order_things_were_asked_in(world):
    a = run(world, f"{GOOD_Q} {HOLDS}", checks=["file_anchor", "quote"])
    b = run(world, f"{GOOD_Q} {HOLDS}", checks=["quote", "file_anchor", "quote"])
    assert receipts.dumps(receipts.render(a, "v1")) == receipts.dumps(receipts.render(b, "v1"))
    assert receipts.dumps(receipts.render(a, "v1")) == receipts.dumps(receipts.render(a, "v1"))


def test_the_schema_file_is_the_schema(world):
    on_disk = json.loads((ROOT / "docs" / "receipt-v1.schema.json").read_text(encoding="utf-8"))
    assert on_disk == receipts.SCHEMA and on_disk["$id"] == receipts.V1


def _mutations():
    def drop(path):
        def f(r):
            target = r
            for k in path[:-1]:
                target = target[k]
            del target[path[-1]]
        return f

    def put(path, value):
        def f(r):
            target = r
            for k in path[:-1]:
                target = target[k]
            target[path[-1]] = value
        return f
    return {
        "missing outcome": (drop(["predicate", "verification", "outcome"]), "schema"),
        "missing scope": (drop(["predicate", "scope"]), "schema"),
        "unknown outcome": (put(["predicate", "verification", "outcome"], "MOSTLY_FINE"), "schema"),
        "unknown coverage": (put(["predicate", "scope", "coverage"], "ALMOST"), "schema"),
        "unknown check": (put(["predicate", "scope", "executed"], ["quote", "llm_judge"]), "schema"),
        "wrong type": (put(["predicate", "scope", "executed"], "quote"), "schema"),
        "v0 type": (put(["predicateType"], receipts.V0), "schema"),
        "extra field": (put(["predicate", "verified_by_policy"], True), "schema"),
        "coverage says full": (put(["predicate", "scope", "coverage"], "FULL"), "rules"),
        "outcome says pass": (put(["predicate", "verification", "outcome"], "PASS"), "rules"),
        "unordered": (put(["predicate", "scope", "effective"], ["number", "quote"]), "rules"),
        "executed outside effective": (put(["predicate", "scope", "effective"], ["quote"]), "rules"),
        "promoted provenance": (put(["predicate", "evidence", "provenance", "collector_observed"], 5), "rules"),
        "counts": (put(["predicate", "verification", "counts", "supported"], 9), "rules"),
    }


@pytest.mark.parametrize("name", list(_mutations()))
def test_a_tampered_or_malformed_receipt_is_caught(world, name):
    mutate, by = _mutations()[name]
    r = receipts.render(run(world, f"{BAD_Q} {HOLDS}", profile="research"), "v1")
    valid(r)
    mutate(r)
    errors = validate(r, receipts.SCHEMA) + receipts.problems(r)
    assert errors, name
    if by == "rules":
        assert receipts.problems(r), name  # caught by the consistency rules, beyond the schema


def test_problems_also_catch_reasons_that_contradict_the_scope(world):
    r = receipts.render(run(world, GOOD_Q, profile="research"), "v1")
    r["predicate"]["scope"]["excluded"][0]["reason"] = "call_option"  # a check not in effective, "turned off by call"
    assert any("not in scope.effective" in p for p in receipts.problems(r))


# --- no secrets, no policy claims -------------------------------------------------------------------------------

def test_a_receipt_carries_no_token_or_environment(world, monkeypatch):
    monkeypatch.setenv("BUDDIE_GITHUB_TOKEN", "ghp_secret_token_value")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN", "plugin_secret_value")
    r = receipts.dumps(receipts.render(run(world, f"{GOOD_Q} `⚓ pr:o/r#1=open`"), "v1"))
    assert "secret" not in r and "VERBATIM_STORE" not in r and "policy" not in r


# --- the surfaces -------------------------------------------------------------------------------------------------

def test_cli_writes_v1_on_request_and_keeps_its_default_and_exit_code(world, capsys, tmp_path):
    repo, tmp = world
    report = tmp / "r.md"
    report.write_text(f"{BAD_Q}\n{HOLDS}\n", encoding="utf-8")
    common = ["verify", str(report), "--no-fetch", "--no-github", "--repo", str(repo), "--store", str(tmp / "store")]
    assert cli.main(common + ["--json", str(tmp / "v0.json")]) == 1
    default_out = capsys.readouterr().out
    assert json.loads((tmp / "v0.json").read_text(encoding="utf-8"))["predicateType"] == receipts.V0
    assert cli.main(common + ["--receipt", "v1", "--json", str(tmp / "v1.json")]) == 1  # the same exit code
    out = capsys.readouterr().out
    v1 = json.loads((tmp / "v1.json").read_text(encoding="utf-8"))
    valid(v1)
    assert out.splitlines()[:-1] == default_out.splitlines()[:-1]  # the same items; only the summary line differs
    assert out.splitlines()[-1].startswith("buddie FAIL (receipt-v1, coverage UNKNOWN")
    with pytest.raises(SystemExit) as got:
        cli.main(common + ["--receipt", "v2"])
    assert got.value.code == 2 and "unknown receipt version" in capsys.readouterr().err
    assert cli.main(["receipt-schema"]) == 0 and json.loads(capsys.readouterr().out) == receipts.SCHEMA


def test_mcp_returns_v1_only_when_asked(world):
    repo, tmp = world

    def call(**arguments):
        return mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "verify_report", "arguments": {"text": GOOD_Q, "repos": [str(repo)], "store": str(tmp / "store"),
                                                   "fetch": False, "github": False, **arguments}}})["result"]
    assert call()["structuredContent"]["predicateType"] == receipts.V0
    got = call(receipt="v1", profile="research")
    valid(got["structuredContent"])
    assert got["content"][0]["text"].startswith("buddie PASS (receipt-v1, coverage PARTIAL")
    bad = call(receipt="v2")
    assert bad["isError"] and "unknown receipt version" in json.dumps(bad)
    schema = next(t for t in mcp.TOOLS if t["name"] == "verify_report")["inputSchema"]["properties"]
    assert schema["receipt"]["enum"] == ["v0", "v1"] and schema["receipt"]["default"] == "v0"


def test_the_remote_server_keeps_v0(world):
    schema = next(t for t in remote.tools() if t["name"] == "verify_report")["inputSchema"]["properties"]
    assert "receipt" not in schema
    with pytest.raises(ValueError):
        remote.verify_report({"text": GOOD_Q, "receipt": "v1"})


def test_the_hook_and_the_journal_stay_on_v0():
    """The gate decides on its findings and receipt-v0; it never renders a v1, so the version cannot change a
    decision (and the 819 golden scenarios hold that)."""
    for name in ("hook", "journal"):
        source = (ROOT / "buddie" / f"{name}.py").read_text(encoding="utf-8")
        assert "receipts" not in source and "receipt-v1" not in source


# --- review follow-up: exclusion reasons agree with the requested selection --------------------------------------

def _gate_level_receipt(world):
    """research asked for, quote left on and number turned off by the levels (as the hook's effective selection)."""
    return receipts.render(run(world, f"{GOOD_Q} {HOLDS} `⚓ pr:o/r#1=open`",
                               selection=profiles.effective("research", ["quote"]),
                               requested=profiles.resolve("research")), "v1")


def _reason(r, check, reason):
    next(e for e in r["predicate"]["scope"]["excluded"] if e["check"] == check)["reason"] = reason


def test_a_requested_check_marked_profile_is_inconsistent(world):
    r = _gate_level_receipt(world)
    valid(r)
    _reason(r, "number", "profile")  # number was requested: what turned it off was the levels
    assert any("number" in p and "requested" in p for p in receipts.problems(r))


def test_an_unrequested_check_marked_gate_level_is_inconsistent(world):
    r = _gate_level_receipt(world)
    _reason(r, "pr_anchor", "gate_level")  # research never asked for pr_anchor: the profile left it out
    assert any("pr_anchor" in p and "requested" in p for p in receipts.problems(r))


def test_a_receipt_with_nothing_requested_cannot_exclude_by_profile(world):
    r = _gate_level_receipt(world)
    r["predicate"]["scope"]["requested"] = {"profile": None, "checks": None}  # nothing asked: everything requested
    assert any("pr_anchor" in p and "requested" in p for p in receipts.problems(r))


@pytest.mark.parametrize("mutate, needle", [
    (lambda s: s["requested"].update(checks=["number", "quote"]), "scope.requested.checks"),
    (lambda s: s["requested"].update(checks=["quote", "llm_judge"]), "scope.requested.checks"),
    (lambda s: s["requested"].update(profile=None), "scope.requested"),
    (lambda s: s["requested"].update(checks=None), "scope.requested"),
    (lambda s: s["excluded"].insert(0, {"check": "quote", "module": "sources", "reason": "call_option",
                                        "detected": 1}), "both executed and excluded"),
])
def test_inconsistent_requested_effective_and_excluded_scopes_are_caught(world, mutate, needle):
    r = _gate_level_receipt(world)
    mutate(r["predicate"]["scope"])
    assert any(needle in p for p in receipts.problems(r)), receipts.problems(r)


@pytest.mark.parametrize("kw", [{"profile": "developer"}, {"profile": "research"}, {"profile": "complete"},
                                {"profile": "custom", "modules": ["github"], "checks": ["quote"]}, {}])
def test_receipts_of_every_profile_hold_together(world, kw):
    valid(receipts.render(run(world, f"{GOOD_Q} {HOLDS} `⚓ pr:o/r#1=open`", **kw), "v1"))


def test_a_check_a_policy_floor_brings_back_is_not_a_profile_exclusion(world):
    """A floor puts into effective (and executed) a check the requested profile does not have: that is consistent,
    and nothing about it may read as excluded."""
    restored = profiles.effective("research", ["quote", "number", "file_anchor"])
    r = receipts.render(run(world, f"{GOOD_Q} {BROKEN}", selection=restored, requested=profiles.resolve("research")),
                        "v1")
    valid(r)
    scope = r["predicate"]["scope"]
    assert "file_anchor" in scope["executed"] and "file_anchor" not in scope["requested"]["checks"]
    assert "file_anchor" not in {e["check"] for e in scope["excluded"]}
