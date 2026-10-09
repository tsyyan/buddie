"""A time condition comes due in the launch gate and the summary, not only in lab's chain.py (lab NEXT №83).

Before 0.7.3 promises.py and summary.py called `Mandate.verdict(n)` with no moment, so a row «сутки после влития №1»
stayed `ask` «waits for a condition» forever there, while `chain.py debt` already moved it to `launch` (NEXT №76).
Now both judge at the clock, the delay counted from the commit of the queue's first-parent history that brought the
row's text (the merge of its parent's PR), as chain.py `_appeared` does.
"""
from __future__ import annotations

import io
import os
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from buddie import hook, mandate as man, summary

QUEUE = """| № | Шаг | Тема | Основание | Статус |
|---|---|---|---|---|
| 1 | Сделать этап | t | PLAN этап 1 | выполнено `⚓ NEXT.md@0000000` |
| 2 | Замерить через сутки после влития №1 | t | PLAN этап 1 ← №1 | предложено |
| 3 | Снять данные через сутки | t | PLAN этап 1 ← №1 | предложено, ждёт условия |
"""
ACCEPTED = "| Область | Слова |\n|---|---|\n| `PLAN этап 1` | «принимаем план» 2026-10-01 |\n"
CONFIG = """[mandate]
queue = "NEXT.md"
accepted = "ACCEPTED.md"
waiting = "ждёт условия"
wait_words = '\\bчерез (?:сутки|\\d+ (?:час|дн|сут|недел)\\w*)|\\bне раньше \\d{4}-\\d{2}-\\d{2}'
wait_not_before = 'не раньше (?P<date>\\d{4}-\\d{2}-\\d{2})(?:[ T](?P<time>\\d{2}:\\d{2}))?'
wait_delay = '(?:через )?(?:(?P<k>\\d+) )?(?P<unit>сут|час|дн|недел)\\w*(?: после)?'
wait_units = { "сут" = 24, "час" = 1, "дн" = 24, "недел" = 168 }
[[mandate.refs]]
pattern = 'PLAN этап (?P<stage>\\d+)'
doc = "PLAN.md"
level = "stage"

[launch]
tools = 'Agent'
"""


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _repo(tmp_path, monkeypatch, hours_ago: float):
    """The queue committed `hours_ago` before now, then a later edit of another file; returns (repo, sha, time)."""
    r = tmp_path / "repo"
    r.mkdir()
    for name, text in (("NEXT.md", QUEUE), ("ACCEPTED.md", ACCEPTED), ("buddie.toml", CONFIG)):
        (r / name).write_text(text)
    when = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=hours_ago)
    env = dict(os.environ, GIT_COMMITTER_DATE=when.isoformat(), GIT_AUTHOR_DATE=when.isoformat())
    git = lambda *a: subprocess.run(["git", "-C", str(r), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                    check=True, capture_output=True, text=True, env=env).stdout.strip()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    git("add", ".")
    git("commit", "-qm", "Merge pull request #1 from tsyyan/claude/x")
    sha = git("rev-parse", "--short", "HEAD")
    (r / "PLAN.md").write_text("plan\n")  # a later commit that does not touch the queue
    subprocess.run(["git", "-C", str(r), "-c", "user.name=t", "-c", "user.email=t@t", "add", "."], check=True)
    subprocess.run(["git", "-C", str(r), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "plan"],
                   check=True)
    for k, v in {"BUDDIE_FETCH": "0", "BUDDIE_GITHUB": "0", "VERBATIM_STORE": str(tmp_path / "store"),
                 "BUDDIE_LOG": str(tmp_path / "hook.jsonl"), "BUDDIE_STATE": str(tmp_path / "pending"),
                 "BUDDIE_REPOS": str(r), "BUDDIE_FREE": "0"}.items():
        monkeypatch.setenv(k, v)
    for name in ("BUDDIE_SESSIONS", "BUDDIE_SUMMARY", "BUDDIE_LAUNCH", "BUDDIE_PROMISES", "BUDDIE_LESSONS"):
        monkeypatch.delenv(name, raising=False)
    return r, sha, _iso(when)


def _launch(n, sha):
    err = io.StringIO()
    code = hook.run({"cwd": ".", "hook_event_name": "PreToolUse", "session_id": "coord", "tool_name": "Agent",
                     "tool_input": {"description": f"№{n}", "prompt": f"Выполни строку №{n} `⚓ NEXT.md@{sha}`."}}, err)
    return code, err.getvalue()


def test_appeared_is_the_commit_that_brought_the_row(tmp_path, monkeypatch):
    r, sha, when = _repo(tmp_path, monkeypatch, 2)
    m = man.Mandate(man.load_config(r), sha)
    assert m.appeared(2) == when and man.Mandate(man.load_config(r)).appeared(2) == when
    assert m.appeared(99) is None
    due = _iso(datetime.fromisoformat(when.replace("Z", "+00:00")) + timedelta(hours=24))
    before = _iso(datetime.fromisoformat(due.replace("Z", "+00:00")) - timedelta(minutes=1))
    assert m.verdict(2)["verdict"] == "ask"  # no moment: never due, as chain.py verdict without --now
    assert m.verdict_now(2, before)["reasons"] == ["waits for a condition: через сутки"]
    assert m.verdict_now(2, due) == {"n": 2, "verdict": "auto", "reasons": []}


def test_uncommitted_text_has_no_start(tmp_path, monkeypatch):
    r, _, _ = _repo(tmp_path, monkeypatch, 30)
    (r / "NEXT.md").write_text(QUEUE.replace("Замерить через", "Замерить снова через"))
    m = man.Mandate(man.load_config(r))
    assert m.appeared(2) is None and m.verdict_now(2)["verdict"] == "ask"


@pytest.mark.parametrize("hours_ago, code", [(2, 2), (30, 0)])
def test_launch_gate_lets_a_due_row_through(tmp_path, monkeypatch, hours_ago, code):
    r, sha, _ = _repo(tmp_path, monkeypatch, hours_ago)
    got, err = _launch(2, sha)
    assert got == code
    if code:
        assert "waits for a condition: через сутки" in err
    else:
        assert err == ""


@pytest.mark.parametrize("hours_ago, due", [(2, False), (30, True)])
def test_summary_launches_a_due_row(tmp_path, monkeypatch, hours_ago, due):
    r, _, _ = _repo(tmp_path, monkeypatch, hours_ago)
    out = summary.summarize("s1", [r])
    by = {s["key"]: s for s in out["next"]}
    assert by["№2"]["verdict"] == ("auto" if due else "ask")
    # a status «ждёт условия» whose only condition came due is lifted, as in chain.py debt
    assert by["№3"]["waiting"] is (not due) and by["№3"]["verdict"] == ("auto" if due else "ask")
    assert out["debt"]["launch"] == (["№2", "№3"] if due else [])
    assert out["debt"]["waiting"] == ([] if due else ["№3"])
