"""The context gate (NEXT №58): past 200k tokens a reply that is not the result is returned."""
from __future__ import annotations

import io
import json

import pytest

from buddie import context, hook


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("BUDDIE_FETCH", "0")
    monkeypatch.setenv("BUDDIE_GITHUB", "0")
    monkeypatch.setenv("VERBATIM_STORE", str(tmp_path / "store"))
    monkeypatch.setenv("BUDDIE_LOG", str(tmp_path / "hook.jsonl"))
    monkeypatch.setenv("BUDDIE_STATE", str(tmp_path / "pending"))
    monkeypatch.setenv("BUDDIE_REPOS", str(tmp_path / "norepo"))
    monkeypatch.delenv("BUDDIE_CONTEXT_LIMIT", raising=False)
    return tmp_path


def _transcript(path, read, sidechain=None):
    rows = [{"type": "assistant", "message": {"usage": {"input_tokens": 2, "cache_read_input_tokens": 1000,
                                                         "cache_creation_input_tokens": 10}}},
            {"type": "assistant", "message": {"usage": {"input_tokens": 3, "cache_read_input_tokens": read,
                                                         "cache_creation_input_tokens": 500, "output_tokens": 9}}},
            {"type": "user", "message": {"content": "ok"}}]
    if sidechain:
        rows.append({"type": "assistant", "isSidechain": True,
                     "message": {"usage": {"input_tokens": 1, "cache_read_input_tokens": sidechain}}})
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    return str(path)


def _send(text, transcript, tool="mcp__hearthbot__reply"):
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "session_id": "s1", "cwd": ".",
             "tool_input": {"text": text}, "transcript_path": transcript}
    err = io.StringIO()
    return hook.run(event, err), err.getvalue()


def test_last_context_sums_the_last_main_chain_call(tmp_path):
    assert context.last_context(_transcript(tmp_path / "t.jsonl", 250_000, sidechain=900_000)) == 250_503
    assert context.last_context(str(tmp_path / "missing.jsonl")) is None
    assert context.last_context(None) is None


def test_reply_past_the_limit_is_returned(env):
    code, err = _send("Беру ещё одну подзадачу.", _transcript(env / "t.jsonl", 250_000))
    assert code == 2
    assert "250k tokens is over 200k" in err
    entry = json.loads((env / "hook.jsonl").read_text().splitlines()[-1])
    assert entry["context"] == 250_503 and entry["reasons"] == {"context": 1}


def test_under_the_limit_final_handover_and_disclosure_pass(env):
    low = _transcript(env / "low.jsonl", 150_000)
    high = _transcript(env / "high.jsonl", 250_000)
    assert _send("Беру ещё одну подзадачу.", low)[0] == 0
    assert _send("Готово `⚓ pr:o/r#1=merged`\n\nСледующий шаг: новый тред.", high)[0] == 0
    assert _send("Передаю шаг координатору.", high, tool="mcp__claude-code-remote__send_message")[0] == 0
    code, _ = _send("Отвечаю на вопрос.\nbuddie: контекст треда 250 тыс., дальше лучше новым тредом", high)
    assert code == 0
    gate = json.loads((env / "hook.jsonl").read_text().splitlines()[-1])
    assert gate["context"] == 250_503


def test_limit_from_env(env, monkeypatch):
    high = _transcript(env / "t.jsonl", 250_000)
    monkeypatch.setenv("BUDDIE_CONTEXT_LIMIT", "0")
    assert _send("Беру ещё одну подзадачу.", high)[0] == 0
    monkeypatch.setenv("BUDDIE_CONTEXT_LIMIT", "300000")
    assert _send("Беру ещё одну подзадачу.", high)[0] == 0
    monkeypatch.setenv("BUDDIE_CONTEXT_LIMIT", "100000")
    assert _send("Беру ещё одну подзадачу.", _transcript(env / "u.jsonl", 150_000))[0] == 2


def test_stop_and_handover_are_never_held_for_context():
    assert context.over({"hook_event_name": "Stop"}, False, 250_000) is None
    assert context.over({"hook_event_name": "PreToolUse", "tool_name": "SendMessage"}, False, 250_000) is None
    assert context.over({"hook_event_name": "PreToolUse", "tool_name": "x"}, False, 250_000)


