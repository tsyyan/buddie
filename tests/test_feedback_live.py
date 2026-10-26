"""The Feedback E2E live pilot runner (experiments/feedback-e2e-v1/live.py), offline: a fake transport stands in for
the Messages API, so nothing here sends a request or spends money. What is checked is the gate: the manifest, the
cost enforcement, the abort rules, the isolation of the agent's tools and of the network."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_receipts import validate

EXP = Path(__file__).resolve().parents[1] / "experiments" / "feedback-e2e-v1"
sys.path.insert(0, str(EXP))

import harness as H  # noqa: E402
import live  # noqa: E402
import scenarios as S  # noqa: E402

MANIFEST = json.loads((EXP / "approval.pilot.json").read_text(encoding="utf-8"))
USAGE = {"input_tokens": 1500, "output_tokens": 400, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}


def authorized():
    doc = copy.deepcopy(MANIFEST)
    doc["final_authorization"] = {"authorized_by": "a test", "authorized_at": "2026-10-26T00:00:00Z"}
    return doc


class Fake:
    """A scripted agent: checks the report once with its condition's first tool, then hands it back unchanged."""

    def __init__(self, usage=USAGE, model=None):
        self.usage, self.model, self.bodies = usage, model, []

    def send(self, body):
        self.bodies.append(body)
        tool = body["tools"][0]["name"]
        report = body["messages"][0]["content"].split("## Report\n\n", 1)[1].strip()
        answered = len(body["messages"]) > 1
        content = ([{"type": "text", "text": report + "\nSTATUS: not verified"}] if answered else
                   [{"type": "tool_use", "id": f"t{len(self.bodies)}", "name": tool, "input": {"text": report}}])
        out = {"id": f"msg_{len(self.bodies)}", "model": self.model or body["model"],
               "stop_reason": "end_turn" if answered else "tool_use", "content": content}
        if self.usage is not None:
            out["usage"] = dict(self.usage)
        return out


def test_the_manifest_is_complete_but_not_yet_authorized(monkeypatch):
    schema = json.loads((EXP / "approval.schema.json").read_text(encoding="utf-8"))
    assert validate(MANIFEST, schema) == []
    assert MANIFEST["model"] == "claude-sonnet-5-5" and MANIFEST["limits"]["max_cost_usd"] == 10
    assert live.problems(MANIFEST, execute=False) == []
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    found = live.problems(MANIFEST, execute=True)
    assert any("final_authorization" in p for p in found) and any("ANTHROPIC_API_KEY" in p for p in found)
    assert live.main(["execute", "--approval", str(EXP / "approval.pilot.json"), "--out", "x"]) == 2


def test_the_per_run_ceiling_must_fit_the_pilot_ceiling():
    doc = authorized()
    doc["limits"]["max_cost_per_run_usd"] = 1.0                      # 16 runs x 1.0 > 10
    assert any("per-run ceiling" in p for p in live.problems(doc, execute=False))


def test_a_dry_pilot_runs_all_sixteen_paired_runs(tmp_path):
    fake = Fake()
    summary = live.pilot(authorized(), tmp_path, fake)
    assert summary["status"] == "complete" and summary["runs_recorded"] == 16 == summary["runs_planned"]
    records = [json.loads(line) for line in (tmp_path / "live.jsonl").read_text(encoding="utf-8").splitlines()]
    schema = json.loads((EXP / "metrics.schema.json").read_text(encoding="utf-8"))
    assert all(validate(r, schema) == [] and H.check_record(r) == [] for r in records)
    assert sorted((r["scenario"], r["condition"]) for r in records) == sorted(
        (s.sid, c) for s in S.SCENARIOS for c in ("control", "treatment"))
    per_call = live.cost(USAGE, MANIFEST["pricing"])
    ledger = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(ledger) == 32 and summary["usage_cost_usd"] == pytest.approx(32 * per_call)
    assert all(r["cost_usd"] is None and r["cost_verifiable"] is False for r in records)
    assert all(r["tokens"]["input"] == 3000 for r in records)
    # every request: the approved model, a fresh conversation, no option the agent could set
    assert {b["model"] for b in fake.bodies} == {"claude-sonnet-5-5"}
    assert all("temperature" not in b and b["output_config"] == {"effort": "medium"} for b in fake.bodies)
    # an unchanged report handed back as not verified: success only where nothing was wrong (S7, an under-claim)
    assert {(r["scenario"], r["condition"]) for r in records if r["labels"]["verified_task_success"]} == {
        ("S7", "control"), ("S7", "treatment")}


