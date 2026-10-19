"""buddie 0.5, the closed loop (NEXT №55): how the gate was passed, lessons at session start, ready anchors."""
from __future__ import annotations

import io
import json

import pytest

from buddie import hook, journal, suggest

FINAL = "Сделано: 3 из 4 проверок прошли.\n\nСледующий шаг: повторить."


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("BUDDIE_FETCH", "0")
    monkeypatch.setenv("BUDDIE_GITHUB", "0")
    monkeypatch.setenv("VERBATIM_STORE", str(tmp_path / "store"))
    monkeypatch.setenv("BUDDIE_LOG", str(tmp_path / "hook.jsonl"))
    monkeypatch.setenv("BUDDIE_STATE", str(tmp_path / "pending"))
    monkeypatch.setenv("BUDDIE_REPOS", str(tmp_path / "norepo"))
    return tmp_path


def _transcript(path, calls):
    rows = []
    for i, (cmd, out) in enumerate(calls):
        rows.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": f"toolu_{i}", "name": "Bash", "input": {"command": cmd}}]}})
        rows.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"toolu_{i}", "content": out}]}})
    path.write_text("\n".join(json.dumps(r) for r in rows))
    return str(path)


def _send(text, session="s1", transcript=None, cwd="."):
    event = {"hook_event_name": "PreToolUse", "tool_name": "mcp__hearthbot__reply", "session_id": session,
             "cwd": cwd, "tool_input": {"text": text}, "transcript_path": transcript}
    err = io.StringIO()
    return hook.run(event, err), err.getvalue()


def _log(env):
    return [json.loads(x) for x in (env / "hook.jsonl").read_text().splitlines()]


def test_pass_through_proof_is_journaled(env):
    t = _transcript(env / "t.jsonl", [("python -m pytest -q tests", "....\n3 из 4 проверок прошли\n")])
    code, err = _send(FINAL, transcript=t, cwd=str(env))
    assert code == 2
    assert "Ready anchors" in err and "`⚓ run:python -m pytest -q tests => 3 из 4 проверок прошли`" in err
    fixed = "Сделано: 3 из 4 проверок прошли `⚓ run:python -m pytest -q tests => 3 из 4 проверок прошли`.\n\n" \
            "Следующий шаг: повторить."
    assert _send(fixed, transcript=t, cwd=str(env))[0] == 0
    first, second = _log(env)
    assert first["reasons"] == {"final_no_anchor": 1, "final_bare": 1} and "gate" not in first
    assert second["gate"]["way"] == "proof" and second["gate"]["proved"] == 2
    assert not list((env / "pending").glob("*.json"))  # state is dropped once the gate is passed


def test_pass_through_removal_and_disclosure(env):
    assert _send(FINAL, cwd=str(env))[0] == 2
    assert _send("Сделано, но без чисел. `⚓ run:ls`\n\nСледующий шаг: повторить.", cwd=str(env))[0] == 0
    assert _log(env)[-1]["gate"]["way"] in ("removal", "mixed")
    assert _send(FINAL, session="s2", cwd=str(env))[0] == 2
    assert _send(FINAL + "\nbuddie: считал вручную", session="s2", cwd=str(env))[0] == 0
    assert _log(env)[-1]["gate"]["way"] == "disclosure"


def test_returned_again_then_proof(env):
    assert _send(FINAL, cwd=str(env))[0] == 2
    assert _send(FINAL.replace("Сделано", "Готово"), cwd=str(env))[0] == 2
    assert _log(env)[-1]["gate"] == {"proved": 0, "removed": 0, "kept": 2, "disclosed": False, "way": "returned"}


def test_passage_quote_fixed_is_proof_and_dropped_is_removal():
    before = [{"kind": "quote", "line": 1, "text": "He said “the outage began at 14:58 UTC” ([r](https://x.org))."}]
    fixed = "He said “the outage began at 14:59 UTC” ([r](https://x.org))."
    assert journal.passage(before, fixed, [], 0)["way"] == "proof"
    assert journal.passage(before, "Nothing to report here at all.", [], 0)["way"] == "removal"
    bare = [{"kind": "final_bare", "line": 1, "text": "Сделано: 3 из 4 проверок прошли."}]
    assert journal.passage(bare, "Сделано: проверки прошли.", [], 0)["removed"] == 1  # same line, count dropped


