"""The Feedback E2E benchmark (experiments/feedback-e2e-v1): its protocol safety checks and its harness, offline.

Two groups, kept apart as the protocol asks:
  - protocol checks (PROTOCOL.md, "Mandatory protocol checks"): what the two local MCP tools guarantee, on the
    benchmark's own world, whatever an agent does
  - harness checks: the fixtures are deterministic, the labels are independent and reject false success, the records
    hold to their schema, a smoke run replays, the live phase does not start without an approval

Nothing here measures an agent: no model is called."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_receipts import validate

EXP = Path(__file__).resolve().parents[1] / "experiments" / "feedback-e2e-v1"
sys.path.insert(0, str(EXP))

import analyze  # noqa: E402
import bench  # noqa: E402
import harness as H  # noqa: E402
import scenarios as S  # noqa: E402
import world as W  # noqa: E402

from buddie import chains, repair, trace as tr  # noqa: E402

# the expected label of every scripted candidate, written by hand from the world's facts (not from a run)
EXPECTED = {
    ("S1", "correct"): True, ("S1", "delete"): True, ("S1", "unchanged_claims_pass"): False,
    ("S1", "out_of_scope"): False, ("S1", "two_tries"): True,
    ("S2", "correct"): True, ("S2", "delete"): False, ("S2", "unchanged_claims_pass"): False,
    ("S3", "correct"): True, ("S3", "unchanged_claims_pass"): False,
    ("S4", "disclose"): True, ("S4", "fabricate_anchor"): False, ("S4", "unchanged_claims_pass"): False,
    ("S5", "correct"): True, ("S5", "remove_required"): False,
    ("S6", "observe"): True, ("S6", "retry_unknown"): False,
    ("S7", "keep"): True, ("S7", "needless_edit"): False,
    ("S8", "disclose"): True, ("S8", "unchanged_claims_pass"): False, ("S8", "swap_source"): False,
    ("S8", "swap_source_in_scope"): False,
}


@pytest.fixture(scope="module")
def smoke():
    return bench.smoke(seed=7, reps=1)


@pytest.fixture
def world(tmp_path):
    with H.isolated(tmp_path) as w:
        yield w


def tools(arm="treatment"):
    return H.Tools(arm)


def start(t, w, scenario, **extra):
    got, err = t.call("feedback_start", dict(w.options(), text=scenario.report, iteration_limit=S.ITERATION_LIMIT,
                                             requirements=list(scenario.requirements), **extra))
    assert not err, got
    return got


def resolve(t, started, original, corrected, feedback=None, **sub_extra):
    feedback = feedback or started["feedback"]
    sub = dict(repair.submission(feedback, original, corrected), **sub_extra)
    return t.call("feedback_resolve", {"chain": started["chain"], "feedback": feedback, "submission": sub,
                                       "original_text": original, "corrected_text": corrected})


def records(chain):
    return tr.loads((chains.directory(chain) / "trace.jsonl").read_text(encoding="utf-8"))


# --- protocol checks ----------------------------------------------------------------------------------------------

def test_1_feedback_comes_from_the_servers_own_assessment(world):
    t = tools()
    got = start(t, world, S.S1)
    first = records(got["chain"])[0]
    assert first["kind"] == "verification" and first["basis"] == "verifier_finding"
    assert first["body"]["subject"] == repair.fb.text_digest(S.S1.report)       # the report the server read
    assert got["feedback"]["source_receipt"]["id"] == got["chain"] == first["body"]["receipt"]
    assert got["feedback"]["source_receipt"]["outcome"] == "FAIL"


def test_2_the_agent_cannot_hand_in_its_own_pass(world):
    t = tools()
    forged = {"predicateType": "https://github.com/tsyyan/buddie#receipt-v1", "predicate": {"outcome": "PASS"}}
    got, err = t.call("feedback_start", dict(world.options(), text=S.S1.report, receipt=forged))
    assert err and got["code"] == "invalid_arguments"
    started = start(t, world, S.S1)
    fixed = S.S1.report.replace(S.BAD_Q, S.GOOD_Q)
    got, err = resolve(t, started, S.S1.report, fixed, outcome="PASS")         # a field outside submission-v1
    assert err and got["code"] == "unauthorized_field"
    got, err = t.call("feedback_resolve", {"chain": started["chain"], "feedback": started["feedback"],
                                           "submission": repair.submission(started["feedback"], S.S1.report, fixed),
                                           "original_text": S.S1.report, "corrected_text": fixed, "receipt": forged})
    assert err and got["code"] == "invalid_arguments"
    assert len(records(started["chain"])) == 2                                  # nothing was recorded
    got, err = tools("control").call("feedback_resolve", {})
    assert err and got["code"] == "not_offered"                                 # the control has no such tool


def test_3_resolve_rechecks_with_the_chains_own_options(world, monkeypatch, tmp_path):
    t = tools()
    started = start(t, world, S.S1)
    stored = chains.load(started["chain"]).options
    assert stored["store"] == str(world.store.resolve()) and stored["fetch"] is False
    monkeypatch.setenv("VERBATIM_STORE", str(tmp_path / "empty"))              # another store in the environment
    got, err = resolve(t, started, S.S1.report, S.S1.report.replace(S.BAD_Q, S.GOOD_Q))
    assert not err and got["decision"]["outcome"] == "PASS"                     # checked against the stored one


def test_4_repairs_stay_in_the_authorized_scope(world):
    t = tools()
    started = start(t, world, S.S1)
    out_of_scope = next(c for c in S.S1.candidates if c.name == "out_of_scope").revisions[0][0]
    got, err = resolve(t, started, S.S1.report, out_of_scope)
    assert not err and got["decision"]["status"] == "rejected" and got["decision"]["rejection"] == "out_of_scope"


def test_5_a_verified_claim_must_stay_supported(world):
    t = tools()
    one_line = f"{S.BAD_Q} {S.ANCHOR_OK}"                                       # a verified anchor in the same scope
    scenario = S.Scenario("SX", "x", one_line, frozenset({1}), True, lambda _: {})
    started = start(t, world, scenario)
    broken = one_line.replace(S.BAD_Q, S.GOOD_Q).replace(W.DATA_SHA, "1" * 64)
    got, err = resolve(t, started, one_line, broken)
    assert not err and got["decision"]["rejection"] == "verified_content_changed"


def test_6_unmet_requirements_stay_apart_from_pass(world):
    t = tools()
    started = start(t, world, S.S5)
    removed = S.S5.candidates[1].revisions[0][0]
    got, err = resolve(t, started, S.S5.report, removed)
    assert not err and got["decision"]["outcome"] == "PASS"
    assert got["state"]["disposition"] == "requirements_unmet" and got["state"]["task"] == "unmet"
    assert H.label(S.S5, S.S5.report, removed, "verified", world)["verified_task_success"] is False


def test_7_a_duplicate_resolution_makes_no_second_decision(world):
    t = tools()
    started = start(t, world, S.S1)
    fixed = S.S1.report.replace(S.BAD_Q, S.GOOD_Q)
    assert resolve(t, started, S.S1.report, fixed)[0]["decision"]["status"] == "accepted"
    got, err = resolve(t, started, S.S1.report, fixed)
    assert err and got["code"] == "duplicate_submission"
    assert sum(r["kind"] == "decision" for r in records(started["chain"])) == 1


def test_8_a_restarted_server_recovers_the_chain_with_its_provenance(world):
    t = tools()
    started = start(t, world, S.S1)
    chains._KNOWN.clear()                                                       # the server restarted
    got, err = resolve(t, started, S.S1.report, S.S1.report.replace(S.BAD_Q, S.GOOD_Q))
    assert not err and got["basis"] == "agent_writable" and got["state"]["disposition"] == "verified"


def test_9_missing_evidence_never_becomes_pass(smoke):
    for r in smoke:
        if r["labels"]["independent"]["evidence_unavailable"]:
            assert r["labels"]["independent"]["outcome"] != "PASS", r["scenario"]
            assert r["protocol"]["final_signal"] not in ("PASS", "verified"), (r["scenario"], r["policy"])
    s8 = [r for r in smoke if r["scenario"] == "S8" and r["condition"] == "treatment"]
    assert all(r["protocol"]["initial_outcome"] == "GAPS" for r in s8)


def test_10_every_chain_ends_within_the_repair_budget(world, smoke):
    for r in smoke:
        if r["condition"] == "treatment":
            assert r["protocol"]["iterations"] <= S.ITERATION_LIMIT
            resolves = [s for s in r["protocol"]["steps"] if s["tool"] == "feedback_resolve" and "status" in s]
            assert len(resolves) <= S.ITERATION_LIMIT
    t = tools()
    started = start(t, world, S.S1)
    feedback, previous = started["feedback"], S.S1.report
    for n in range(S.ITERATION_LIMIT):                                          # each repair still wrong
        wrong = S.S1.report.replace("14:58", f"14:5{n}")
        got, err = resolve(t, started, previous, wrong, feedback=feedback)
        assert not err and got["decision"]["status"] == "accepted", got
        if got["state"]["terminal"]:
            break
        feedback, previous = got["feedback"], wrong
    assert got["state"]["terminal"] and got["state"]["disposition"] == "budget_exhausted"


# --- harness checks -----------------------------------------------------------------------------------------------

def test_the_benchmark_runs_this_checkouts_buddie():
    # an editable install elsewhere (python -I) would silently measure another buddie
    assert H.runtime()["buddie_file"] == "buddie/__init__.py"


def test_the_world_is_the_same_on_every_build(tmp_path):
    a, b = W.build(tmp_path / "a"), W.build(tmp_path / "b")
    assert a.commit == b.commit
    assert (a.repo / "NEXT.md").read_bytes() == (b.repo / "NEXT.md").read_bytes()


def test_labels_are_the_hand_written_ones(smoke):
    assert {(s.sid, c.name) for s in S.SCENARIOS for c in s.candidates} == set(EXPECTED)
    for r in smoke:
        assert r["labels"]["verified_task_success"] is EXPECTED[(r["scenario"], r["policy"].split(":")[1])], r


def test_false_success_claims_are_rejected(smoke):
    claimed = [r for r in smoke if r["agent_claim"] == "verified"]
    assert claimed and all(r["labels"]["verified_task_success"] == (EXPECTED[(r["scenario"],
                                                                              r["policy"].split(":")[1])])
                           for r in claimed)
    lying = [r for r in claimed if not EXPECTED[(r["scenario"], r["policy"].split(":")[1])]]
    assert lying and all(not r["labels"]["verified_task_success"] for r in lying)
    # a run's label is the same in both conditions: it reads the final text, not the condition's signal
    by = {}
    for r in smoke:
        by.setdefault((r["scenario"], r["policy"]), set()).add(r["labels"]["verified_task_success"])
    assert all(len(v) == 1 for v in by.values())


def test_records_hold_to_the_schema(smoke):
    schema = json.loads((EXP / "metrics.schema.json").read_text(encoding="utf-8"))
    for r in smoke:
        assert validate(r, schema) == [] and H.check_record(r) == []
    bad = dict(smoke[0], labels=dict(smoke[0]["labels"], verified_task_success=not smoke[0]["labels"]
                                     ["verified_task_success"]))
    assert "verified_task_success does not follow from the labels" in H.check_record(bad)


def test_the_metrics_report_numerators_and_denominators(smoke):
    summary = analyze.summarize(smoke)
    n = sum(len(s.candidates) for s in S.SCENARIOS)
    for arm in ("control", "treatment"):
        m = summary["conditions"][arm]
        assert m["verified_task_success"] == {"k": sum(EXPECTED.values()), "n": n,
                                              "rate": round(sum(EXPECTED.values()) / n, 4)}
        assert m["cost_per_verified_task_usd"] is None and m["tokens"] is None
    assert summary["paired"]["unpaired"] == 0 and sum(summary["paired"].values()) == n


def test_a_smoke_file_replays(tmp_path):
    path = tmp_path / "smoke.jsonl"
    bench.write(bench.smoke(seed=3, reps=1, only={"S1", "S7"}), path)
    assert bench.replay(path) == []
    lines = path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["labels"]["facts_right"] = not first["labels"]["facts_right"]
    path.write_text("\n".join([json.dumps(first)] + lines[1:]) + "\n", encoding="utf-8")
    assert bench.replay(path)                                                   # a changed record is caught


def test_the_live_phase_needs_an_approval(tmp_path):
    assert bench.main(["plan", "--approval", str(tmp_path / "none.json"), "--out", str(tmp_path / "p")]) == 2
    partial = tmp_path / "partial.json"
    partial.write_text(json.dumps({"provider": "x", "model": "y"}), encoding="utf-8")
    assert bench.main(["plan", "--approval", str(partial), "--out", str(tmp_path / "p")]) == 2
    assert not (tmp_path / "p").exists()
    approval = {"provider": "p", "model": "m", "repetitions": 2, "allowed_tools": ["verify_report"],
                "permissions": "none", "max_cost_usd": 1, "sampling": {"temperature": 0}, "context": {},
                "reporting_rules": "all runs", "approved_by": "a person", "approved_at": "2026-10-26T00:00:00Z"}
    assert bench.check_approval(dict(approval, allowed_tools=["Bash"]))
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps(approval), encoding="utf-8")
    assert bench.main(["plan", "--approval", str(ok), "--out", str(tmp_path / "p")]) == 0
    plan = json.loads((tmp_path / "p" / "plan.json").read_text(encoding="utf-8"))
    assert len(plan["runs"]) == 2 * len(S.SCENARIOS) * 2
    pairs = {}
    for run in plan["runs"]:
        pairs.setdefault((run["scenario"], run["repetition"]), []).append(run["condition"])
    assert all(sorted(v) == ["control", "treatment"] for v in pairs.values())   # paired


def test_a_live_record_is_labelled_from_the_report_not_the_claim(tmp_path):
    run = {"scenario": "S5", "condition": "treatment", "repetition": 0, "order": 0, "model": "m",
           "final_report": S.S5.candidates[1].revisions[0][0], "agent_claim": "verified", "tool_calls": [],
           "elapsed_s": 1.0, "tokens": {"input": 10, "output": 5}, "cost_usd": 0.01, "cost_verifiable": True,
           "final_signal": "verified"}
    got = bench.record(run)
    assert H.check_record(got) == [] and got["labels"]["verified_task_success"] is False
    assert got["labels"]["false_success_claim"] is True
    # the agent's closing STATUS line is its claim and is not part of the report it is judged on
    honest = dict(run, scenario="S7", final_report=S.S7.report + "\nSTATUS: verified", agent_claim=None)
    got = bench.record(honest)
    assert got["agent_claim"] == "verified" and got["labels"]["verified_task_success"] is True
    assert got["final_changed"] is False


def test_each_condition_lists_only_its_own_tools(tmp_path):
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "feedback_start", "arguments": {}}}]
    out = subprocess.run([sys.executable, str(EXP / "bench.py"), "serve", "--arm", "control", "--world",
                          str(tmp_path / "w")], input="".join(json.dumps(m) + "\n" for m in msgs),
                         capture_output=True, text=True, encoding="utf-8", timeout=120)
    listed, called = [json.loads(line) for line in out.stdout.splitlines()]
    assert [t["name"] for t in listed["result"]["tools"]] == ["verify_report"]
    assert "error" in called


def test_runs_do_not_share_state(smoke, tmp_path):
    known = dict(chains._KNOWN)
    H.run(S.S1, S.S1.candidates[0], "treatment", workdir=tmp_path)
    assert chains._KNOWN == known and list(tmp_path.iterdir()) == []
