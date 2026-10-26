"""Verification feedback v1, the bounded repair adapter and the decision trace (docs/feedback.md).

Every case runs offline: a snapshot store in a temp directory, a repo with one file, canned GitHub answers. No model
is called and nothing is fetched."""
from __future__ import annotations

import copy
import json
import urllib.request
from pathlib import Path

import pytest
from test_receipts import validate

from buddie import cli, feedback as fb, receipts, repair, trace as tr, verify
from buddie.verbatim.store import Store

ROOT = Path(__file__).resolve().parents[1]
URL = "https://news.example.org/outage"
PAGE = ("<p>" + "Background paragraph about the service. " * 40 + "</p><p>The company said the outage began at 14:59 "
        "UTC and was resolved within two hours.</p>").encode()
QUOTE = "the outage began at 14:59 UTC and was resolved within two hours"
GOOD_Q = f"The vendor wrote that “{QUOTE}” ([r]({URL}))."
BAD_Q = GOOD_Q.replace("14:59", "14:58")
WORSE_Q = GOOD_Q.replace("14:59", "14:57")
GONE_Q = GOOD_Q.replace(URL, "https://gone.example/p")
NOW = "2026-10-22T00:00:00Z"
HEAD = "dbf390f479dee4806b67d6d62d90aeec7fc12843"
API = {"/repos/o/r/pulls/55": {"state": "open", "merged": False, "draft": False, "head": {"sha": HEAD}}}


@pytest.fixture
def world(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "data.txt").write_bytes(b"hello\n")
    Store(tmp_path / "store").add(URL, PAGE, content_type="text/html")
    for k, v in (("BUDDIE_FETCH", "0"), ("BUDDIE_GITHUB", "0"), ("BUDDIE_LOG", str(tmp_path / "hook.jsonl")),
                 ("VERBATIM_STORE", str(tmp_path / "store"))):
        monkeypatch.setenv(k, v)
    return repo, tmp_path


def assess(world, text, **kw):
    """An independent verify run on `text`, in this process (what a chain takes)."""
    repo, tmp = world
    return repair.reverify(text, **{"repos": [repo], "store": tmp / "store", "fetch": False, "now": NOW,
                                    "github": API.get, **kw})


def check(world, text, **kw):
    """The receipt-v1 of assess()."""
    return receipts.v1(assess(world, text, **kw))


def anchor(world, ok=True):
    import hashlib
    h = hashlib.sha256(b"hello\n").hexdigest()[:12] if ok else "0" * 12
    return f"`⚓ data.txt#{h}`"


def by_condition(feedback):
    return [f["condition"] for f in feedback["findings"]]


def run_once(world, original, corrected, *, limit=1, execution="none", **kw):
    records, first = tr.start(assess(world, original, **kw), iteration_limit=limit)
    got = repair.resolve(records, first, repair.submission(first, original, corrected, execution=execution),
                         original=original, corrected=corrected, assessment=assess(world, corrected, **kw))
    return records, first, got


# --- 1. feedback from an actual receipt ---------------------------------------------------------------------------

def test_feedback_is_made_from_an_actual_receipt(world):
    text = f"{BAD_Q}\n\nThe file is as stated. {anchor(world)}"
    receipt = check(world, text)
    got = fb.from_receipt(receipt)
    assert validate(got, fb.SCHEMA) == [] and fb.problems(got, receipt) == []
    assert got["source_receipt"]["outcome"] == "FAIL" == receipt["predicate"]["verification"]["outcome"]
    assert got["source_subject_digest"] == fb.text_digest(text)
    assert by_condition(got) == ["failed", "verified"]
    assert got["disposition"] == "repair_requested" and got["iteration"] == 0 and got["iteration_limit"] == 1
    [action] = got["recommended_actions"]
    assert action["operation"] == "correct_claim" and action["target"] == {
        "check": "quote", "line": 1, "subject": BAD_Q[BAD_Q.index("the outage"):BAD_Q.index("”")],
        "extent": "paragraph"}
    assert action["idempotent"] is True and action["preserve_valid_content"] is True
    # each finding keeps the receipt's identity, status and evidence, none added
    for entry, original in zip(got["findings"], receipt["predicate"]["verification"]["findings"]):
        assert entry["finding_id"] == fb.finding_id(entry["index"], original)
        for key in ("check", "verdict", "fact", "reason", "decision", "line", "subject", "message"):
            assert entry[key] == original[key]
        assert [{k: v for k, v in e.items() if k != "resolution"} for e in entry["evidence"]] == original["evidence"]
    assert got["findings"][1]["actionable"] is False and got["findings"][1]["not_actionable_reason"] == "verified"


