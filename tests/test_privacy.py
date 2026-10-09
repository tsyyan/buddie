"""The plugin's default journal keeps receipts only (NEXT №104, audit/22 §3.2 п. 2): no words of the conversation.

The plugin directory policy: «Software must not collect extraneous conversation data, even for logging purposes».
Every gate line was a receipt already (counts, verdicts, sha256); promise and choice lines kept sentences and answers.
Without [journal] text = true they keep hashes and queue numbers, and the choice: anchor and the promise loop work
the same. conftest.py sets BUDDIE_JOURNAL_TEXT=1 for lab's own tests; these tests drop it.
"""
from __future__ import annotations

import json

import pytest

from buddie import anchors, config, promises, summary
from tests import test_promises as tp
from tests import test_summary as ts

SECRET = "запусти №5 сейчас, пароль кот"


@pytest.fixture(autouse=True)
def _receipts_only(monkeypatch):
    monkeypatch.delenv("BUDDIE_JOURNAL_TEXT", raising=False)


def _journal(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def test_default_is_receipts_and_the_file_or_env_turn_text_on(monkeypatch):
    assert config.journal_text({}) is False
    assert config.journal_text({"journal": {"text": True}}) is True
    assert config.journal_text({"journal": {"text": "yes"}}) is False  # only a TOML true
    monkeypatch.setenv("BUDDIE_JOURNAL_TEXT", "1")
    assert config.journal_text({}) is True
    monkeypatch.setenv("BUDDIE_JOURNAL_TEXT", "0")
    assert config.journal_text({"journal": {"text": True}}) is False
    assert "[journal]\ntext = false" in config.TEMPLATE


def test_choice_line_has_no_words_and_still_backs_the_anchor(tmp_path, monkeypatch):
    env = ts.env.__wrapped__(tmp_path, monkeypatch)
    repo = ts.repo.__wrapped__(tmp_path)
    ts._stop_sub("a1", "Нашёл баг.\n\nСледующий шаг: №4 починить сборку.\nСледующий шаг: попробовать иначе.")
    out = summary.summarize("s1", [repo])
    labels = [o["label"] for o in out["options"]]
    assert ts._choose(out["card"], labels[0]) == (0, "")
    raw = (env / "hook.jsonl").read_text(encoding="utf-8")
    c = _journal(env / "hook.jsonl")[-1]["choice"]
    assert set(c) == {"id", "summary_id", "picked", "other_rows", "questions", "options"}
    assert labels[0] not in raw and out["card"]["questions"][0]["question"] not in raw
    sid = out["summary_id"]
    assert anchors.check_one(f"choice:{sid}={out['options'][0]['key']}", [], {})["status"] == "HOLDS"
    assert anchors.check_one(f"choice:{sid}={labels[0]}", [], {})["status"] == "HOLDS"
    assert anchors.check_one(f"choice:{sid}=№99", [], {})["status"] == "BROKEN"


def test_typed_answer_keeps_only_its_numbers(tmp_path, monkeypatch):
    env = ts.env.__wrapped__(tmp_path, monkeypatch)
    repo = ts.repo.__wrapped__(tmp_path)
    ts._stop_sub("a1", "Готово.\n\nСледующий шаг: №3 новое направление.")
    out = summary.summarize("s1", [repo])
    ts._choose(out["card"], SECRET)
    raw = (env / "hook.jsonl").read_text(encoding="utf-8")
    assert "пароль" not in raw and "кот" not in raw
    assert _journal(env / "hook.jsonl")[-1]["choice"]["other_rows"] == ["5"]
    assert anchors.check_one(f"choice:{out['summary_id']}=№5", [], {})["status"] == "HOLDS"
    assert anchors.check_one(f"choice:{out['summary_id']}=№3", [], {})["status"] == "BROKEN"


def test_promise_line_keeps_a_hash_and_the_loop_still_works(tmp_path, monkeypatch, capsys):
    repo = tp.repo.__wrapped__(tmp_path, monkeypatch)
    sha = tp._merge(repo, 53)
    text = tp.PROMISE_42.format(sha=sha)
    code, err = tp._stop("coord", text, tmp_path)
    assert code == 2 and "запуск №42" in err and "lab#53" in err  # the return does not need the sentence
    [line] = tp._journal(tmp_path, "promise")
    p = line["promise"]
    assert "text" not in p and len(p["sha256"]) == 64 and p["row"] == 42
    raw = (tmp_path / "hook.jsonl").read_text(encoding="utf-8")
    assert "запущу" not in raw.casefold() and "Вердикт" not in raw
    assert tp._run({"hook_event_name": "SessionStart", "session_id": "coord2"}) == (0, "")
    assert "запуск №42, после влития lab#53" in capsys.readouterr().out
    assert promises.open_promises([repo], None)  # still open until the launch


def test_decision_card_and_pick_lines_have_no_words(tmp_path, monkeypatch):
    from tests import test_decisions as td
    env = td.env.__wrapped__(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)  # no buddie.toml around: the plugin's default, not lab's [journal] text = true
    t1 = td._write(env, "s1.jsonl", td._entries(pick=None))
    assert td.hook.run({"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "mcp__hearthbot__ask_decision",
                        "tool_input": td.ASK, "tool_response": [{"type": "text", "text": td.RESULT}]},
                       td.io.StringIO()) == 0
    t2 = td._write(env, "s2.jsonl", td._entries(card=False, pick=td.wake()))
    for _ in range(2):
        td.decisions.sync({"session_id": "s2", "transcript_path": t2})
    raw = (env / "hook.jsonl").read_text(encoding="utf-8")
    assert "buddie" not in raw and "релиз" not in raw and "Пауза" not in raw  # no question, label or consequence
    lines = _journal(env / "hook.jsonl")
    assert len([x for x in lines if "card" in x]) == 1 and len([x for x in lines if "choice" in x]) == 1
    assert td.check("№78", t2)["status"] == "HOLDS" and td.check("Всё по buddie", t2)["status"] == "HOLDS"
    assert td.check("№96", None)["status"] == "HOLDS" and td.check("№95", None)["status"] == "BROKEN"
    card = td.decisions.journal_cards()[td.CARD_ID]
    assert "question" not in card and card["options"][1]["steps"] == ["№105", "№96", "№104", "№101", "№78"]
    other = td.decisions.choice({"id": td.CARD_ID, "index": 1, "label": "Внешнее"}, card)
    assert other["chosen"] == []  # the wake's label does not hash to option B's: no steps
