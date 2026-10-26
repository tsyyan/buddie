"""Verification feedback over the local MCP server (docs/feedback.md#mcp): feedback_start and feedback_resolve.

The server runs every check itself and keeps the chain in its state dir (buddie/chains.py); no tool takes a receipt.
Offline: a snapshot store and a repo in a temp directory, fetch and GitHub off, JSON-RPC through mcp.handle. The
adversarial cases (concurrent resolves, a restart, failed writes, damaged or altered state) must never end in an
accepted decision that the server's own check did not make."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from buddie import chains, feedback as fb, mcp, repair, trace as tr
from buddie.verbatim.store import Store

ROOT = Path(__file__).resolve().parents[1]
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
    monkeypatch.setattr(chains, "_KNOWN", {})
    return {"repos": [str(repo)], "store": str(tmp_path / "store"), "fetch": False, "github": False}, tmp_path


def report(words="The file is as stated."):
    return f"{BAD_Q}\n\n{words} {ANCHOR}"


def call(name, arguments):
    reply = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": name, "arguments": arguments}})
    return reply["result"]


def start(options, text):
    got = call("feedback_start", dict(options, text=text, requirements=REQUIRED))
    assert not got["isError"], got
    return got["structuredContent"]


def resolve_args(chain, feedback, original, corrected):
    return {"chain": chain, "feedback": feedback, "original_text": original, "corrected_text": corrected,
            "submission": repair.submission(feedback, original, corrected)}


def resolve(chain, feedback, original, corrected):
    return call("feedback_resolve", resolve_args(chain, feedback, original, corrected))


def trace_file(chain):
    return chains.directory(chain) / "trace.jsonl"


def code(got):
    assert got["isError"], got
    return got["structuredContent"]["code"]


def decisions(chain):
    return tr.replay(tr.loads(trace_file(chain).read_text(encoding="utf-8"))).decisions


def opened(world, words="The file is as stated."):
    options, _ = world
    original = report(words)
    started = start(options, original)
    return started, original, original.replace(BAD_Q, GOOD_Q)


# --- the loop ------------------------------------------------------------------------------------------------------

def test_a_misquote_is_corrected_through_the_mcp_tools(world):
    options, tmp = world
    started, original, corrected = opened(world)

    # (1) the server checks the report itself and opens the chain
    first = started["feedback"]
    assert started["state"] == {"disposition": "repair_requested", "task": "unmet", "iteration": 0,
                                "terminal": False}
    assert [(a["operation"], a["target"]["line"]) for a in first["recommended_actions"]] == [("correct_claim", 1)]
    assert started["receipt_line"].startswith("buddie FAIL (receipt-v1")
    assert sorted(p.name for p in chains.directory(started["chain"]).iterdir()) == ["options.json", "trace.jsonl"]

    # (2) the corrected quote is accepted on the server's own re-check
    got = resolve(started["chain"], first, original, corrected)
    assert not got["isError"], got
    out = got["structuredContent"]
    decision = out["decision"]
    assert decision["status"] == "accepted" and decision["outcome"] == "PASS"
    assert list(decision["resolved"].values()) == ["corrected"]
    assert out["state"] == {"disposition": "verified", "task": "met", "iteration": 1, "terminal": True}
    assert out["basis"] == "server"
    assert got["content"][0]["text"].startswith("buddie PASS (receipt-v1")
    written = trace_file(started["chain"]).read_bytes()
    assert tr.replay(tr.loads(written.decode("utf-8"))).disposition == "verified"

    # (3) the same call again is refused and writes nothing
    assert code(resolve(started["chain"], first, original, corrected)) == "duplicate_submission"
    assert trace_file(started["chain"]).read_bytes() == written


def test_no_tool_takes_a_receipt(world):
    options, tmp = world
    tools = {t["name"]: t for t in call_list()}
    for name in ("feedback_start", "feedback_resolve"):
        schema = tools[name]["inputSchema"]
        assert schema["additionalProperties"] is False and "receipt" not in schema["properties"]
    forged = {"predicateType": "https://github.com/tsyyan/buddie#receipt-v1", "predicate": {"outcome": "PASS"}}
    assert code(call("feedback_start", dict(options, text=f"{BAD_Q}\n", receipt=forged))) == "invalid_arguments"
    assert not (tmp / "state" / "feedback").exists()


def call_list():
    return mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]


def test_a_changed_feedback_is_refused_and_nothing_is_written(world):
    started, original, corrected = opened(world, "The file is as stated, too.")
    before = trace_file(started["chain"]).read_bytes()
    changed = copy.deepcopy(started["feedback"])
    changed["iteration_limit"] = 3
    assert code(resolve(started["chain"], changed, original, corrected)) == "forged_feedback"
    changed["feedback_id"] = fb.feedback_id({k: v for k, v in changed.items() if k != "feedback_id"})
    assert code(resolve(started["chain"], changed, original, corrected)) == "feedback_mismatch"
    assert trace_file(started["chain"]).read_bytes() == before


def test_deleting_the_required_quote_leaves_the_task_unmet(world):
    started, original, _ = opened(world, "The file is as stated, still.")
    got = resolve(started["chain"], started["feedback"], original,
                  original.replace(BAD_Q, "The vendor gave a time for the outage."))
    assert not got["isError"], got
    out = got["structuredContent"]
    assert out["decision"]["outcome"] == "PASS" and list(out["decision"]["resolved"].values()) == ["removed"]
    assert out["state"]["disposition"] == "requirements_unmet" and out["state"]["task"] == "unmet"
    assert tr.replay(tr.loads(trace_file(started["chain"]).read_text(encoding="utf-8"))).terminal


def test_both_tools_are_listed_locally_and_not_remotely():
    from buddie import remote
    listed = {t["name"]: t for t in call_list()}
    assert {"feedback_start", "feedback_resolve"} <= set(listed)
    assert all(listed[n]["inputSchema"]["additionalProperties"] is False for n in ("feedback_start", "feedback_resolve"))
    assert all(listed[n]["annotations"]["readOnlyHint"] is False for n in ("feedback_start", "feedback_resolve"))
    assert not {"feedback_start", "feedback_resolve"} & {t["name"] for t in remote.tools()}
    assert not {"feedback_start", "feedback_resolve"} & set(remote.HANDLERS)
    assert chains.OPTION_KEYS == set(mcp._CHECK_OPTIONS)


# --- concurrency: one submission per feedback ----------------------------------------------------------------------

def test_a_resolve_that_lands_while_another_is_checked_wins_alone(world, monkeypatch):
    """Deterministic interleaving: a second resolve commits while the first is re-verifying."""
    started, original, corrected = opened(world)
    real, inner = repair.reverify, []

    def racing(text, **kw):
        if not inner:
            inner.append(None)
            inner[0] = resolve(started["chain"], started["feedback"], original, corrected)
        return real(text, **kw)

    monkeypatch.setattr(repair, "reverify", racing)
    outer = resolve(started["chain"], started["feedback"], original, corrected)
    assert not inner[0]["isError"] and inner[0]["structuredContent"]["decision"]["status"] == "accepted"
    assert code(outer) == "duplicate_submission"
    assert len(decisions(started["chain"])) == 1


RESOLVER = """
import json, sys
from buddie import mcp
args = json.loads(open(sys.argv[1], encoding="utf-8").read())
reply = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "feedback_resolve", "arguments": args}})
sys.stdout.write(json.dumps(reply["result"]["structuredContent"]))
"""


def test_two_processes_resolving_at_once_resolve_once(world, tmp_path):
    started, original, corrected = opened(world)
    args = tmp_path / "args.json"
    args.write_text(json.dumps(resolve_args(started["chain"], started["feedback"], original, corrected)),
                    encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8")
    procs = [subprocess.Popen([sys.executable, "-c", RESOLVER, str(args)], cwd=ROOT, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    outs = [json.loads(p.communicate(timeout=120)[0].decode("utf-8")) for p in procs]
    accepted = [o for o in outs if "error" not in o]
    assert len(accepted) == 1 and accepted[0]["decision"]["status"] == "accepted", outs
    assert accepted[0]["basis"] == "agent_writable"  # another process: it knows the chain from its files only
    assert [o["code"] for o in outs if "error" in o][0] in ("duplicate_submission", "chain_changed")
    assert len(decisions(started["chain"])) == 1


# --- restarts, damaged and altered state ----------------------------------------------------------------------------

def test_after_a_restart_a_chain_resolves_once_and_says_on_what_basis(world):
    started, original, corrected = opened(world)
    chains._KNOWN.clear()  # the server restarted
    got = resolve(started["chain"], started["feedback"], original, corrected)
    assert got["structuredContent"]["decision"]["status"] == "accepted"
    assert got["structuredContent"]["basis"] == "agent_writable"
    chains._KNOWN.clear()
    assert code(resolve(started["chain"], started["feedback"], original, corrected)) == "duplicate_submission"
    assert len(decisions(started["chain"])) == 1


def _options_file(chain):
    return chains.directory(chain) / "options.json"


def test_damaged_state_is_refused_not_resolved(world):
    started, original, corrected = opened(world)
    chain, path = started["chain"], trace_file(started["chain"])
    good = path.read_bytes()
    path.write_bytes(good[:-20])                                 # a torn last line
    assert code(resolve(chain, started["feedback"], original, corrected)) == "state_corrupt"
    path.write_bytes(good)
    doc = json.loads(_options_file(chain).read_text(encoding="utf-8"))
    weaker = dict(doc, options=dict(doc["options"], store=str(Path(doc["options"]["store"]).parent / "other")))
    _options_file(chain).write_text(json.dumps(weaker), encoding="utf-8")   # a changed option, digest kept
    assert code(resolve(chain, started["feedback"], original, corrected)) == "state_corrupt"
    _options_file(chain).write_text(json.dumps(dict(doc, options=dict(doc["options"], fetch="yes"))), encoding="utf-8")
    assert code(resolve(chain, started["feedback"], original, corrected)) == "state_corrupt"
    assert decisions(chain) == ()


def test_altered_state_is_refused_while_the_server_knows_the_chain(world):
    started, original, corrected = opened(world)
    chain = started["chain"]
    doc = json.loads(_options_file(chain).read_text(encoding="utf-8"))
    altered = dict(doc["options"], store=str(Path(doc["options"]["store"]).parent / "other"))
    _options_file(chain).write_text(json.dumps(dict(doc, options=altered, sha256=chains.digest(chain, altered))),
                                    encoding="utf-8")   # consistent, digest and all
    assert code(resolve(chain, started["feedback"], original, corrected)) == "state_tampered"
    assert decisions(chain) == ()
    # without the server's memory the same files are read, and the result says they are the agent's
    chains._KNOWN.clear()
    got = resolve(chain, started["feedback"], original, corrected)
    assert got["structuredContent"]["basis"] == "agent_writable"


def test_a_rewritten_history_is_refused_while_the_server_knows_the_chain(world):
    started, original, corrected = opened(world)
    resolve(started["chain"], started["feedback"], original, corrected)
    records = tr.loads(trace_file(started["chain"]).read_text(encoding="utf-8"))
    trace_file(started["chain"]).write_bytes(tr.dumps(records[:2]).encode("utf-8"))  # the answer dropped
    assert code(resolve(started["chain"], started["feedback"], original, corrected)) == "state_tampered"


# --- failed writes at each stage -----------------------------------------------------------------------------------

@pytest.mark.parametrize("stage", ["options", "trace", "rename"])
def test_an_interrupted_start_leaves_no_chain_and_can_be_retried(world, monkeypatch, stage):
    options, tmp = world
    write, rename = chains._write, os.rename

    def failing_write(path, data):
        if path.name == f"{stage}.json" or path.name == f"{stage}.jsonl":
            raise OSError(28, "No space left on device")
        write(path, data)

    def failing_rename(a, b):
        raise OSError(28, "No space left on device")

    if stage == "rename":
        monkeypatch.setattr(chains.os, "rename", failing_rename)
    else:
        monkeypatch.setattr(chains, "_write", failing_write)
    got = call("feedback_start", dict(options, text=report(), requirements=REQUIRED))
    assert code(got) == "write_failed"
    assert list((tmp / "state" / "feedback").iterdir()) == []
    monkeypatch.setattr(chains, "_write", write)
    monkeypatch.setattr(chains.os, "rename", rename)
    start(options, report())


def test_a_crash_inside_a_start_leaves_only_a_temporary_directory(world):
    options, tmp = world
    started = start(options, report())
    leftover = chains.root() / f".{started['chain'].split(':')[1][:8]}.crashed"
    leftover.mkdir()
    (leftover / "options.json").write_text("{}", encoding="utf-8")
    start(options, report("Another text."))                    # not mistaken for a chain
    assert chains.count() == 2
    assert chains.prune(now=time.time() + chains.STALE + 1) == 1 and not leftover.exists()


def test_a_failed_commit_writes_nothing_and_the_retry_resolves(world, monkeypatch):
    started, original, corrected = opened(world)
    before = trace_file(started["chain"]).read_bytes()
    replace = os.replace

    def full(a, b):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(chains.os, "replace", full)
    assert code(resolve(started["chain"], started["feedback"], original, corrected)) == "write_failed"
    assert trace_file(started["chain"]).read_bytes() == before
    assert sorted(p.name for p in chains.directory(started["chain"]).iterdir()) == ["lock", "options.json",
                                                                                    "trace.jsonl"]
    monkeypatch.setattr(chains.os, "replace", replace)
    got = resolve(started["chain"], started["feedback"], original, corrected)
    assert got["structuredContent"]["decision"]["status"] == "accepted"
    assert len(decisions(started["chain"])) == 1


# --- retention and limits ------------------------------------------------------------------------------------------

def test_the_state_dir_is_bounded(world, monkeypatch):
    options, tmp = world
    monkeypatch.setattr(chains, "MAX_CHAINS", 1)
    old, original, corrected = opened(world)
    assert code(call("feedback_start", dict(options, text=report("A second text."), requirements=REQUIRED))) \
        == "state_full"
    past = time.time() - chains.RETENTION - 60
    for p in [chains.directory(old["chain"]), *chains.directory(old["chain"]).iterdir()]:
        os.utime(p, (past, past))
    start(options, report("A second text."))                   # the idle chain is removed to make room
    assert not chains.directory(old["chain"]).exists()
    assert code(resolve(old["chain"], old["feedback"], original, corrected)) == "unknown_chain"


def test_oversized_state_is_refused(world):
    started, original, corrected = opened(world)
    chain = started["chain"]
    with pytest.raises(chains.ChainError, match="options_too_large"):
        chains.create("sha256:" + "0" * 64, (), dict(chains.load(chain).options, repos=["r" * 100] * 1000))
    trace_file(chain).write_bytes(trace_file(chain).read_bytes() + b" " * chains.MAX_TRACE_BYTES)
    assert code(resolve(chain, started["feedback"], original, corrected)) == "state_corrupt"
    assert code(call("feedback_resolve", dict(resolve_args("sha256:../x", started["feedback"], original, corrected)))) \
        == "malformed_chain"


def test_an_oversized_initial_trace_is_not_published(world, monkeypatch):
    options, _ = world
    monkeypatch.setattr(chains, "MAX_TRACE_BYTES", 1024)
    got = call("feedback_start", dict(options, text=report(), requirements=REQUIRED))
    assert code(got) == "trace_too_large"
    assert not chains.root().exists()
    assert chains._KNOWN == {}


def guarded_state_reads(monkeypatch, limits):
    """Real files, but reject reads that would allocate unbounded attacker-written state."""
    original_open, sizes = Path.open, []

    class Reader:
        def __init__(self, raw, limit):
            self.raw, self.limit = raw, limit

        def __enter__(self):
            self.raw.__enter__()
            return self

        def __exit__(self, *args):
            return self.raw.__exit__(*args)

        def read(self, size=-1):
            sizes.append(size)
            assert 0 <= size <= self.limit + 1, "state read must be bounded before allocation"
            return self.raw.read(size)

    def open_state(path, mode="r", *args, **kwargs):
        raw = original_open(path, mode, *args, **kwargs)
        return Reader(raw, limits[path.name]) if mode == "rb" and path.name in limits else raw

    monkeypatch.setattr(Path, "open", open_state)
    return sizes


def test_load_reads_both_state_files_with_byte_limits(world, monkeypatch):
    started, _, _ = opened(world)
    sizes = guarded_state_reads(monkeypatch, {"trace.jsonl": chains.MAX_TRACE_BYTES,
                                            "options.json": chains.MAX_OPTIONS_BYTES})
    assert chains.load(started["chain"]).basis == "server"
    assert len(sizes) == 2


def test_commit_bounds_its_reread_and_refuses_oversized_changed_state(world, monkeypatch):
    started, original, corrected = opened(world)
    read = chains.load(started["chain"])
    got = repair.reverify(corrected, **mcp._checking(read.options))
    result = repair.resolve(read.records, started["feedback"], repair.submission(started["feedback"], original, corrected),
                            original=original, corrected=corrected, assessment=got)
    # A changed file is much larger than the allowed trace; keep the fixture small and the bound independently set.
    limit = len(tr.dumps(result.records).encode("utf-8")) + 1
    monkeypatch.setattr(chains, "MAX_TRACE_BYTES", limit)
    path = trace_file(started["chain"])
    path.write_bytes(b"x" * (limit + 100))
    before = path.read_bytes()
    with monkeypatch.context() as context:
        sizes = guarded_state_reads(context, {"trace.jsonl": limit})
        with pytest.raises(chains.ChainError, match="state_corrupt"):
            chains.commit(read, result.records, lambda state: pytest.fail("oversized state must not replay"))
        assert sizes
    assert path.read_bytes() == before


LOCKER = """
import sys
from buddie import chains
from pathlib import Path
try:
    with chains._locked(Path(sys.argv[1]), timeout=0.3):
        print("locked")
except chains.ChainError as error:
    print(error.code)
"""


def test_the_chain_lock_excludes_another_process(world):
    started, _, _ = opened(world)
    where = chains.directory(started["chain"])
    env = dict(os.environ, PYTHONPATH=str(ROOT))

    def other():
        return subprocess.run([sys.executable, "-c", LOCKER, str(where)], cwd=ROOT, env=env, capture_output=True,
                              text=True, timeout=60).stdout.strip()

    with chains._locked(where):
        assert other() == "chain_busy"
    assert other() == "locked"  # released with the holder, nothing stale left