def test_the_checked_in_schema_is_the_module_s():
    on_disk = json.loads((ROOT / "docs" / "feedback-v1.schema.json").read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(fb.SCHEMA))


# --- 2-5. each condition is its own -------------------------------------------------------------------------------

def test_missing_evidence(world):
    got = fb.from_receipt(check(world, GONE_Q))
    [f] = got["findings"]
    assert (f["condition"], f["reason"], f["evidence_state"]) == ("missing_evidence", "source_unavailable", "absent")
    assert got["recommended_actions"][0]["operation"] == "cite_readable_source"
    assert got["source_receipt"]["outcome"] == "GAPS"


def test_corrupted_evidence_is_refused_not_judged(world):
    repo, tmp = world
    store = Store(tmp / "store")
    (tmp / "store" / "snapshots" / store.latest(URL)["sha256"]).write_bytes(b"not the page")
    with pytest.raises(ValueError, match="does not match its hash"):  # verify refuses corrupted bytes (as before)
        check(world, GOOD_Q)
    (tmp / "store" / "snapshots" / store.latest(URL)["sha256"]).write_bytes(PAGE)  # whole again, to tamper with
    receipt = check(world, GOOD_Q)
    receipt["predicate"]["verification"]["findings"][0]["evidence"][0]["digest"] = "zz" * 32
    with pytest.raises(fb.InvalidReceipt, match="corrupted evidence reference"):
        fb.from_receipt(receipt)


def test_an_evidence_hash_mismatch_is_invalid_evidence(world):
    got = fb.from_receipt(check(world, f"The file is as stated. {anchor(world, ok=False)}"))
    [f] = got["findings"]
    assert (f["condition"], f["verdict"], f["fact"]) == ("invalid_evidence", "BROKEN", "contradicted")
    assert got["recommended_actions"][0]["operation"] == "refresh_anchor"


def test_failed_and_inconclusive_and_unavailable_are_apart(world):
    pr = check(world, "Merged: `⚓ pr:o/r#55=merged`")
    assert by_condition(fb.from_receipt(pr)) == ["failed"]
    offline = check(world, "Merged: `⚓ pr:o/r#55=merged`", github=None)
    got = fb.from_receipt(offline)
    assert by_condition(got) == ["unavailable"] and got["findings"][0]["not_actionable_reason"] == "verifier_unavailable"
    assert got["disposition"] == "not_actionable" and got["recommended_actions"] == []
    entry = {"check": "quote", "fact": "undetermined", "reason": "ambiguous_miss"}
    assert fb.condition(entry) == "inconclusive"
    assert fb.condition({**entry, "fact": "unrecognized", "reason": "unknown_verdict"}) == "unavailable"


def test_empty_and_gaps_stay_what_they_are(world):
    empty = fb.from_receipt(check(world, "Nothing to see here."))
    assert empty["source_receipt"]["outcome"] == "EMPTY" and empty["disposition"] == "nothing_verified"
    assert empty["findings"] == [] and empty["recommended_actions"] == []
    gaps = fb.from_receipt(check(world, "Merged: `⚓ pr:o/r#55=merged`", github=None))
    assert gaps["source_receipt"]["outcome"] == "GAPS" and gaps["disposition"] == "not_actionable"
    # a repair that removes every claim is EMPTY, never verified
    _, _, got = run_once(world, GONE_Q, "We could not confirm the vendor's statement.")
    assert got.decision["outcome"] == "EMPTY" and got.feedback["disposition"] == "nothing_verified"
    assert list(got.decision["resolved"].values()) == ["removed"]