# --- inside a turn (NEXT №106) ------------------------------------------------------------------------------------

def _spawn(transcript, prompt="Собери выгрузку.", tool="Agent"):
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "session_id": "s1", "cwd": ".",
             "tool_input": {"description": "сбор", "prompt": prompt}, "transcript_path": transcript}
    err = io.StringIO()
    return hook.run(event, err), err.getvalue()


def test_subagent_launch_past_the_limit_is_returned(env):
    code, err = _spawn(_transcript(env / "t.jsonl", 250_000))
    assert code == 2 and "do not launch a subagent" in err
    entry = json.loads((env / "hook.jsonl").read_text().splitlines()[-1])
    assert entry["tool"] == "Agent" and entry["context"] == 250_503 and entry["reasons"] == {"context": 1}
    assert _spawn(_transcript(env / "u.jsonl", 250_000), tool="Task")[0] == 2


def test_subagent_launch_under_the_limit_or_disclosed_passes(env):
    assert _spawn(_transcript(env / "low.jsonl", 150_000))[0] == 0
    high = _transcript(env / "high.jsonl", 250_000)
    code, _ = _spawn(high, "Собери выгрузку.\nbuddie: контекст треда 250 тыс., запуск по просьбе пользователя")
    assert code == 0
    assert json.loads((env / "hook.jsonl").read_text().splitlines()[-1])["exit"] == 0


def _woken(path, read, final_turn_before=True, final_now=False):
    """A thread transcript: a final answer by `reply`, then (when woken) a new user turn, then work past `read`."""
    usage = {"input_tokens": 3, "cache_read_input_tokens": read, "cache_creation_input_tokens": 500}
    final = {"type": "tool_use", "name": "mcp__hearthbot__reply",
             "input": {"text": "Готово `⚓ pr:o/r#1=merged`\n\nСледующий шаг: №2."}}
    rows = [{"type": "user", "message": {"content": "сделай №1"}},
            {"type": "assistant", "message": {"content": [final], "usage": usage}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}}]
    if final_turn_before:
        rows.append({"type": "user", "message": {"content": "<github-webhook-activity>PR merged</github-webhook-activity>"}})
    rows.append({"type": "assistant", "message": {"content": [{"type": "text", "text": "Смотрю."}], "usage": usage}})
    if final_now:
        rows.append({"type": "assistant", "message": {"content": [final], "usage": usage}})
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return str(path)


def test_woken_thread_send_message_past_the_limit_is_returned(env):
    tool = "mcp__claude-code-remote__send_message"
    code, err = _send("Сделал ещё одну правку.", _woken(env / "w.jsonl", 250_000), tool=tool)
    assert code == 2 and "already handed in its result" in err
    # under the limit, a hand-over in the turn of the final answer, a new final answer, a disclosure: all pass
    assert _send("Сделал ещё одну правку.", _woken(env / "low.jsonl", 150_000), tool=tool)[0] == 0
    same = _woken(env / "same.jsonl", 250_000, final_turn_before=False)
    assert _send("Передаю шаг №2 координатору.", same, tool=tool)[0] == 0
    again = _woken(env / "again.jsonl", 250_000, final_now=True)
    assert _send("Передаю шаг №2 координатору.", again, tool="SendMessage")[0] == 0
    code, _ = _send("Ответ.\nbuddie: контекст треда 250 тыс., дальше лучше новым тредом",
                    _woken(env / "d.jsonl", 250_000), tool=tool)
    assert code == 0


def test_woken_reads_turns_not_tool_results(tmp_path):
    final = lambda t: "Следующий шаг:" in t  # noqa: E731
    assert context.woken(_woken(tmp_path / "a.jsonl", 1), final)
    assert not context.woken(_woken(tmp_path / "b.jsonl", 1, final_turn_before=False), final)
    assert not context.woken(_woken(tmp_path / "c.jsonl", 1, final_now=True), final)
    assert not context.woken(str(tmp_path / "missing.jsonl"), final) and not context.woken(None, final)