def test_session_start_prints_lessons_of_past_sessions(env, monkeypatch):
    assert _send(FINAL, session="old", cwd=str(env))[0] == 2
    assert _send("ok `⚓ run:ls`\n\nСледующий шаг: дальше.", session="old", cwd=str(env))[0] == 0
    out = io.StringIO()
    assert hook.session_start({"session_id": "new"}, out) == 0
    text = out.getvalue()
    assert "1 past sessions" in text and "final answer with no anchor (1)" in text and "number with no anchor" in text
    assert len(text.strip().splitlines()) <= 10
    out = io.StringIO()
    hook.session_start({"session_id": "old"}, out)  # its own lines are not a lesson for itself
    assert out.getvalue() == ""
    monkeypatch.setenv("BUDDIE_LESSONS", "0")
    out = io.StringIO()
    hook.session_start({"session_id": "new"}, out)
    assert out.getvalue() == ""


def test_lessons_read_pre_05_journal(tmp_path):
    rows = [{"at": "2026-10-03T01:00:00Z", "session": "a", "exit": 2, "outcome": "FAIL", "final": False},
            {"at": "2026-10-03T01:01:00Z", "session": "a", "exit": 0, "outcome": "PASS", "final": True},
            {"at": "2026-10-03T02:00:00Z", "session": "b", "exit": 0, "outcome": "GAPS", "final": True}]
    text = journal.lessons(rows)
    assert "2 past sessions" in text and "1 of 2 sessions" in text and "FAIL before 0.5 (quote or anchor) (1)" in text


def test_measure_shares():
    rows = [{"at": "2026-10-04T01:00:00Z", "session": "a", "exit": 2},
            {"at": "2026-10-04T01:01:00Z", "session": "a", "exit": 0, "gate": {"way": "proof"}},
            {"at": "2026-10-04T02:00:00Z", "session": "b", "exit": 0},
            {"at": "2026-10-04T03:00:00Z", "session": "c", "exit": 2},
            {"at": "2026-10-04T03:01:00Z", "session": "c", "exit": 0, "gate": {"way": "removal"}},
            {"at": "2026-10-02T03:00:00Z", "session": "z", "exit": 2}]
    m = journal.measure(rows, since="2026-10-04", sessions=10)
    assert m["sessions"] == 3 and m["first_message_passed"] == 1
    assert m["proof_share"] == 0.5 and m["removal_share"] == 0.5
    assert journal.measure(rows, since="2026-10-04", sessions=2)["sessions"] == 2


def test_ready_anchors_from_github_are_checked():
    pull = {"state": "open", "draft": False, "merged": False, "merge_commit_sha": None,
            "head": {"sha": "abcdef1234567890"}}
    runs = {"check_runs": [{"name": "ci", "status": "completed", "conclusion": "success"}]}

    def get(path):
        if path == "/repos/o/r/pulls/7":
            return pull
        if "/check-runs" in path:
            return runs
        if path.endswith("/status"):
            return {"statuses": []}
        return None

    items = [{"kind": "final_no_anchor", "line": None, "text": ""}]
    out = suggest.ready_anchors("PR https://github.com/o/r/pull/7 открыт.", items, github=get)
    assert out == ["- `⚓ pr:o/r#7=open@abcdef123456`", "- `⚓ ci:o/r@abcdef123456=success`"]
    assert suggest.ready_anchors("x", [{"kind": "quote", "line": 1, "text": "x"}], github=get) == []


def test_ready_run_anchor_never_offers_an_echo(tmp_path):
    t = _transcript(tmp_path / "t.jsonl", [('echo "41 passed"', "41 passed")])
    items = [{"kind": "final_bare", "line": 1, "text": "41 passed"}]
    assert suggest.ready_anchors("41 passed", items, transcript=t) == []


def test_hooks_json_has_session_start():
    from pathlib import Path
    cfg = json.loads((Path(__file__).resolve().parents[1] / "hooks" / "hooks.json").read_text())
    assert "SessionStart" in cfg["hooks"]


