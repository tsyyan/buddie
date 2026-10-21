"""The internal contract (buddie/core.py) and its adapter (buddie/findings.py): every verdict has one typed meaning,
an unknown one is never support, and receipt-v0 comes out of the findings exactly as before."""
from __future__ import annotations

import ast
import itertools
import random
import subprocess
import sys
from pathlib import Path

import pytest

from buddie import core, findings as fnd, mandate
from buddie import verify as v
from buddie.core import Check, Decision, Fact, Outcome, Policy, Provenance, ReasonCode, Sufficiency
from buddie.verbatim import check, numbers

ROOT = Path(__file__).resolve().parents[1]
GAP, BLOCK = Policy(block_numbers=False), Policy(block_numbers=True)


# --- the core stands alone ---------------------------------------------------------------------------------------

def test_core_imports_only_the_standard_library():
    tree = ast.parse((ROOT / "buddie" / "core.py").read_text(encoding="utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert names <= {"__future__", "collections", "dataclasses", "enum"}
    loaded = subprocess.run([sys.executable, "-c", "import sys, buddie.core; "
                             "print(sorted(m for m in sys.modules if m.startswith('buddie')))"],
                            capture_output=True, text=True, cwd=ROOT, check=True).stdout
    assert loaded.strip() == "['buddie', 'buddie.core']"


def test_the_tables_cover_every_verdict_the_checkers_return():
    assert set(fnd.QUOTE_FACTS) == set(check.ORDER)
    assert set(fnd.NUMBER_FACTS) == set(numbers.RANK)
    assert set(fnd.STATUS_FACTS) == {mandate.HOLDS, mandate.BROKEN, mandate.UNCHECKABLE, mandate.UNSUPPORTED}
    assert set(fnd.REASONS) >= set(fnd.QUOTE_FACTS) | set(fnd.NUMBER_FACTS) | set(fnd.STATUS_FACTS)


# --- each class of result -----------------------------------------------------------------------------------------

QUOTES = {  # verdict: fact, reason, decision (either policy)
    "FOUND": (Fact.SUPPORTED, ReasonCode.FOUND, Decision.ALLOW),
    "FOUND_NORMALIZED": (Fact.SUPPORTED, ReasonCode.FOUND_NORMALIZED, Decision.ALLOW),
    "NOT_A_QUOTE": (Fact.NO_CLAIM, ReasonCode.NOT_A_CITATION, Decision.ALLOW),
    "HIDDEN_ONLY": (Fact.UNDETERMINED, ReasonCode.ONLY_HIDDEN, Decision.FLAG),
    "FOUND_IN_COPY": (Fact.UNDETERMINED, ReasonCode.ONLY_IN_COPY, Decision.FLAG),
    "UNCERTAIN": (Fact.UNDETERMINED, ReasonCode.AMBIGUOUS_MISS, Decision.FLAG),
    "SOURCE_UNAVAILABLE": (Fact.UNDETERMINED, ReasonCode.SOURCE_UNAVAILABLE, Decision.FLAG),
    "NO_SOURCE": (Fact.UNDETERMINED, ReasonCode.NO_SOURCE, Decision.FLAG),
    "NOT_FOUND": (Fact.CONTRADICTED, ReasonCode.NOT_IN_SOURCE, Decision.BLOCK),
}
NUMBERS = {  # verdict: fact, reason, decision with numbers="gap", decision with numbers="fail"
    "FOUND": (Fact.SUPPORTED, ReasonCode.FOUND, Decision.ALLOW, Decision.ALLOW),
    "FOUND_NORMALIZED": (Fact.SUPPORTED, ReasonCode.FOUND_NORMALIZED, Decision.ALLOW, Decision.ALLOW),
    "FOUND_ROUNDED": (Fact.SUPPORTED, ReasonCode.FOUND_NORMALIZED, Decision.ALLOW, Decision.ALLOW),
    "NO_CONTEXT": (Fact.UNDETERMINED, ReasonCode.VALUE_WITHOUT_CONTEXT, Decision.FLAG, Decision.FLAG),
    "UNCERTAIN": (Fact.UNDETERMINED, ReasonCode.AMBIGUOUS_MISS, Decision.FLAG, Decision.FLAG),
    "SOURCE_UNAVAILABLE": (Fact.UNDETERMINED, ReasonCode.SOURCE_UNAVAILABLE, Decision.FLAG, Decision.FLAG),
    "NOT_FOUND": (Fact.CONTRADICTED, ReasonCode.NOT_IN_SOURCE, Decision.FLAG, Decision.BLOCK),
}
SUFFICIENCY = {Fact.SUPPORTED: Sufficiency.SUFFICIENT, Fact.CONTRADICTED: Sufficiency.SUFFICIENT,
               Fact.NO_CLAIM: Sufficiency.SUFFICIENT, Fact.UNDETERMINED: Sufficiency.INSUFFICIENT,
               Fact.UNRECOGNIZED: Sufficiency.UNKNOWN}


@pytest.mark.parametrize("verdict", QUOTES)
def test_quote_verdicts(verdict):
    fact, reason, decision = QUOTES[verdict]
    f = fnd.quote({"verdict": verdict, "quote": "q", "line": 3})
    assert (f.check, f.verdict, f.fact, f.reason, f.sufficiency, f.line) == (
        Check.QUOTE, verdict, fact, reason, SUFFICIENCY[fact], 3)
    assert GAP.decide(f) is BLOCK.decide(f) is decision


@pytest.mark.parametrize("verdict", NUMBERS)
def test_number_verdicts(verdict):
    fact, reason, in_gap, in_fail = NUMBERS[verdict]
    f = fnd.number({"verdict": verdict, "text": "$3.4 billion"})
    assert (f.check, f.fact, f.reason, f.sufficiency) == (Check.NUMBER, fact, reason, SUFFICIENCY[fact])
    assert (GAP.decide(f), BLOCK.decide(f)) == (in_gap, in_fail)


ANCHORS = [  # anchor, its check
    ("data.txt#" + "a" * 12, Check.FILE_ANCHOR), ("data.txt@abcdef1", Check.COMMIT_ANCHOR),
    ("x.count=3", Check.FACT_ANCHOR), ("pr:o/r#1=open", Check.PR_ANCHOR), ("ci:o/r@abcdef1=success", Check.CI_ANCHOR),
    ("run:pytest -q => 3 passed", Check.RUN_ANCHOR), ("choice:abc123=№3", Check.CHOICE_ANCHOR),
    ("whatever text", Check.OTHER_ANCHOR)]


@pytest.mark.parametrize("anchor, kind", ANCHORS)
@pytest.mark.parametrize("status, fact, decision", [("HOLDS", Fact.SUPPORTED, Decision.ALLOW),
                                                    ("BROKEN", Fact.CONTRADICTED, Decision.BLOCK),
                                                    ("UNCHECKABLE", Fact.UNDETERMINED, Decision.FLAG)])
def test_anchor_statuses(anchor, kind, status, fact, decision):
    f = fnd.anchor({"anchor": anchor, "status": status, "line": 1, "why": "a person's words"})
    assert (f.check, f.fact, f.message) == (kind, fact, "a person's words")
    assert GAP.decide(f) is decision
    if kind is Check.FACT_ANCHOR:
        assert f.reason is ReasonCode.NOT_COMPUTED
    elif kind is Check.OTHER_ANCHOR:
        assert f.reason is ReasonCode.NOT_AN_ANCHOR
    else:
        assert f.reason is fnd.REASONS[status]


@pytest.mark.parametrize("status, fact", [("HOLDS", Fact.SUPPORTED), ("BROKEN", Fact.CONTRADICTED),
                                          ("UNSUPPORTED", Fact.UNDETERMINED), ("UNCHECKABLE", Fact.UNDETERMINED)])
def test_work_claim_statuses(status, fact):
    f = fnd.work_claim({"kind": "done", "status": status, "line": 2})
    assert (f.check, f.subject, f.fact, f.reason) == (Check.WORK_CLAIM, "done", fact, fnd.REASONS[status])


# --- unknown verdicts ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("make", [lambda: fnd.quote({"verdict": "FOUND_SOMEHOW"}),
                                  lambda: fnd.number({"verdict": "FOUND_SOMEHOW"}),
                                  lambda: fnd.anchor({"anchor": "data.txt#" + "a" * 12, "status": "PROBABLY"}),
                                  lambda: fnd.work_claim({"kind": "done", "status": "PROBABLY"})])
