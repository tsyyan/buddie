"""buddie 0.6, the summary with a choice card (audit/16, NEXT №61), on recorded hook events."""
from __future__ import annotations

import io
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from buddie import anchors, hook, mandate, mcp, summary

QUEUE = """| № | Шаг | Тема | Основание | Статус |
|---|---|---|---|---|
| 1 | Сделать этап | t | PLAN этап 1 | выполнено `⚓ NEXT.md@0000000` |
| 2 | Продолжить этап | t | PLAN этап 1 ← №1 | предложено |
| 3 | Новое направление | t | — | предложено |
| 4 | Починить сборку | t | fix ← №3 | предложено |
| 5 | Дождаться данных | t | — | предложено, ждёт условия: данные |
"""
ACCEPTED = "| Область | Слова |\n|---|---|\n| `PLAN этап 1` | «принимаем план» 2026-10-01 |\n"
CONFIG = """[mandate]
queue = "NEXT.md"
accepted = "ACCEPTED.md"
[[mandate.refs]]
pattern = 'PLAN этап (?P<stage>\\d+)'
doc = "PLAN.md"
level = "stage"
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("BUDDIE_FETCH", "0")
    monkeypatch.setenv("BUDDIE_GITHUB", "0")
    monkeypatch.setenv("VERBATIM_STORE", str(tmp_path / "store"))
    monkeypatch.setenv("BUDDIE_LOG", str(tmp_path / "hook.jsonl"))
    monkeypatch.setenv("BUDDIE_STATE", str(tmp_path / "pending"))
    monkeypatch.setenv("BUDDIE_REPOS", str(tmp_path / "norepo"))
    monkeypatch.delenv("BUDDIE_SESSIONS", raising=False)
    monkeypatch.delenv("BUDDIE_SUMMARY", raising=False)
    return tmp_path


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    (r / "NEXT.md").write_text(QUEUE)
    (r / "ACCEPTED.md").write_text(ACCEPTED)
    (r / "buddie.toml").write_text(CONFIG)
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    return r


def _event(name, session="s1", **kw):
    return dict({"hook_event_name": name, "session_id": session, "cwd": "."}, **kw)


def _run(event):
    err = io.StringIO()
    return hook.run(event, err), err.getvalue()


def _stop_sub(aid, text, session="s1", kind="general-purpose"):
    return _run(_event("SubagentStop", session, agent_id=aid, agent_type=kind, last_assistant_message=text,
                       stop_hook_active=False, agent_transcript_path=""))


def test_summary_demanded_only_when_no_subagent_is_left(env):
    _run(_event("SubagentStart", agent_id="a1", agent_type="Explore"))
    _run(_event("SubagentStart", agent_id="a2", agent_type="general-purpose"))
    assert _stop_sub("a1", "Нашёл три файла.\n\nСледующий шаг: №3 новое направление.", kind="Explore") == (0, "")
    assert _run(_event("Stop", stop_hook_active=False)) == (0, "")  # a2 is still running
    _stop_sub("a2", "Починил сборку.\n\nСледующий шаг: fix — починить тесты.")
    code, err = _run(_event("Stop", stop_hook_active=False))
    assert code == 2 and "новых результатов 2" in err and "summary" in err and "choice:" in err
    assert _run(_event("Stop", stop_hook_active=True)) == (0, "")  # never loops
    assert _run(_event("Stop", stop_hook_active=False)) == (0, "")  # once per batch of results
    _run(_event("SubagentStart", agent_id="a3"))
    _stop_sub("a3", "Ещё один результат.")
    assert _run(_event("Stop", stop_hook_active=False))[0] == 2


def test_summary_off_and_threshold(env, monkeypatch):
    _stop_sub("a1", "Готово.")
    monkeypatch.setenv("BUDDIE_SUMMARY_MIN", "2")
    assert _run(_event("Stop", stop_hook_active=False))[0] == 0
    _stop_sub("a2", "Готово тоже.")
    monkeypatch.setenv("BUDDIE_SUMMARY", "0")
    assert _run(_event("Stop", stop_hook_active=False))[0] == 0
    monkeypatch.delenv("BUDDIE_SUMMARY")
    assert _run(_event("Stop", stop_hook_active=False))[0] == 2


def test_no_state_no_demand_and_running_background_task(env):
    assert _run(_event("Stop", session="other", stop_hook_active=False)) == (0, "")
    _stop_sub("a1", "Готово.")
    busy = _event("Stop", stop_hook_active=False, background_tasks=[{"id": "t1", "status": "running"}])
    assert _run(busy)[0] == 0
    ended = _event("Stop", stop_hook_active=False, background_tasks=[{"id": "t1", "status": "completed"}])
    assert _run(ended)[0] == 2


def test_lost_subagent_does_not_hold_the_summary(env):
    _run(_event("SubagentStart", agent_id="old", agent_type="Explore"))
    _stop_sub("a1", "Готово.")
    with summary.editing("s1") as s:
        s["live"]["old"]["at"] = (datetime.now(timezone.utc) - timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert _run(_event("Stop", stop_hook_active=False))[0] == 2
    built = summary.build(summary.load("s1"))
    assert built["lost"][0]["agent_id"] == "old" and built["lost"][0]["quiet_minutes"] >= 45
    assert "Потеряно:" in built["text"] and built["live"] == []


def test_receipt_of_each_result(env):
    _stop_sub("a1", "Сделано: 3 из 4 проверок `⚓ README.md#0123456789ab`.\n\nСледующий шаг: №2.")
    r = summary.load("s1")["results"][0]
    assert r["outcome"] in ("GAPS", "FAIL") and r["anchors"][0]["anchor"] == "README.md#0123456789ab"
    assert r["next"] == ["№2."]


def test_build_with_queue_verdicts_and_card(env, repo):
    _stop_sub("a1", "Этап закрыт `⚓ pr:o/r#7=open`.\n\nСледующий шаг: №2 продолжить этап.")
    _stop_sub("a2", "Нашёл баг.\n\nСледующий шаг: №4 починить сборку.")
    _stop_sub("a3", "Идея.\n\nСледующий шаг: попробовать другой подход к поиску.")
    out = summary.summarize("s1", [repo])
    by = {s["key"]: s for s in out["next"]}
    assert by["№2"]["verdict"] == "auto" and by["№3"]["verdict"] == "ask" and by["№4"]["fix"]
    assert by["№5"]["waiting"]
    assert out["debt"]["launch"] == ["№2"] and out["debt"]["waiting"] == ["№5"]
    keys = [o["key"] for o in out["options"]]
    assert keys[0] == "№4" and keys[-1] == "none" and len(keys) == 4  # fix first, at most three, then «nothing»
    q = out["card"]["questions"][0]
    assert 2 <= len(q["options"]) <= 4 and q["multiSelect"] and all("," not in o["label"] for o in q["options"])
    assert out["card"]["metadata"]["source"] == f"buddie:{out['summary_id']}"
    assert out["effects"][0]["anchor"] == "pr:o/r#7=open"
    assert "Запускаю сам" in out["text"] and "№2" in out["text"]
    assert summary.summarize("s1", [repo])["summary_id"] == out["summary_id"]  # same input, same card


def test_step_from_a_failed_receipt_is_not_confirmed(env, repo):
    _stop_sub("a1", "Сделано `⚓ NEXT.md@deadbeef`.\n\nСледующий шаг: №2 продолжить этап.")
    r = summary.load("s1")["results"][0]
    assert r["outcome"] in ("FAIL", "GAPS")
    with summary.editing("s1") as s:
        s["results"][0]["outcome"] = "FAIL"
    out = summary.summarize("s1", [repo], queue=False)
    step = out["next"][0]
    assert step["basis_ok"] is False and step["verdict"] == "ask"
    assert "основание не подтверждено" in out["options"][0]["description"]


def _choose(sid_card, answer, session="s1", response=None):
    q = sid_card["questions"][0]
    tool_response = {"questions": sid_card["questions"], "answers": {q["question"]: answer}}
    if response:
        tool_response["response"] = response
    return _run(_event("PostToolUse", session, tool_name="AskUserQuestion", tool_use_id="toolu_9",
                       tool_input=sid_card, tool_response=tool_response))


def test_choice_goes_to_the_journal_and_backs_the_anchor(env, repo):
    _stop_sub("a1", "Нашёл баг.\n\nСледующий шаг: №4 починить сборку.\nСледующий шаг: попробовать иначе.")
    out = summary.summarize("s1", [repo])
    labels = [o["label"] for o in out["options"]]
    assert _choose(out["card"], f"{labels[0]}, {labels[1]}") == (0, "")
    line = [json.loads(x) for x in (env / "hook.jsonl").read_text().splitlines()][-1]
    assert line["choice"]["summary_id"] == out["summary_id"]
    assert line["choice"]["chosen"] == [out["options"][0]["key"], out["options"][1]["key"]]
    assert "exit" not in line  # not a gate check: lessons and measure skip it
    sid = out["summary_id"]
    assert anchors.check_one(f"choice:{sid}=№4", [], {})["status"] == "HOLDS"
    assert anchors.check_one(f"choice:{sid}={out['options'][1]['key'][1:]}", [], {})["status"] == "HOLDS"
    assert anchors.check_one(f"choice:{sid}={labels[0]}", [], {})["status"] == "HOLDS"
    assert anchors.check_one(f"choice:{sid}=№99", [], {})["status"] == "BROKEN"
    assert anchors.check_one("choice:000000000000=№4", [], {})["status"] == "UNCHECKABLE"
    state = summary.load("s1")
    assert all(r["summarized"] for r in state["results"]) and state["shown"]
    assert _run(_event("Stop", stop_hook_active=False))[0] == 0
    again = summary.summarize("s1", [repo])
    assert "№4" not in [s["key"] for s in again["next"]]  # chosen, so launched
    left = [s for s in again["next"] if s["text"] == "попробовать иначе."]
    assert left and left[0]["shown"]  # not chosen: stays, marked as shown
    assert "показан с" in again["text"]


def test_other_text_is_kept_and_counts(env, repo):
    _stop_sub("a1", "Готово.\n\nСледующий шаг: №3 новое направление.")
    out = summary.summarize("s1", [repo])
    _choose(out["card"], "запусти №5 сейчас")
    c = [json.loads(x) for x in (env / "hook.jsonl").read_text().splitlines()][-1]["choice"]
    assert c["chosen"] == [] and c["other"] == ["запусти №5 сейчас"]
    assert anchors.check_one(f"choice:{out['summary_id']}=№5", [], {})["status"] == "HOLDS"
    assert anchors.check_one(f"choice:{out['summary_id']}=№3", [], {})["status"] == "BROKEN"


def test_plain_ask_user_question_is_journaled_by_tool_use_id(env):
    card = {"questions": [{"question": "Публикуем?", "header": "Публикация", "multiSelect": False,
                           "options": [{"label": "Да", "description": ""}, {"label": "Нет", "description": ""}]}]}
    _choose(card, "Да")
    assert anchors.check_one("choice:toolu_9=Да", [], {})["status"] == "HOLDS"


def test_consent_backed_by_a_choice(env, repo):
    _stop_sub("a1", "Готово.\n\nСледующий шаг: №3 новое направление.")
    out = summary.summarize("s1", [repo])
    _choose(out["card"], [o["label"] for o in out["options"] if o["key"] == "№3"][0])
    cfg = mandate.load_config(repo)
    good = mandate.check_text(f"Запустил №3 по выбору пользователя `⚓ choice:{out['summary_id']}=№3`.", cfg)
    bad = mandate.check_text(f"Запустил №4 по выбору пользователя `⚓ choice:{out['summary_id']}=№4`.", cfg)
    assert [c["status"] for c in good if c["kind"] == "consent"] == ["HOLDS"]
    assert [c["status"] for c in bad if c["kind"] == "consent"] == ["BROKEN"]
    assert [c["status"] for c in mandate.check_text("Запустил по выбору пользователя.", cfg)
            if c["kind"] == "consent"] == ["UNSUPPORTED"]


def test_queue_only_summary_without_a_session(env, repo):
    out = summary.summarize(None, [repo])
    assert out["session"] is None and out["done"] == [] and {s["key"] for s in out["next"]} == {"№2", "№3", "№4", "№5"}


def test_mcp_and_cli(env, repo, capsys):
    _stop_sub("a1", "Готово.\n\nСледующий шаг: №3 новое направление.")
    reply = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "summary", "arguments": {"session": "s1", "repos": [str(repo)]}}})
    assert reply["result"]["content"][0]["text"].startswith("Сводка buddie")
    assert reply["result"]["structuredContent"]["card"]
    from buddie.cli import main
    assert main(["summary", "--session", "s1", "--repo", str(repo), "--text"]) == 0
    text = capsys.readouterr().out
    assert text.startswith("Сводка buddie") and '"metadata"' in text.splitlines()[-1]


# --- the live run (NEXT №70): recorded events of a cloud session, dogfood/summary-live ----------------------------

LIVE = Path(__file__).resolve().parents[1] / "dogfood" / "summary-live"


def _live(name):
    if not (LIVE / name).is_file():
        pytest.skip("dogfood/ is not exported")
    return [json.loads(x) for x in (LIVE / name).read_text(encoding="utf-8").splitlines()]


def _live_transcript(tmp_path, file):
    """A transcript with the recorded entry of `file` (the hook reads only these)."""
    path = tmp_path / file.replace("/", "_")
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in _live("transcripts.jsonl")
                            if e["file"] == file), encoding="utf-8")
    return str(path)


def test_live_subagent_stop_reads_the_handback(env):
    stops = [e for e in _live("events.jsonl") if e["hook_event_name"] == "SubagentStop" and e["agent_type"]]
    assert len(stops) == 4 and all("last_assistant_message" not in e for e in stops)
    session = env / "session.jsonl"  # run: anchors are found in the session's subagents/ (the recorded /root/... is not)
    session.write_text("", encoding="utf-8")
    (env / "session" / "subagents").mkdir(parents=True)
    for e in stops:
        file = f"subagents/agent-{e['agent_id']}.jsonl"
        e["agent_transcript_path"] = str((env / "session" / file).with_name(file.split("/")[1]))
        Path(_live_transcript(env, file)).rename(e["agent_transcript_path"])
        e["transcript_path"] = str(session)
        assert _run(e)[0] == 0
    results = {r["agent_id"]: r for r in summary.load(stops[0]["session_id"])["results"]}
    assert results["a9f2c249e6b6cbe84"]["next"] == ["№68 перепрогон ворот E016 на buddie 0.5.1"]
    assert results["a4ba79392036ffb6f"]["next"] == ["№69 buddie 0.7 ворота запуска и обещания"]
    a, b = results["a1eabca40425754a7"], results["a9fecd79d95f03e52"]  # the second batch, with anchors
    assert a["outcome"] == "PASS" and a["next"] == ["№68 перепрогон ворот E016 на buddie 0.5.1"]
    assert b["outcome"] == "FAIL" and b["next"] == ["№69 buddie 0.7 ворота запуска и обещания"]
    assert [x["status"] for x in b["anchors"] if x["anchor"].endswith("=> NO SUCH OUTPUT")] == ["BROKEN"]


def test_live_stop_demanding_the_summary_is_logged_with_exit_2(env):
    """Event 16 of the live run: the gate let the answer out, run() returned it for the summary (NEXT №72)."""
    events = _live("events.jsonl")
    stop = events[15]
    assert stop["hook_event_name"] == "Stop" and not stop["stop_hook_active"]
    session = stop["session_id"]
    main = env / "main.jsonl"  # the recorded main transcript holds only the cards: its last answer is the event's
    main.write_text(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": stop["last_assistant_message"]}]}}, ensure_ascii=False) + "\n", encoding="utf-8")
    for e in events[:15]:
        e["transcript_path"] = str(main)  # the recorded /root/... is unreadable on a CI runner
        if e["hook_event_name"] == "SubagentStart":
            _run(e)
        elif e["hook_event_name"] == "SubagentStop" and e["agent_type"]:
            file = f"subagents/agent-{e['agent_id']}.jsonl"
            e["agent_transcript_path"] = _live_transcript(env, file)
            _run(e)
    stop["transcript_path"] = str(main)
    code, err = _run(stop)
    assert code == 2 and err
    line = [json.loads(x) for x in (env / "hook.jsonl").read_text().splitlines()][-1]
    assert line["event"] == "Stop" and line["exit"] == 2 and line["demand"]
    lines = (env / "hook.jsonl").read_text().count("\n")
    assert _run(dict(stop, stop_hook_active=True)) == (0, "")  # the re-entered Stop passes
    after = (env / "hook.jsonl").read_text().splitlines()  # with only a heartbeat line (NEXT №118)
    assert len(after) == lines + 1 and json.loads(after[-1])["beat"] and json.loads(after[-1])["active"]


def test_live_compaction_stop_is_not_a_result(env):
    stop = [e for e in _live("events.jsonl") if e["hook_event_name"] == "SubagentStop" and not e["agent_type"]]
    assert len(stop) == 1 and stop[0]["last_assistant_message"].startswith("<analysis>")
    assert _run(stop[0])[0] == 0
    assert summary.load(stop[0]["session_id"])["results"] == []


@pytest.mark.parametrize("k, sid, chosen, other, wrong", [
    (0, "709d076ad2ee", ["№66", "№51"], ["попробуем мультивыбор, надеюсь ничего не сломается"], "№68"),
    (1, "eae76f25b137", ["№51"], [], "№66")])
def test_live_choice_finds_the_card_metadata_in_the_transcript(env, k, sid, chosen, other, wrong):
    choice = [e for e in _live("events.jsonl") if e["hook_event_name"] == "PostToolUse"][k]
    assert "metadata" not in choice["tool_input"]  # Claude Code drops it from the hook input
    state = json.loads((LIVE / "state.json").read_text(encoding="utf-8"))
    session = choice["session_id"]
    summary.state_file(session).parent.mkdir(parents=True, exist_ok=True)
    summary.state_file(session).write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    choice["transcript_path"] = _live_transcript(env, f"{session}.jsonl")
    assert _run(choice)[0] == 0
    c = [json.loads(x) for x in (env / "hook.jsonl").read_text().splitlines()][-1]["choice"]
    assert c["summary_id"] == sid and c["chosen"] == chosen and c["other"] == other
    for step in chosen:
        assert anchors.check_one(f"choice:{sid}={step}", [], {})["status"] == "HOLDS"
        assert anchors.check_one(f"choice:{sid}={step.lstrip('№')}", [], {})["status"] == "HOLDS"
    assert anchors.check_one(f"choice:{sid}={wrong}", [], {})["status"] == "BROKEN"
