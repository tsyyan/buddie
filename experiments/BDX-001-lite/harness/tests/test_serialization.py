"""Plans and run records: deterministic, randomized order, complete and JSON round-trippable."""
import json
from types import SimpleNamespace

import pytest

from bdx import backends, cli

SCRIPT = {"calls": [["environment_snapshot", {"device": "device-1", "categories": ["hardware.memory"]}]],
          "answer": "It will not fit in 2 GiB.\n```result\n{\"outcome\": \"recommendation\", \"commands\": "
                    "[\"pip install llama-cpp-python\"], \"environment_facts\": [], \"question\": null}\n```"}


def make_plan(tmp_path, seed=11, set_="smoke", reps=1):
    out = tmp_path / f"b{seed}{set_}{reps}"
    cli.plan(SimpleNamespace(set=set_, reps=reps, seed=seed, out=str(out)))
    return out, json.loads((out / "plan.json").read_text(encoding="utf-8"))


def test_plan_is_deterministic_and_shuffled(tmp_path):
    _, a = make_plan(tmp_path, 11)
    _, b = make_plan(tmp_path / "x", 11)
    _, c = make_plan(tmp_path / "y", 12)
    ids = lambda p: [r["run_id"] for r in p["runs"]]  # noqa: E731
    assert ids(a) == ids(b) and ids(a) != ids(c)
    assert len(ids(a)) == 9 and sorted(ids(a)) != ids(a)
    _, full = make_plan(tmp_path / "f", 1, "full", 2)
    assert len(full["runs"]) == 72 and len(set(ids(full))) == 72


def test_run_refuses_model_backend_without_cost_confirmation(tmp_path):
    out, _ = make_plan(tmp_path)
    assert cli.run(SimpleNamespace(batch=str(out), backend="claude-cli", model="x", limit=None,
                                   confirm_cost=False)) == 2


def test_record_from_scripted_backend_round_trips(tmp_path):
    _, p = make_plan(tmp_path)
    entry = next(r for r in p["runs"] if r["run_id"] == "HW-2-C-r1")
    prepared = cli.prepare(entry)
    out = backends.scripted(prepared, SCRIPT)
    rec = cli.record(prepared, out, "scripted", None, cli.now())
    again = json.loads(json.dumps(rec, ensure_ascii=False))
    assert again == rec
    for key in ("run_id", "scenario", "condition", "backend", "prompts", "tools_available", "tool_calls",
                "tool_used", "diagnostic_iterations", "final_text", "duration_s", "usage", "status", "fixtures"):
        assert key in rec
    assert rec["tool_used"] and rec["diagnostic_iterations"] == 1
    assert rec["items_requested"] == [["hardware.memory"]]
    assert rec["fixtures"]["buddie_version"] == {"linux-container-2g": "2.0.1"}
    assert rec["response_bytes_total"] == rec["tool_calls"][0]["response_bytes"] > 0


@pytest.mark.parametrize("failure", [None, "isolation_violation"])
def test_status_reflects_harness_failure(tmp_path, failure):
    _, p = make_plan(tmp_path)
    prepared = cli.prepare(p["runs"][0])
    rec = cli.record(prepared, {"failure": failure, "tool_calls": []}, "claude-cli", "m", cli.now())
    assert rec["status"] == ("ok" if failure is None else "harness_failure")