# --- 6-8. correction, failed correction, no change ----------------------------------------------------------------

def test_a_successful_correction_is_verified_by_a_new_receipt(world):
    records, first, got = run_once(world, BAD_Q, GOOD_Q)
    assert got.decision["status"] == "accepted" and got.decision["outcome"] == "PASS"
    assert got.feedback["disposition"] == "verified" and got.feedback["iteration"] == 1
    assert got.feedback["parent"] == first["feedback_id"] and got.feedback["chain"] == first["chain"]
    assert list(got.decision["resolved"].values()) == ["corrected"]
    assert [r["kind"] for r in got.records] == ["verification", "feedback", "submission", "reverification",
                                                "decision", "feedback"]
    state = tr.replay(got.records)
    assert state.terminal and state.disposition == "verified" and records == got.records[:2]  # records appended


def test_a_failed_correction_spends_the_budget(world):
    _, _, got = run_once(world, BAD_Q, WORSE_Q)
    assert got.decision["status"] == "accepted" and got.decision["outcome"] == "FAIL"
    assert got.feedback["disposition"] == "budget_exhausted" and got.feedback["recommended_actions"] == []
    assert list(got.decision["resolved"].values()) == ["still_open"]
    assert got.feedback["source_receipt"]["outcome"] == "FAIL"


def test_an_unchanged_text_is_no_repair(world):
    records, first = tr.start(assess(world, BAD_Q))
    sub = repair.submission(first, BAD_Q, BAD_Q, execution="succeeded")  # what the agent says changes nothing
    got = repair.resolve(records, first, sub, original=BAD_Q, corrected=BAD_Q, assessment=assess(world, BAD_Q))
    assert got.decision["rejection"] == "unchanged_artifact" and got.feedback["disposition"] == "budget_exhausted"
    assert [r["kind"] for r in got.records][2:] == ["submission", "decision", "feedback"]  # no reverification
    assert got.records[2]["body"]["asserted"]["execution"] == "succeeded"
    assert got.records[2]["body"]["observed"]["status"] == "rejected"


def test_a_false_digest_is_the_agent_s_assertion_and_rejected(world):
    records, first = tr.start(assess(world, BAD_Q))
    sub = {**repair.submission(first, BAD_Q, GOOD_Q), "artifact_after": "0" * 64}
    got = repair.resolve(records, first, sub, original=BAD_Q, corrected=GOOD_Q, assessment=assess(world, GOOD_Q))
    assert got.decision["rejection"] == "assertion_mismatch" and got.feedback["disposition"] == "budget_exhausted"


# --- 9-10. patch scope ---------------------------------------------------------------------------------------------

def test_a_field_outside_the_submission_contract_is_refused(world):
    records, first = tr.start(assess(world, BAD_Q))
    for extra in ({"disposition": "verified"}, {"outcome": "PASS"}, {"iteration_limit": 3}):
        sub = {**repair.submission(first, BAD_Q, GOOD_Q), **extra}
        with pytest.raises(repair.SubmissionError) as error:
            repair.resolve(records, first, sub, original=BAD_Q, corrected=GOOD_Q, assessment=assess(world, GOOD_Q))
        assert error.value.code == "unauthorized_field"
    assert tr.replay(records).disposition == "repair_requested"  # nothing spent


def test_a_change_outside_the_scope_is_rejected(world):
    original = f"Intro line.\n\n{BAD_Q}"
    corrected = f"Intro line, rewritten.\n\n{GOOD_Q}"
    _, _, got = run_once(world, original, corrected)
    assert got.decision["rejection"] == "out_of_scope" and got.feedback["disposition"] == "budget_exhausted"
    assert got.records[2]["body"]["observed"]["out_of_scope"] == [1]


