"""Verification feedback over the local MCP server (docs/feedback.md#mcp): feedback_start and feedback_resolve.

The server runs every check itself and keeps the chain in its state dir; no tool takes a receipt. Offline: a
snapshot store and a repo in a temp directory, fetch and GitHub off, JSON-RPC through mcp.handle."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from buddie import feedback as fb, mcp, repair, trace as tr
from buddie.verbatim.store import Store

URL = "https://news.example.org/outage"
PAGE = ("<p>" + "Background paragraph about the service. " * 40 + "</p><p>The company said the outage began at 14:59 "
        "UTC and was resolved within two hours.</p>").encode()
GOOD_Q = f"The vendor wrote that “the outage began at 14:59 UTC and was resolved within two hours” ([r]({URL}))."
BAD_Q = GOOD_Q.replace("14:59", "14:58")
ANCHOR = f"`⚓ data.txt#{hashlib.sha256(b'hello' + bytes([10])).hexdigest()}`"
REQUIRED = [{"check": "quote", "subject_prefix": "the outage began"}]


@pytest.fixture
def world(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "data.txt").write_bytes(b"hello\n")
    Store(tmp_path / "store").add(URL, PAGE, content_type="text/html")
    monkeypatch.setenv("BUDDIE_STATE", str(tmp_path / "state"))
    return {"repos": [str(repo)], "store": str(tmp_path / "store"), "fetch": False, "github": False}, tmp_path


def call(name, arguments):
    reply = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": name, "arguments": arguments}})
    return reply["result"]


def start(options, text):
    got = call("feedback_start", dict(options, text=text, requirements=REQUIRED))
    assert not got["isError"], got
    return got["structuredContent"]


def resolve(chain, feedback, original, corrected, **extra):
    return call("feedback_resolve", {"chain": chain, "feedback": feedback, "original_text": original,
                                     "corrected_text": corrected,
                                     "submission": repair.submission(feedback, original, corrected), **extra})


def chain_file(tmp, chain):
    return tmp / "state" / "feedback" / f"{chain.split(':')[1]}.jsonl"


def test_a_misquote_is_corrected_through_the_mcp_tools(world):
    options, tmp = world
    original = f"{BAD_Q}\n\nThe file is as stated. {ANCHOR}"
    corrected = original.replace(BAD_Q, GOOD_Q)

    # (1) the server checks the report itself and opens the chain
    started = start(options, original)
    first = started["feedback"]
    assert started["state"] == {"disposition": "repair_requested", "task": "unmet", "iteration": 0,
                                "terminal": False}
    assert [(a["operation"], a["target"]["line"]) for a in first["recommended_actions"]] == [("correct_claim", 1)]
    assert started["receipt_line"].startswith("buddie FAIL (receipt-v1")
    assert (chain_file(tmp, started["chain"]).with_suffix(".options.json")).is_file()

    # (2) the corrected quote is accepted on the server's own re-check
    got = resolve(started["chain"], first, original, corrected)
    assert not got["isError"], got
    out = got["structuredContent"]
    decision = out["decision"]
    assert decision["status"] == "accepted" and decision["outcome"] == "PASS"
    assert list(decision["resolved"].values()) == ["corrected"]
    assert out["state"] == {"disposition": "verified", "task": "met", "iteration": 1, "terminal": True}
    assert got["content"][0]["text"].startswith("buddie PASS (receipt-v1")
    written = chain_file(tmp, started["chain"]).read_text(encoding="utf-8")
    assert tr.replay(tr.loads(written)).disposition == "verified"

    # (3) the same call again is refused and appends nothing
    again = resolve(started["chain"], first, original, corrected)
    assert again["isError"] and again["structuredContent"]["code"] == "duplicate_submission"
    assert chain_file(tmp, started["chain"]).read_text(encoding="utf-8") == written


def test_no_tool_takes_a_receipt(world):
    options, tmp = world
    tools = {t["name"]: t for t in call_list()}
    for name in ("feedback_start", "feedback_resolve"):
        schema = tools[name]["inputSchema"]
        assert schema["additionalProperties"] is False and "receipt" not in schema["properties"]
    forged = {"predicateType": "https://github.com/tsyyan/buddie#receipt-v1", "predicate": {"outcome": "PASS"}}
    got = call("feedback_start", dict(options, text=f"{BAD_Q}\n", receipt=forged))
    assert got["isError"] and got["structuredContent"]["code"] == "invalid_arguments"
    assert not (tmp / "state" / "feedback").exists()


def call_list():
    return mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]


def test_a_changed_feedback_is_refused_and_nothing_is_appended(world):
    options, tmp = world
    original = f"{BAD_Q}\n\nThe file is as stated, too. {ANCHOR}"
    started = start(options, original)
    before = chain_file(tmp, started["chain"]).read_text(encoding="utf-8")
    changed = copy.deepcopy(started["feedback"])
    changed["iteration_limit"] = 3
    got = resolve(started["chain"], changed, original, original.replace(BAD_Q, GOOD_Q))
    assert got["isError"] and got["structuredContent"]["code"] == "forged_feedback"
    changed["feedback_id"] = fb.feedback_id({k: v for k, v in changed.items() if k != "feedback_id"})
    got = resolve(started["chain"], changed, original, original.replace(BAD_Q, GOOD_Q))
    assert got["isError"] and got["structuredContent"]["code"] == "feedback_mismatch"
    assert chain_file(tmp, started["chain"]).read_text(encoding="utf-8") == before


def test_deleting_the_required_quote_leaves_the_task_unmet(world):
    options, tmp = world
    original = f"{BAD_Q}\n\nThe file is as stated, still. {ANCHOR}"
    started = start(options, original)
    got = resolve(started["chain"], started["feedback"], original,
                  original.replace(BAD_Q, "The vendor gave a time for the outage."))
    assert not got["isError"], got
    out = got["structuredContent"]
    assert out["decision"]["outcome"] == "PASS" and list(out["decision"]["resolved"].values()) == ["removed"]
    assert out["state"]["disposition"] == "requirements_unmet" and out["state"]["task"] == "unmet"
    assert tr.replay(tr.loads(chain_file(tmp, started["chain"]).read_text(encoding="utf-8"))).terminal


def test_both_tools_are_listed_locally_and_not_remotely():
    from buddie import remote
    listed = {t["name"]: t for t in call_list()}
    assert {"feedback_start", "feedback_resolve"} <= set(listed)
    assert all(listed[n]["inputSchema"]["additionalProperties"] is False for n in ("feedback_start", "feedback_resolve"))
    assert all(listed[n]["annotations"]["readOnlyHint"] is False for n in ("feedback_start", "feedback_resolve"))
    assert not {"feedback_start", "feedback_resolve"} & {t["name"] for t in remote.tools()}
    assert not {"feedback_start", "feedback_resolve"} & set(remote.HANDLERS)
