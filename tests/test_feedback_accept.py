"""The hand-in boundary (repair.accept, MCP feedback_accept): a chain's `verified` covers its last independently
accepted text and nothing else. Found by the Feedback E2E benchmark (experiments/feedback-e2e-v1, REPORT.md F3): a
chain verified at start, an edit refused with loop_closed, and the edited text handed in still read as verified.

Offline: a snapshot store and a repo in a temp directory, fetch and GitHub off, JSON-RPC through mcp.handle."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from buddie import chains, mcp, repair, trace as tr
from buddie.verbatim.store import Store

URL = "https://news.example.org/outage"
PAGE = ("<p>" + "Background paragraph about the service. " * 40 + "</p><p>The company said the outage began at 14:59 "
        "UTC and was resolved within two hours.</p>").encode()
GOOD_Q = f"The vendor wrote that “the outage began at 14:59 UTC and was resolved within two hours” ([r]({URL}))."
BAD_Q = GOOD_Q.replace("14:59", "14:58")
ANCHOR = f"`⚓ data.txt#{hashlib.sha256(b'hello' + bytes([10])).hexdigest()}`"
REPORT = f"{BAD_Q}\n\nThe file is as stated. {ANCHOR}"
FIXED = REPORT.replace(BAD_Q, GOOD_Q)
CORRECT = f"{GOOD_Q}\n\nThe file is as stated. {ANCHOR}"
REQUIRED = [{"check": "quote", "subject_prefix": "the outage began"}]


@pytest.fixture
def options(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "data.txt").write_bytes(b"hello\n")
    Store(tmp_path / "store").add(URL, PAGE, content_type="text/html")
    monkeypatch.setenv("BUDDIE_STATE", str(tmp_path / "state"))
    monkeypatch.setattr(chains, "_KNOWN", {})
    return {"repos": [str(repo)], "store": str(tmp_path / "store"), "fetch": False, "github": False}


def call(name, arguments):
    result = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                         "params": {"name": name, "arguments": arguments}})["result"]
    return result["structuredContent"], result["isError"], result["content"][0]["text"]


def start(options, text, **extra):
    got, err, _ = call("feedback_start", dict(options, text=text, **extra))
    assert not err, got
    return got


def resolve(started, feedback, before, after, execution="none"):
    got, err, _ = call("feedback_resolve", {"chain": started["chain"], "feedback": feedback,
                                            "original_text": before, "corrected_text": after,
                                            "submission": repair.submission(feedback, before, after,
                                                                            execution=execution)})
    assert not err, got
    return got


def accept(chain, final):
    got, err, text = call("feedback_accept", {"chain": chain, "final_text": final})
    assert not err, got
    return got, text


def trace_bytes(chain):
    return (chains.directory(chain) / "trace.jsonl").read_bytes()


def test_a_verified_chain_accepts_the_text_it_verified(options):
    started = start(options, REPORT)
    assert resolve(started, started["feedback"], REPORT, FIXED)["state"]["disposition"] == "verified"
    got, text = accept(started["chain"], FIXED)
    assert got["accepted"] is True and got["reason"] is None and got["basis"] == "server"
    assert got["artifact_sha256"] == got["final_sha256"] == hashlib.sha256(FIXED.encode()).hexdigest()
    assert text.startswith("buddie feedback: final report accepted; chain verified, basis server")


@pytest.mark.parametrize("edit", [lambda t: t + "\nAll systems are fine.", lambda t: t.replace("as stated", "fine"),
                                  lambda t: t + "\n", lambda t: t.replace("\n", "\r\n")])
def test_a_verified_chain_refuses_any_other_text(options, edit):
    started = start(options, REPORT)
    resolve(started, started["feedback"], REPORT, FIXED)
    got, text = accept(started["chain"], edit(FIXED))
    assert got["accepted"] is False and got["reason"] == "artifact_mismatch" and got["disposition"] == "verified"
    assert "refused (artifact_mismatch)" in text


def test_a_refused_repair_handed_in_is_refused(options):
    started = start(options, REPORT, iteration_limit=2)
    out_of_scope = FIXED.replace("as stated", "checked")                 # edits a line outside the action's scope
    got = resolve(started, started["feedback"], REPORT, out_of_scope)
    assert got["decision"]["status"] == "rejected" and got["decision"]["rejection"] == "out_of_scope"
    assert accept(started["chain"], out_of_scope)[0]["reason"] == "not_verified"
    # the chain is verified later by a repair it accepts; the refused text still is not what it verified
    assert resolve(started, got["feedback"], REPORT, FIXED)["state"]["disposition"] == "verified"
    refused, _ = accept(started["chain"], out_of_scope)
    assert refused["accepted"] is False and refused["reason"] == "artifact_mismatch"
    assert accept(started["chain"], FIXED)[0]["accepted"] is True


def _not_verified(options):
    """A chain in each disposition but verified, with the text it last accepted."""
    # each chain its own text: the same check of the same text within a second is the same chain (chain_exists)
    yield "repair_requested", start(options, REPORT), REPORT
    other = REPORT.replace("as stated", "as stated here")
    s = start(options, other, iteration_limit=1)
    wrong = other.replace("14:58", "14:57")
    assert resolve(s, s["feedback"], other, wrong)["state"]["disposition"] == "budget_exhausted"
    yield "budget_exhausted", s, wrong
    s = start(options, REPORT + " ", requirements=REQUIRED)
    removed = (REPORT + " ").replace(BAD_Q, "The vendor gave a time for the outage.")
    assert resolve(s, s["feedback"], REPORT + " ", removed)["state"]["disposition"] == "requirements_unmet"
    yield "requirements_unmet", s, removed
    unavailable = "CI passed on the fix. ⚓ `ci:o/r@dbf390f479dee4806b67d6d62d90aeec7fc12843=success`"
    yield "not_actionable", start(options, unavailable), unavailable
    yield "nothing_verified", start(options, "Nothing in this text is checkable."), "Nothing in this text is checkable."


def test_no_chain_but_a_verified_one_ever_accepts(options):
    seen = set()
    for disposition, started, last in _not_verified(options):
        got, _ = accept(started["chain"], last)
        assert got["disposition"] == disposition and got["accepted"] is False and got["reason"] == "not_verified"
        assert got["artifact_sha256"] == got["final_sha256"]          # even the chain's own text is not accepted
        seen.add(disposition)
    assert seen == {"repair_requested", "budget_exhausted", "requirements_unmet", "not_actionable",
                    "nothing_verified"}


def test_after_a_restart_acceptance_says_it_rests_on_agent_writable_files(options):
    started = start(options, REPORT)
    resolve(started, started["feedback"], REPORT, FIXED)
    chains._KNOWN.clear()                                                  # the server restarted
    got, text = accept(started["chain"], FIXED)
    assert got["accepted"] is True and got["basis"] == "agent_writable"
    assert text.endswith("basis agent_writable") or "basis agent_writable\n" in text
    assert accept(started["chain"], FIXED + "!")[0]["reason"] == "artifact_mismatch"
    # while the server knows the chain, a rewritten history is refused before anything is accepted
    records = tr.loads(trace_bytes(started["chain"]).decode("utf-8"))
    accept(started["chain"], FIXED)                                       # the chain is known again (read, not written)
    chains._KNOWN[started["chain"]] = (chains.load(started["chain"]).digest, records[-1]["record_id"])
    (chains.directory(started["chain"]) / "trace.jsonl").write_bytes(tr.dumps(records[:2]).encode("utf-8"))
    got, err, _ = call("feedback_accept", {"chain": started["chain"], "final_text": REPORT})
    assert err and got["code"] == "state_tampered"


def test_a_correct_report_is_accepted_as_it_is_without_a_repair(options):
    started = start(options, CORRECT)
    assert started["state"]["disposition"] == "verified"
    before = trace_bytes(started["chain"])
    got, _ = accept(started["chain"], CORRECT)
    assert got["accepted"] is True and got["disposition"] == "verified"
    assert trace_bytes(started["chain"]) == before                        # reading acceptance writes nothing
    # the benchmark's S7 needless edit: the chain refused it (loop_closed); handed in anyway, it is not accepted
    edited = CORRECT.replace("The vendor wrote that", "The vendor stated that")
    _, err, _ = call("feedback_resolve", {"chain": started["chain"], "feedback": started["feedback"],
                                          "original_text": CORRECT, "corrected_text": edited,
                                          "submission": repair.submission(started["feedback"], CORRECT, edited)})
    assert err
    assert accept(started["chain"], edited)[0]["reason"] == "artifact_mismatch"


def test_the_boundary_takes_no_receipt_and_no_other_argument(options):
    started = start(options, CORRECT)
    got, err, _ = call("feedback_accept", {"chain": started["chain"], "final_text": CORRECT,
                                           "receipt": {"predicate": {"outcome": "PASS"}}})
    assert err and got["code"] == "invalid_arguments"
    got, err, _ = call("feedback_accept", {"chain": "sha256:" + "0" * 64, "final_text": CORRECT})
    assert err and got["code"] == "unknown_chain"
    tool = next(t for t in mcp.TOOLS if t["name"] == "feedback_accept")
    assert tool["inputSchema"]["additionalProperties"] is False and set(tool["inputSchema"]["properties"]) == {
        "chain", "final_text"}
    assert tool["annotations"]["readOnlyHint"] is True


def test_the_library_boundary_reads_records_only(options):
    started = start(options, CORRECT)
    records = chains.load(started["chain"]).records
    assert repair.accept(records, CORRECT)["accepted"] is True
    assert repair.accept(records, CORRECT + "x") == dict(repair.accept(records, CORRECT + "x"), accepted=False,
                                                          reason="artifact_mismatch")
    assert repair.accepted_artifact(records) == hashlib.sha256(CORRECT.encode()).hexdigest()


def test_the_remote_server_does_not_offer_it():
    from buddie import remote
    assert "feedback_accept" not in remote.HANDLERS
    assert "feedback_accept" not in {t["name"] for t in remote.tools()}
    assert json.dumps(mcp.TOOLS)  # the tool list stays serializable