def test_an_unknown_verdict_is_never_support(make):
    f = make()
    assert (f.fact, f.sufficiency, f.reason) == (Fact.UNRECOGNIZED, Sufficiency.UNKNOWN, ReasonCode.UNKNOWN_VERDICT)
    assert GAP.decide(f) is BLOCK.decide(f) is Decision.FLAG and f.evidence == ()
    supported = fnd.quote({"verdict": "FOUND"})
    assert core.outcome([supported, f]) is Outcome.UNKNOWN and core.v0_outcome([supported, f]) == "GAPS"


# --- mixed outcomes, and what was not checked ---------------------------------------------------------------------

def _f(verdict, kind=fnd.quote):
    return kind({"verdict": verdict, "status": verdict, "anchor": "data.txt#" + "a" * 12, "kind": "done"})


@pytest.mark.parametrize("verdicts, strict, v0", [
    (["FOUND", "FOUND_NORMALIZED", "NOT_A_QUOTE"], Outcome.PASS, "PASS"),
    (["FOUND", "SOURCE_UNAVAILABLE"], Outcome.GAPS, "GAPS"),
    (["FOUND", "NOT_FOUND", "SOURCE_UNAVAILABLE"], Outcome.FAIL, "FAIL"),
    (["NOT_FOUND", "WHO_KNOWS"], Outcome.FAIL, "FAIL"),           # a block outranks the unknown
    (["SOURCE_UNAVAILABLE", "WHO_KNOWS"], Outcome.UNKNOWN, "GAPS"),  # the unknown outranks a gap
    ([], Outcome.UNKNOWN, "EMPTY"),                              # nothing checked is not a pass
])
def test_mixed_outcomes(verdicts, strict, v0):
    found = [_f(x) for x in verdicts]
    assert core.outcome(found) is strict and core.v0_outcome(found) == v0