def test_a_response_costlier_than_its_checked_worst_case_aborts(tmp_path):
    summary = live.pilot(authorized(), tmp_path, Fake(usage=dict(USAGE, output_tokens=10_000_000)))
    assert summary["status"].startswith("aborted") and "worst case" in summary["status"]
    assert summary["runs_recorded"] == 0


def test_missing_usage_or_another_model_aborts(tmp_path):
    assert "no usage" in live.pilot(authorized(), tmp_path / "a", Fake(usage=None))["status"]
    assert "approved" in live.pilot(authorized(), tmp_path / "b", Fake(model="claude-opus-5-5"))["status"]


def test_the_pilot_ceiling_stops_before_a_request_that_could_cross_it(tmp_path):
    ledger = live.Ledger(authorized(), None)
    ledger.total = 9.99
    item = {"order": 0, "scenario": "S1", "repetition": 0, "condition": "control"}
    fake = Fake()
    with pytest.raises(live.PilotAbort, match="pilot ceiling"):
        live.run_one(item, authorized(), fake, ledger)
    assert fake.bodies == []                                         # nothing was sent


def test_the_per_run_ceiling_stops_the_run_not_the_pilot():
    doc = authorized()
    doc["limits"]["max_cost_per_run_usd"] = 0.05                     # below one request's worst case
    item = {"order": 0, "scenario": "S1", "repetition": 0, "condition": "treatment"}
    fake = Fake()
    record = live.run_one(item, doc, fake, live.Ledger(doc, None))
    assert fake.bodies == [] and any(d.startswith("budget_stop") for d in record["deviations"])
    assert record["labels"]["verified_task_success"] is False


def test_the_agents_tools_take_text_only():
    for arm, tools in live.TOOLS.items():
        for t in tools:
            schema = t["input_schema"]
            assert schema["additionalProperties"] is False and t["strict"] is True
            assert not set(schema["properties"]) & {"path", "repos", "store", "transcript", "access", "fetch",
                                                    "github", "receipt", "submission", "feedback"}


def test_the_treatment_adapter_fills_the_submission_and_tracks_the_chain(tmp_path):
    with H.isolated(tmp_path) as world:
        a = live.Adapter("treatment", S.S1, world)
        got, err = a.call("feedback_start", {"text": S.S1.report})
        assert not err and got["state"]["disposition"] == "repair_requested"
        fixed = S.S1.report.replace(S.BAD_Q, S.GOOD_Q)
        got, err = a.call("feedback_resolve", {"corrected_text": fixed, "execution": "none"})
        assert not err and got["decision"]["status"] == "accepted" and a.accepted == fixed
        assert a.final_signal() == "verified"
        assert a.call("verify_report", {"text": fixed})[1] is True     # not a tool of this condition
        c = live.Adapter("control", S.S1, world)
        for _ in range(1 + S.ITERATION_LIMIT):
            assert c.call("verify_report", {"text": fixed})[1] is False
        assert c.call("verify_report", {"text": fixed})[1] is True     # the draft budget is the same 2


def test_the_transport_ignores_base_urls_and_sends_an_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:1/subscription-proxy")
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": true}'

    def urlopen(req, timeout):
        seen.update(url=req.full_url, key=req.get_header("X-api-key"), version=req.get_header("Anthropic-version"))
        return Response()

    monkeypatch.setattr(live.urllib.request, "urlopen", urlopen)
    assert live.Transport("sk-test").send({"model": "m"}) == {"ok": True}
    assert seen == {"url": "https://api.anthropic.com/v1/messages", "key": "sk-test", "version": live.API_VERSION}


GUARD = """
import socket, sys
sys.path.insert(0, sys.argv[1])
import live
live.guard_network()
try:
    socket.getaddrinfo("example.org", 443)
    print("reached")
except PermissionError:
    print("blocked")
"""


def test_the_network_guard_refuses_every_other_host():
    out = subprocess.run([sys.executable, "-c", GUARD, str(EXP)], capture_output=True, text=True, timeout=60,
                         cwd=EXP.parents[1])
    assert out.stdout.strip() == "blocked", out.stderr