def test_ready_run_anchor_skips_the_claim_read_back(tmp_path):
    claim = "Сделано: модуль собран, тесты: 47 passed."
    t = _transcript(tmp_path / "t.jsonl", [("python -m pytest -q", "47 passed in 2.6s"),
                                          ("python check_draft.py", f"line 1: {claim}")])
    items = [{"kind": "final_bare", "line": 1, "text": claim}]
    assert suggest.ready_anchors(claim, items, transcript=t) == ["- line 1: `⚓ run:python -m pytest -q => 47 passed in 2.6s`"]


def test_ready_run_anchor_skips_a_draft_with_another_first_word(tmp_path):
    claim = "Итог: buddie 0.5, PR https://github.com/o/r/pull/7, тесты: 47 passed."
    draft = "line 1: Сделано: buddie 0.5, PR https://github.com/o/r/pull/7, тесты: 47 passed in the draft"
    t = _transcript(tmp_path / "t.jsonl", [("python -m pytest -q", "47 passed in 2.6s"), ("python check.py", draft)])
    items = [{"kind": "final_bare", "line": 1, "text": claim}]
    assert suggest.ready_anchors(claim, items, transcript=t) == ["- line 1: `⚓ run:python -m pytest -q => 47 passed in 2.6s`"]


def test_prose_claim_gets_a_ready_run_anchor_and_passes_by_proof(env):
    """NEXT №63: a final answer that claims tests passed in prose is returned with the run that shows it."""
    t = _transcript(env / "t.jsonl", [("python -m pytest -q tests", "....\n47 passed in 2.6s\n")])
    text = "Готово, тесты прошли: 47 passed.\n\nСледующий шаг: повторить."
    code, err = _send(text, transcript=t, cwd=str(env))
    assert code == 2 and "work claimed in prose, line 1" in err
    assert "- line 1: `⚓ run:python -m pytest -q tests => 47 passed in 2.6s`" in err
    fixed = text.replace("47 passed.", "47 passed `⚓ run:python -m pytest -q tests => 47 passed in 2.6s`.")
    assert _send(fixed, transcript=t, cwd=str(env))[0] == 0
    first, second = _log(env)
    assert first["reasons"]["prose"] == 1 and second["gate"]["way"] == "proof"


def test_prose_claim_without_a_count_gets_the_latest_run(tmp_path):
    t = _transcript(tmp_path / "t.jsonl", [("python -m pytest -q tests", "....\n12 passed in 0.4s\n")])
    items = [{"kind": "prose", "line": 1, "text": "Тесты прошли."}]
    assert suggest.ready_anchors("Тесты прошли.", items, transcript=t) == [
        "- `⚓ run:python -m pytest -q tests => 12 passed in 0.4s`"]


def test_session_start_and_empty_stop_write_heartbeats(env):
    """NEXT №118: SessionStart and a Stop with no text each leave a short line; the gate's counts skip them."""
    assert hook.run({"hook_event_name": "SessionStart", "session_id": "hb", "source": "startup"}) == 0
    t = env / "empty.jsonl"
    t.write_text(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "toolu_0", "name": "mcp__hearthbot__reply", "input": {"text": "x"}}]}}))
    assert hook.run({"hook_event_name": "Stop", "session_id": "hb", "transcript_path": str(t)}, io.StringIO()) == 0
    assert hook.run({"hook_event_name": "Stop", "session_id": "hb", "stop_hook_active": True}, io.StringIO()) == 0
    start, stop, again = _log(env)
    assert {k: start[k] for k in ("event", "session", "beat", "source", "exit")} == {
        "event": "SessionStart", "session": "hb", "beat": True, "source": "startup", "exit": 0}
    assert stop["event"] == "Stop" and stop["empty"] and stop["exit"] == 0 and not stop["active"]
    assert again["active"] and set(start) >= {"at", "event", "session", "exit"}
    assert journal.entries([env / "hook.jsonl"]) == []
    out = io.StringIO()
    hook.session_start({"session_id": "other"}, out)
    assert out.getvalue() == ""  # heartbeats are not lessons


def test_heartbeat_goes_to_shared_folder(env, monkeypatch):
    monkeypatch.setenv("BUDDIE_SHARED_LOG", str(env / "shared"))
    hook.run({"hook_event_name": "SessionStart", "session_id": "hb2"})
    line = json.loads((env / "shared" / "hb2.jsonl").read_text())
    assert line["event"] == "SessionStart" and line["beat"]