def test_a_check_that_was_off_keeps_the_strict_outcome_from_passing():
    found = [_f("FOUND")]
    off = fnd.coverage(found, quotes=False, numbers="gap", mandate_off=False, mandate_config=True)
    assert [s.what for s in off.capabilities_off] == ["quotes", "numbers"]
    assert core.outcome(found, off) is Outcome.GAPS and core.v0_outcome(found) == "PASS"  # v0 never said it
    on = fnd.coverage(found, quotes=True, numbers="gap", mandate_off=False, mandate_config=False, short_quotes=2)
    assert on.capabilities_off == () and core.outcome(found, on) is Outcome.PASS
    assert [(s.what, s.count) for s in on.skipped] == [("work_claims", None), ("short_quotes", 2)]
    assert on.checked == {Check.QUOTE: 1}


def test_a_contradicted_number_blocks_only_by_policy():
    found = [_f("FOUND"), _f("NOT_FOUND", fnd.number)]
    assert found[1].fact is Fact.CONTRADICTED  # the fact does not change with the policy
    assert core.outcome(found, policy=GAP) is Outcome.GAPS and core.outcome(found, policy=BLOCK) is Outcome.FAIL


# --- evidence and its provenance ----------------------------------------------------------------------------------

def test_evidence_says_only_what_is_known():
    snap = fnd.quote({"verdict": "FOUND", "url": "https://e.example/a", "sha256": "ab" * 32,
                      "provenance": "publisher", "fetched_at": "2026-10-21T00:00:00Z"}).evidence
    # a digest names the bytes; the store's record says publisher, which nobody here vouches for
    assert snap == (core.EvidenceRef("snapshot", "https://e.example/a", Provenance.UNKNOWN, "ab" * 32, "publisher",
                                     "2026-10-21T00:00:00Z"),)
    assert fnd.quote({"verdict": "SOURCE_UNAVAILABLE", "url": "https://e.example/a"}).evidence == ()
    holds = {"status": "HOLDS", "repo": "/r"}
    assert fnd.anchor({"anchor": "data.txt#" + "a" * 12, **holds}).evidence[0].provenance is Provenance.AGENT_WRITABLE
    assert fnd.anchor({"anchor": "data.txt@abcdef1", **holds}).evidence[0].provenance is Provenance.AGENT_WRITABLE
    assert fnd.anchor({"anchor": "pr:o/r#1=open", "status": "BROKEN"}).evidence[0].provenance \
        is Provenance.COLLECTOR_OBSERVED
    assert fnd.anchor({"anchor": "run:x => y", "status": "HOLDS"}).evidence[0].provenance is Provenance.CALLER_SUPPLIED
    for anchor in ("data.txt#" + "a" * 12, "pr:o/r#1=open", "x.count=3"):  # not reached: no evidence is invented
        assert fnd.anchor({"anchor": anchor, "status": "UNCHECKABLE"}).evidence == ()
    assert fnd.anchor({"anchor": "x.count=3", "status": "HOLDS"}).evidence == ()  # fact=: buddie has no source


# --- receipt-v0 is what it was ------------------------------------------------------------------------------------