def test_verified_content_cannot_be_changed(world):
    ok, broken = anchor(world), anchor(world, ok=False)
    original = f"{GOOD_Q}\n\nThe file is as stated. {ok}\nThe other file too. {broken}"
    # the verified anchor's line is outside the scope
    _, _, got = run_once(world, original, original.replace(f"stated. {ok}", "stated.").replace(broken, ok))
    assert got.decision["rejection"] == "out_of_scope"
    # a verified claim on the line being corrected must stay
    original = f"Both hold: {ok} and {broken}"
    _, _, got = run_once(world, original, "Both hold: (see the file)")
    assert got.decision["rejection"] == "verified_content_changed"
    _, _, got = run_once(world, original, f"Both hold: {ok}")
    assert got.decision["status"] == "accepted" and got.feedback["disposition"] == "verified"


# --- 11-13. budget, ambiguous execution, duplicates ---------------------------------------------------------------

def test_the_budget_is_finite_and_ends_in_a_terminal_disposition(world):
    records, first = tr.start(assess(world, BAD_Q), iteration_limit=2)
    one = repair.resolve(records, first, repair.submission(first, BAD_Q, WORSE_Q), original=BAD_Q,
                         corrected=WORSE_Q, assessment=assess(world, WORSE_Q))
    assert one.feedback["disposition"] == "repair_requested" and one.feedback["iteration"] == 1
    third = WORSE_Q.replace("14:57", "14:56")
    two = repair.resolve(one.records, one.feedback, repair.submission(one.feedback, WORSE_Q, third),
                         original=WORSE_Q, corrected=third, assessment=assess(world, third))
    assert two.feedback["disposition"] == "budget_exhausted" and two.feedback["iteration"] == 2
    with pytest.raises(repair.SubmissionError) as error:
        repair.resolve(two.records, two.feedback, repair.submission(two.feedback, third, GOOD_Q),
                       original=third, corrected=GOOD_Q, assessment=assess(world, GOOD_Q))
    assert error.value.code == "loop_closed"
    for bad in (0, 4, True, "1", None):
        with pytest.raises(ValueError):
            fb.from_receipt(check(world, BAD_Q), iteration_limit=bad)


def test_a_rejected_submission_s_next_feedback_is_the_receipt_s_next_iteration(world):
    source = assess(world, BAD_Q)
    receipt = receipts.v1(source)
    records, first = tr.start(source, iteration_limit=2)
    got = repair.resolve(records, first, repair.submission(first, BAD_Q, BAD_Q), original=BAD_Q, corrected=BAD_Q)
    assert got.decision["rejection"] == "unchanged_artifact" and got.feedback["disposition"] == "repair_requested"
    assert got.feedback == fb.from_receipt(receipt, iteration=1, iteration_limit=2, parent=first["feedback_id"],
                                           chain=first["chain"])
    assert fb.problems(got.feedback, receipt) == [] and tr.replay(got.records).iteration == 1


def test_an_unknown_external_outcome_asks_for_reconciliation(world):
    original = "Merged: `⚓ pr:o/r#55=merged`"
    first = fb.from_receipt(check(world, original))
    [action] = first["recommended_actions"]
    assert action["operation"] == "reconcile_external_state" and action["idempotent"] is False
    assert any("Do not repeat" in r for r in action["requirements"])
    _, _, got = run_once(world, original, "Merged: `⚓ pr:o/r#55=closed`", execution="unknown")
    assert got.feedback["disposition"] == "reconciliation_required" and got.feedback["recommended_actions"] == []
    # the same text with execution "failed" is an ordinary failed repair, and "unknown" that verifies is verified
    _, _, failed = run_once(world, original, "Merged: `⚓ pr:o/r#55=closed`", execution="failed")
    assert failed.feedback["disposition"] == "budget_exhausted"
    _, _, observed = run_once(world, original, "Still open: `⚓ pr:o/r#55=open`", execution="unknown")
    assert observed.feedback["disposition"] == "verified"