def _v0_before(quotes, anchors, claims, nums, mode):
    """verify.outcome as of #22-#24, for comparison."""
    qm = {"FOUND": "H", "FOUND_NORMALIZED": "H", "NOT_A_QUOTE": "H", "NOT_FOUND": "M"}
    nm = {"FOUND": "H", "FOUND_NORMALIZED": "H", "FOUND_ROUNDED": "H", "NOT_FOUND": "M"}
    if not quotes and not anchors and not claims and not nums:
        return "EMPTY"
    if any(qm.get(q["verdict"], "G") == "M" for q in quotes) or any(a["status"] == "BROKEN" for a in anchors) \
            or any(c["status"] == "BROKEN" for c in claims) \
            or mode == "fail" and any(nm.get(n["verdict"], "G") == "M" for n in nums):
        return "FAIL"
    if any(qm.get(q["verdict"], "G") == "G" for q in quotes) or any(a["status"] == "UNCHECKABLE" for a in anchors) \
            or any(c["status"] in ("UNSUPPORTED", "UNCHECKABLE") for c in claims) \
            or any(nm.get(n["verdict"], "G") != "H" for n in nums):
        return "GAPS"
    return "PASS"


def test_v0_outcome_matches_the_old_rule_on_every_mix():
    rng = random.Random(25)
    qv, nv = [*check.ORDER, "NEW_Q"], [*numbers.RANK, "NEW_N"]
    av, cv = ["HOLDS", "BROKEN", "UNCHECKABLE"], ["HOLDS", "BROKEN", "UNSUPPORTED", "UNCHECKABLE"]
    for _ in range(3000):
        qs = [{"verdict": rng.choice(qv)} for _ in range(rng.randint(0, 3))]
        ns = [{"verdict": rng.choice(nv)} for _ in range(rng.randint(0, 3))]
        an = [{"anchor": rng.choice(ANCHORS)[0], "status": rng.choice(av)} for _ in range(rng.randint(0, 2))]
        cs = [{"kind": "done", "status": rng.choice(cv)} for _ in range(rng.randint(0, 2))]
        for mode in ("gap", "fail"):
            assert v.outcome(qs, an, cs, ns, mode) == _v0_before(qs, an, cs, ns, mode), (qs, ns, an, cs, mode)
    # the one change: a status no checker returns was a PASS by falling through, and is now a gap
    odd = [{"anchor": "data.txt#" + "a" * 12, "status": "PROBABLY"}]
    assert _v0_before([], odd, [], [], "gap") == "PASS" and v.outcome([], odd) == "GAPS"


def test_assess_gives_the_receipt_verify_gives(tmp_path):
    text = "Done. `⚓ data.txt#" + "0" * 12 + "` and `⚓ x.count=3`\n"
    (tmp_path / "data.txt").write_text("hello\n", encoding="utf-8")
    receipt, found, covered = v.assess(text, repos=[tmp_path], quotes=False, now="2026-10-21T00:00:00Z")
    assert receipt == v.verify(text, repos=[tmp_path], quotes=False, now="2026-10-21T00:00:00Z")
    pred = receipt["predicate"]
    assert set(pred) == {"tool", "checked_at", "outcome", "line", "summary", "notes", "unanchored", "quote_backed",
                         "prose_work", "prose_lines", "blocking", "gaps", "quotes", "numbers", "anchors", "mandate"}
    assert pred["outcome"] == "FAIL" and receipt["predicateType"].endswith("#receipt-v0")
    assert [(f.check, f.fact, f.reason) for f in found] == [
        (Check.FILE_ANCHOR, Fact.CONTRADICTED, ReasonCode.BROKEN),
        (Check.FACT_ANCHOR, Fact.UNDETERMINED, ReasonCode.NOT_COMPUTED)]
    assert core.outcome(found, covered) is Outcome.FAIL
    assert [s.what for s in covered.capabilities_off] == ["quotes", "numbers"]


def test_verify_keeps_its_public_signature():
    """verify() as it was on main before #25: every parameter but the text keyword-only, same defaults and types."""
    import inspect
    sig = inspect.signature(v.verify)
    kw = inspect.Parameter.KEYWORD_ONLY
    expected = [("text", inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty, "str"),
                ("name", kw, "report", "str"), ("repos", kw, None, "list[Path] | None"),
                ("store", kw, None, inspect.Parameter.empty), ("fetch", kw, True, "bool"),
                ("access", kw, None, "str | None"), ("quotes", kw, True, "bool"), ("now", kw, None, "str | None"),
                ("mandate", kw, True, "dict | None | bool"), ("rev", kw, None, "str | None"),
                ("github", kw, None, inspect.Parameter.empty), ("transcript", kw, None, "str | None"),
                ("numbers", kw, "gap", "str")]
    assert [(p.name, p.kind, p.default, p.annotation) for p in sig.parameters.values()] == expected
    assert sig.return_annotation == "dict"
    assert list(inspect.signature(v.assess).parameters) == [name for name, *_ in expected]