def test_a_repeated_submission_spends_nothing(world):
    records, first, got = run_once(world, BAD_Q, WORSE_Q, limit=2)
    sub = repair.submission(first, BAD_Q, WORSE_Q)
    with pytest.raises(repair.SubmissionError) as error:
        repair.resolve(got.records, first, sub, original=BAD_Q, corrected=WORSE_Q, assessment=assess(world, WORSE_Q))
    assert error.value.code == "duplicate_submission" and error.value.decision == got.decision
    assert tr.replay(got.records).iteration == 1
    # the same receipt gives the same feedback: a duplicate feedback is the same id, never a second chain step
    again_records, again = tr.start(assess(world, BAD_Q), iteration_limit=2)
    assert again == first and again_records == records


# --- 14-15. determinism and replay --------------------------------------------------------------------------------

def test_serialization_is_deterministic(world):
    a, b = fb.from_receipt(check(world, BAD_Q)), fb.from_receipt(check(world, BAD_Q))
    assert fb.dumps(a) == fb.dumps(b) and a["feedback_id"] == fb.feedback_id(a)
    assert fb.dumps(a) == json.dumps(a, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    _, _, one = run_once(world, BAD_Q, GOOD_Q)
    _, _, two = run_once(world, BAD_Q, GOOD_Q)
    assert tr.dumps(one.records) == tr.dumps(two.records)
    assert tr.loads(tr.dumps(one.records)) == one.records


def test_the_trace_replays_and_refuses_any_change(world):
    _, _, got = run_once(world, BAD_Q, GOOD_Q)
    records = tr.loads(tr.dumps(got.records))
    state = tr.replay(records)
    assert (state.iteration, state.disposition, state.terminal) == (1, "verified", True)
    assert [d["outcome"] for d in state.decisions] == ["PASS"]
    tampered = copy.deepcopy(list(records))
    tampered[3]["body"]["outcome"] = "FAIL"
    with pytest.raises(tr.TraceError, match="changed"):
        tr.replay(tampered)
    with pytest.raises(tr.TraceError, match="sequence"):
        tr.replay(records[:2] + records[3:])
    with pytest.raises(tr.TraceError):
        tr.replay(records[:3])  # a submission with no decision
    # a record re-hashed after the change still does not replay: the next record's parent names the old one
    rehashed = copy.deepcopy(list(records))
    rehashed[3]["body"]["outcome"] = "FAIL"
    rehashed[3]["record_id"] = tr.record_id(rehashed[3])
    with pytest.raises(tr.TraceError, match="sequence"):
        tr.replay(rehashed)
    # nothing follows a terminal feedback
    with pytest.raises(tr.TraceError):
        tr.replay(tr.append(records, "submission", 1, {"feedback_id": state.feedback_id}))


def test_records_of_another_chain_do_not_mix(world):
    _, _, one = run_once(world, BAD_Q, GOOD_Q)
    other, other_first = tr.start(assess(world, GONE_Q))
    with pytest.raises(tr.TraceError):
        tr.replay(other + one.records[2:])
    foreign = {**one.records[2], "seq": 2, "parent": other[-1]["record_id"]}  # in sequence, of the other chain
    foreign["record_id"] = tr.record_id(foreign)
    with pytest.raises(tr.TraceError, match="another chain"):
        tr.replay((*other, foreign))
    with pytest.raises(repair.SubmissionError) as error:
        repair.resolve(other, fb.from_receipt(check(world, BAD_Q)),
                       repair.submission(fb.from_receipt(check(world, BAD_Q)), BAD_Q, GOOD_Q),
                       original=BAD_Q, corrected=GOOD_Q, assessment=assess(world, GOOD_Q))
    assert error.value.code == "feedback_mismatch"


# --- 16. compatibility ---------------------------------------------------------------------------------------------

def test_existing_interfaces_are_unchanged(world, tmp_path, capsys):
    repo, tmp = world
    kw = {"repos": [repo], "store": tmp / "store", "fetch": False, "now": NOW}
    a = verify.assessment(BAD_Q, **kw)
    v0, v1 = copy.deepcopy(receipts.render(a)), copy.deepcopy(receipts.render(a, "v1"))
    fb.from_assessment(a)
    assert receipts.render(a) == v0 == verify.verify(BAD_Q, **kw) and receipts.render(a, "v1") == v1
    with pytest.raises(fb.InvalidReceipt, match="receipt-v1"):
        fb.from_receipt(v0)  # receipt-v0 has no typed findings: no feedback is guessed from it
    path = tmp_path / "r.json"
    path.write_text(receipts.dumps(v1), encoding="utf-8")
    assert cli.main(["feedback", str(path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == fb.from_receipt(v1)
    path.write_text(receipts.dumps(v0), encoding="utf-8")
    assert cli.main(["feedback", str(path)]) == 2


# --- 17. the evidence boundary ------------------------------------------------------------------------------------

def test_feedback_and_repair_read_no_evidence_and_the_trace_carries_none(world, monkeypatch):
    repo, tmp = world
    original, corrected = f"{BAD_Q} {anchor(world)}", f"{GOOD_Q} {anchor(world)}"
    receipt, after = assess(world, original), assess(world, corrected)

    def refuse(*a, **k):
        raise AssertionError("feedback reached for evidence")
    for target, name in ((urllib.request, "urlopen"), (Store, "read"), (Store, "fetch"), (verify, "assessment")):
        monkeypatch.setattr(target, name, refuse)
    records, first = tr.start(receipt)
    got = repair.resolve(records, first, repair.submission(first, original, corrected), original=original,
                         corrected=corrected, assessment=after)
    assert got.feedback["disposition"] == "verified"
    dumped = tr.dumps(got.records)
    for private in (QUOTE, "14:58", "Background paragraph", str(repo), str(tmp), URL, "data.txt"):
        assert private not in dumped
    assert "Background paragraph" not in fb.dumps(first)  # the page's bytes never enter feedback, only references


# --- 18. forged and mismatched references -------------------------------------------------------------------------

def test_forged_or_mismatched_references_are_refused(world):
    receipt = check(world, BAD_Q)
    records, first = tr.start(assess(world, BAD_Q))
    # a feedback changed after it was made
    forged = copy.deepcopy(first)
    forged["source_receipt"]["outcome"] = "PASS"
    assert fb.problems(forged) and fb.problems(first, receipt) == []
    with pytest.raises(repair.SubmissionError) as error:
        repair.resolve(records, forged, repair.submission(forged, BAD_Q, GOOD_Q), original=BAD_Q,
                       corrected=GOOD_Q, assessment=assess(world, GOOD_Q))
    assert error.value.code == "forged_feedback"
    # re-hashed so it holds together alone, it is still not this receipt's feedback, nor the chain's
    forged["feedback_id"] = fb.feedback_id(forged)
    assert fb.problems(forged) == [] and fb.problems(forged, receipt)
    with pytest.raises(repair.SubmissionError):
        repair.resolve(records, forged, repair.submission(forged, BAD_Q, GOOD_Q), original=BAD_Q,
                       corrected=GOOD_Q, assessment=assess(world, GOOD_Q))
    assert fb.problems(first, check(world, GONE_Q))  # another receipt
    # an original text that is not the feedback's
    with pytest.raises(repair.SubmissionError) as error:
        repair.resolve(records, first, repair.submission(first, GONE_Q, GOOD_Q), original=GONE_Q,
                       corrected=GOOD_Q, assessment=assess(world, GOOD_Q))
    assert error.value.code == "artifact_mismatch"

    def attempt(a):
        return repair.resolve(records, first, repair.submission(first, BAD_Q, GOOD_Q), original=BAD_Q,
                              corrected=GOOD_Q, assessment=a).decision["rejection"]
    assert attempt(None) == "reverification_missing"
    assert attempt(assess(world, f"{GOOD_Q} ")) == "receipt_mismatch"  # a check of another text
    assert attempt(assess(world, GOOD_Q, profile="developer")) == "weaker_verification"  # quotes not checked
    # receipts are not taken at all, whatever they say: v0, v1, edited or not (see the forged PASS test)
    for rec in (check(world, GOOD_Q), receipts.render(assess(world, GOOD_Q))):
        with pytest.raises(repair.SubmissionError) as error:
            attempt(rec)
        assert error.value.code == "untrusted_receipt"
    with pytest.raises(TypeError):
        tr.start(receipt)


# --- review of PR #59: adversarial regressions ---------------------------------------------------------------------

def test_r1_a_forged_consistent_pass_receipt_cannot_close_a_chain(world):
    """A receipt is unsigned: a PASS one can be made to hold together for a text that still misquotes. resolve took
    it at head 644f753 and closed the chain as verified; now only an Assessment made in this process is taken."""
    wrong = WORSE_Q
    forged = check(world, GOOD_Q)
    forged["subject"][0]["digest"]["sha256"] = fb.text_digest(wrong)
    assert receipts.problems(forged) == []  # consistent, so no consistency check can tell
    assert fb.from_receipt(forged)["disposition"] == "verified"  # advice about that receipt, as given (unsigned)
    records, first = tr.start(assess(world, BAD_Q))
    with pytest.raises(repair.SubmissionError) as error:
        repair.resolve(records, first, repair.submission(first, BAD_Q, wrong), original=BAD_Q, corrected=wrong,
                       assessment=forged)
    assert error.value.code == "untrusted_receipt" and tr.replay(records).disposition == "repair_requested"
    with pytest.raises(TypeError, match="Assessment"):
        tr.start(forged)
    got = repair.resolve(records, first, repair.submission(first, BAD_Q, wrong), original=BAD_Q, corrected=wrong,
                         assessment=assess(world, wrong))  # the orchestrator's own check of the same text
    assert got.decision["outcome"] == "FAIL" and got.feedback["disposition"] == "budget_exhausted"


def test_r2_a_repair_cannot_add_lines_inside_an_allowed_replacement(world):
    original = f"Intro.\n{BAD_Q}\nOutro."
    smuggled = f"Intro.\n{GOOD_Q}\nThe deployment is complete and every test passed.\nOutro."
    assert repair.changes(original, smuggled) == ([2], [])  # one replace block: the extra line was not seen
    assert repair.added(original, smuggled) == [3]
    _, _, got = run_once(world, original, smuggled)
    assert got.decision["rejection"] == "added_content" and got.feedback["disposition"] == "budget_exhausted"
    assert got.records[2]["body"]["observed"]["added_lines"] == [3]
    inserted = f"Intro.\n{GOOD_Q}\nAll done.\nOutro."
    assert repair.added(f"Intro.\n{GOOD_Q}\nOutro.", inserted) == [3]  # a pure insertion counts the same
    disclosed = f"Intro.\n{GOOD_Q}\nbuddie: the first quote was corrected after a check.\nOutro."
    _, _, ok = run_once(world, original, disclosed)
    assert ok.decision["status"] == "accepted" and ok.feedback["disposition"] == "verified"


def test_r2_out_of_scope_lines_survive_any_accepted_edit():
    """Seeded fuzz of the scope rule alone: whenever no line is out of scope and nothing is added, every line outside
    the scope is still there, unchanged and in order, and the text has no more lines than before but disclosures."""
    import random
    rnd = random.Random(59)
    words = ["a", "b", "c", "a b", ""]
    tried = 0
    for _ in range(3000):
        lines = [rnd.choice(words) for _ in range(rnd.randint(1, 7))]
        allowed = {n for n in range(1, len(lines) + 1) if rnd.random() < 0.4}
        new = list(lines)
        for _ in range(rnd.randint(1, 3)):
            at = rnd.randint(0, len(new))
            op = rnd.choice(("replace", "insert", "delete", "disclose"))
            if op == "replace" and at < len(new):
                new[at] = rnd.choice(words + ["x", "y"])
            elif op == "insert":
                new[at:at] = [rnd.choice(words + ["x"])] * rnd.randint(1, 2)
            elif op == "delete" and at < len(new):
                del new[at]
            elif op == "disclose":
                new.insert(at, "buddie: a gap")
        original, corrected = "\n".join(lines), "\n".join(new)
        changed, inserted = repair.changes(original, corrected)
        if repair.outside(allowed, changed, inserted) or repair.added(original, corrected):
            continue
        tried += 1
        new = corrected.split("\n")  # the text, not the edit list ("\n".join([]) == "\n".join([""]))
        kept = iter(new)
        assert all(any(line == other for other in kept) for n, line in enumerate(lines, 1) if n not in allowed)
        assert len([x for x in new if not x.startswith("buddie:")]) <= len(lines)
    assert tried > 300  # the property was exercised, not skipped


def test_r3_removing_a_required_claim_is_not_a_finished_task(world):
    original = f"Merged: `⚓ pr:o/r#55=merged`\nThe file holds. {anchor(world)}"
    removed = f"The file holds. {anchor(world)}"
    # without requirements the report verifies and says nothing of the task; the removal is recorded as such
    _, _, plain = run_once(world, original, removed)
    assert plain.feedback["disposition"] == "verified" and plain.feedback["task"]["status"] == "not_stated"
    assert list(plain.decision["resolved"].values()) == ["removed"]  # was "corrected" by line number at 644f753
    # with the task's requirement stated by the orchestrator, the same PASS is requirements_unmet
    need = [{"check": "pr_anchor", "subject_prefix": "pr:o/r#55=merged"}]
    records, first = tr.start(assess(world, original), requirements=need)
    assert first["task"]["status"] == "unmet" and first["task"]["requirements"][0]["status"] == "unsupported"
    got = repair.resolve(records, first, repair.submission(first, original, removed), original=original,
                         corrected=removed, assessment=assess(world, removed))
    assert got.decision["outcome"] == "PASS" and got.decision["task"] == "unmet"
    assert got.feedback["disposition"] == "requirements_unmet"
    assert got.feedback["task"]["requirements"][0]["status"] == "absent"
    state = tr.replay(got.records)
    assert state.task == "unmet" and state.terminal
    # an honest correction is a correct report of an unfinished task: still not met
    honest = f"Still open: `⚓ pr:o/r#55=open`\nThe file holds. {anchor(world)}"
    records, first = tr.start(assess(world, original), requirements=need)
    reported = repair.resolve(records, first, repair.submission(first, original, honest), original=original,
                              corrected=honest, assessment=assess(world, honest))
    assert reported.decision["outcome"] == "PASS" and reported.feedback["disposition"] == "requirements_unmet"
    # the agent cannot state or drop requirements
    with pytest.raises(repair.SubmissionError) as error:
        repair.resolve(records, first, {**repair.submission(first, original, removed), "requirements": []},
                       original=original, corrected=removed, assessment=assess(world, removed))
    assert error.value.code == "unauthorized_field"
    for bad in ([{"check": "pr_anchor"}], [{"check": "nope", "subject_prefix": "x"}], "pr_anchor"):
        with pytest.raises(ValueError):
            fb.check_requirements(bad)


def test_r4_a_verified_claim_must_stay_where_it_was(world):
    ok, broken = anchor(world), anchor(world, ok=False)
    original = f"Fix {broken} here; holds {ok}\nmiddle\nSecond {broken}"
    # moved from its own line to another scoped line: still in the text, not where it was (taken at 644f753)
    moved = f"Fix removed here\nmiddle\nSecond removed; holds {ok}"
    assert repair.lost_verified(fb.from_receipt(check(world, original)), original, moved)
    _, _, got = run_once(world, original, moved)
    assert got.decision["rejection"] == "verified_content_changed"
    # its words kept in place, but no longer an anchor: only the new check can tell
    defused = f"Fix it here; holds {ok.replace(chr(0x2693) + ' ', '')}\nmiddle\nSecond removed"
    _, _, got = run_once(world, original, defused)
    assert got.decision["rejection"] == "verified_content_changed"
    # kept on its own line among other words: accepted. The sentence around a claim is not judged (documented)
    reworded = f"Unrelated aside; holds {ok}\nmiddle\nSecond removed"
    _, _, got = run_once(world, original, reworded)
    assert got.decision["status"] == "accepted" and got.feedback["disposition"] == "verified"
