"""buddie 0.7, the launch gate and the journal of promises (audit/18 §5 п. 2, NEXT №69), on recorded events.

The lost autostart of №42 (audit/12_sources/coordination_losses.json): lab#53 got its automerge comment at
2026-10-02T22:58:16Z, the coordinator's summary at 23:21 said «Вердикт auto, запущу сам после влития lab#53», and no
thread was started. The three-thread summary (audit/12): №39, №43 and the presentation finished 23:04–23:46 and the
coordinator was recycled at 23:46:37 without a summary; that promise's words are not recorded, so its text below is
built from the timeline.
"""
from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest

from buddie import hook, promises, summary

QUEUE = """| № | Шаг | Тема | Основание | Статус |
|---|---|---|---|---|
| 1 | Сделать этап | t | PLAN этап 1 | выполнено `⚓ NEXT.md@0000000` |
| 2 | Продолжить этап | t | PLAN этап 1 ← №1 | предложено |
| 3 | Новое направление | t | — | предложено |
| 42 | Продолжить этап дальше | t | PLAN этап 1 ← №1 | предложено |
"""
ACCEPTED = "| Область | Слова |\n|---|---|\n| `PLAN этап 1` | «принимаем план» 2026-10-01 |\n"
CONFIG = """[mandate]
queue = "NEXT.md"
accepted = "ACCEPTED.md"
[[mandate.refs]]
pattern = 'PLAN этап (?P<stage>\\d+)'
doc = "PLAN.md"
level = "stage"

[launch]
tools = 'Agent|mcp__hearthbot__start_thread_session'
"""
PROMISE_42 = ("Сводка 23:21.\n- №42 продолжить этап дальше: вердикт auto, запущу сам после влития lab#53.\n\n"
              "Следующий шаг: №42 `⚓ NEXT.md@{sha}`")
PROMISE_19 = ("Правило автозапуска добавил в инструкции проекта. Шаг №19 из NEXT.md запущу сам, как только сольётся "
              "lab#27: вердикт `auto` для него начнёт действовать только после этого слияния.")


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "repo"
    r.mkdir()
    (r / "NEXT.md").write_text(QUEUE)
    (r / "ACCEPTED.md").write_text(ACCEPTED)
    (r / "buddie.toml").write_text(CONFIG)
    _git(tmp_path, "init", "-q", str(r))
    _git(r, "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
    _git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "queue")
    monkeypatch.setenv("BUDDIE_FETCH", "0")
    monkeypatch.setenv("BUDDIE_GITHUB", "0")
    monkeypatch.setenv("VERBATIM_STORE", str(tmp_path / "store"))
    monkeypatch.setenv("BUDDIE_LOG", str(tmp_path / "hook.jsonl"))
    monkeypatch.setenv("BUDDIE_STATE", str(tmp_path / "pending"))
    monkeypatch.setenv("BUDDIE_REPOS", str(r))
    for name in ("BUDDIE_SESSIONS", "BUDDIE_SUMMARY", "BUDDIE_LAUNCH", "BUDDIE_PROMISES", "BUDDIE_LESSONS", "BUDDIE_FREE"):
        monkeypatch.delenv(name, raising=False)
    return r


def _merge(repo, n):
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m",
         f"Merge pull request #{n} from tsyyan/claude/x")
    return _git(repo, "rev-parse", "--short", "HEAD")


def _transcript(tmp, text, name="t.jsonl"):
    p = Path(tmp) / name
    p.write_text(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}) + "\n")
    return str(p)


def _run(event):
    err = io.StringIO()
    return hook.run(dict({"cwd": "."}, **event), err), err.getvalue()


def _stop(session, text, tmp, **kw):
    return _run(dict({"hook_event_name": "Stop", "session_id": session, "stop_hook_active": False,
                      "transcript_path": _transcript(tmp, text, f"{session}.jsonl")}, **kw))


def _launch(session, tool_input, tool="Agent"):
    return _run({"hook_event_name": "PreToolUse", "session_id": session, "tool_name": tool, "tool_input": tool_input})


def _journal(tmp, key):
    return [e for e in map(json.loads, (Path(tmp) / "hook.jsonl").read_text().splitlines()) if key in e]


def test_extract_recorded_texts():
    p = promises.extract(PROMISE_19)
    assert [(x["kind"], x["row"], x["cond"]) for x in p] == [("launch", 19, {"kind": "pr", "repo": "lab", "n": 27})]
    p = promises.extract(PROMISE_42.format(sha="0000000"))
    assert [(x["row"], x["cond"]["n"]) for x in p] == [(42, 53)]
    assert promises.extract("Запущу №5 после №4.")[0]["cond"] == {"kind": "row", "n": 4}
    assert promises.extract("Запущу №5.")[0]["cond"] == {"kind": "now"}
    # dogfood/effects/texts-2026-10-03.json: an offer with no row is not a promise
    assert promises.extract("Если нужно, напиши здесь «да», и я запущу синхронизацию.") == []
    assert promises.extract("Он писал: «запущу №7 после влития lab#9».\n> запущу №8") == []
    assert promises.extract("Сводка будет, когда закончатся три треда.")[0]["kind"] == "summary"
    assert promises.extract("Пришлю общую сводку после тредов.")[0]["kind"] == "summary"
    assert promises.extract("Запустил №5, сводку прислал.") == []


def test_lost_autostart_42_is_returned_at_stop(repo, tmp_path):
    sha = _merge(repo, 53)  # lab#53 is merged before the promise (22:58 automerge, 23:21 promise)
    code, err = _stop("coord", PROMISE_42.format(sha=sha), tmp_path)
    assert code == 2 and "запуск №42" in err and "lab#53" in err and "условие выполнено" in err
    [line] = _journal(tmp_path, "promise")
    assert line["promise"]["row"] == 42 and "exit" not in line  # not a gate check: lessons skip it
    assert _stop("coord", "Ок.", tmp_path)[0] == 0  # once per promise
    code, out = _launch("coord", {"description": "№42 продолжить этап дальше",
                                  "prompt": f"Выполни строку №42 очереди `⚓ NEXT.md@{sha}`."})
    assert (code, out) == (0, "")
    assert promises.open_promises([repo], None) == []  # kept by the launch


def test_promise_waits_for_its_merge(repo, tmp_path):
    sha = _git(repo, "rev-parse", "--short", "HEAD")
    assert _stop("coord", PROMISE_42.format(sha=sha), tmp_path)[0] == 0  # lab#53 not merged yet
    _merge(repo, 53)
    code, err = _stop("coord", "Жду.", tmp_path)
    assert code == 2 and "№42" in err


def test_recycled_session_promise_printed_at_session_start(repo, tmp_path, capsys):
    _stop("coord1", PROMISE_42.format(sha=_git(repo, "rev-parse", "--short", "HEAD")), tmp_path)
    _stop("coord1", "№39, №43 и презентация идут. Сводка будет, когда закончатся все три треда.", tmp_path)
    assert _run({"hook_event_name": "SessionStart", "session_id": "coord2"}) == (0, "")
    out = capsys.readouterr().out
    assert "открытые обещания (2)" in out and "сессия coord1" in out
    assert "сводка, когда сабагентов не останется" in out and "запуск №42, после влития lab#53" in out
    assert len(out.strip().splitlines()) <= 10


def test_summary_promise_due_when_threads_finish(repo, tmp_path):
    ev = {"hook_event_name": "SubagentStart", "session_id": "coord", "agent_id": "a1", "agent_type": "general"}
    _run(ev)
    assert _stop("coord", "Сводка будет, когда закончатся все три треда.", tmp_path)[0] == 0  # a1 is live
    _run(dict(ev, hook_event_name="SubagentStop", last_assistant_message="Готово.", agent_transcript_path=""))
    with summary.editing("coord") as s:  # this test is about the promise, not the summary demand of 0.6
        s["demanded"].append("a1")
    code, err = _stop("coord", "Жду.", tmp_path)
    assert code == 2 and "сводка" in err
    _stop("coord", "Сводка: №39 влит, №43 влит, презентация ждёт.", tmp_path)
    assert promises.open_promises([repo], None) == []


def test_promise_dropped_by_a_buddie_line(repo, tmp_path):
    _stop("coord", "Запущу №3.", tmp_path)
    assert promises.open_promises([repo], None)
    _stop("coord", "buddie: не запускаю №3 — вердикт ask, нужен выбор человека.", tmp_path)
    assert promises.open_promises([repo], None) == []


def test_launch_gate(repo, tmp_path):
    sha = _git(repo, "rev-parse", "--short", "HEAD")
    code, err = _launch("s", {"description": "№2 продолжить этап", "prompt": "Сделай строку №2."})
    assert code == 2 and "без основания" in err and f"`⚓ NEXT.md@{sha}`" in err  # the ready anchor
    assert _launch("s", {"description": "№2", "prompt": f"⚓ `NEXT.md@{sha}`"})[0] == 0
    code, err = _launch("s", {"description": "№3 новое направление", "prompt": f"`⚓ NEXT.md@{sha}`"})
    assert code == 2 and "verdict ask" in err and "Нужен выбор человека" in err
    assert _launch("s", {"description": "№2", "prompt": "`⚓ NEXT.md@deadbee`"})[0] == 2
    # a parent is not the launched row; a launch with no row passes and is logged
    assert promises.launched_row({"prompt": "Исправь тест ← №2, это №3"}) == 3
    assert _launch("s", {"description": "поиск файлов", "prompt": "Найди все *.py"}) == (0, "")
    outcomes = [e["launch"]["outcome"] for e in _journal(tmp_path, "launch")]
    assert outcomes == ["blocked", "passed", "blocked", "blocked", "unqueued"]
    # a thread launch is gated the same way; a tool not in [launch] is not
    assert _launch("s", {"title": "№3", "message": "go"}, tool="mcp__hearthbot__start_thread_session")[0] == 2
    assert _launch("s", {"title": "№3", "message": "go"}, tool="Bash")[0] == 0


def test_launch_by_the_persons_choice(repo, tmp_path):
    hook.log({"at": "2026-10-04T10:00:00Z", "session": "s", "choice": {
        "id": "abc123", "options": [{"key": "№3", "label": "№3 Новое направление"}], "chosen": ["№3"], "other": []}})
    assert _launch("s", {"description": "№3", "prompt": "`⚓ choice:abc123=№3`"}) == (0, "")
    code, err = _launch("s", {"description": "№2", "prompt": "`⚓ choice:abc123=№3`"})
    assert code == 2 and "another step" in err


def test_gate_off_without_launch_config(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("BUDDIE_LAUNCH", "0")
    assert _launch("s", {"description": "№3", "prompt": "go"})[0] == 0
    monkeypatch.setenv("BUDDIE_PROMISES", "0")
    assert _stop("s", "Запущу №3.", tmp_path)[0] == 0
    assert not (tmp_path / "hook.jsonl").exists() or not _journal(tmp_path, "promise")


# Recorded in the live run of №77 (cloud session 2026-10-04): the PreToolUse tool_input of each launch tool as Claude
# Code sent it. Agent: description, prompt, run_in_background, subagent_type; create_session here had only a title.
LIVE_AGENT = {"description": "№2 live gate probe", "subagent_type": "general-purpose", "run_in_background": False,
              "prompt": "Выполни строку №2 очереди NEXT.md.\n(Это проба шлюза: ничего не делай, просто ответь словом «ok».)"}
LIVE_CREATE_SESSION = {"title": "№2 проба шлюза buddie"}


def test_live_launch_events(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("BUDDIE_LAUNCH", "Agent|mcp__claude-code-remote__create_session")
    assert _launch("s", LIVE_AGENT)[0] == 2
    assert _launch("s", LIVE_CREATE_SESSION, tool="mcp__claude-code-remote__create_session")[0] == 2
    assert _launch("s", {"description": "Unqueued launch probe", "subagent_type": "Explore", "run_in_background": False,
                         "prompt": "Найди файл, где определена функция launched_row."}) == (0, "")
    lines = [e for e in _journal(tmp_path, "launch")]
    assert [e["fields"] for e in lines] == [["description", "prompt", "run_in_background", "subagent_type"], ["title"],
                                            ["description", "prompt", "run_in_background", "subagent_type"]]
    assert [(e["launch"]["row"], e["launch"]["outcome"]) for e in lines] == [(2, "blocked"), (2, "blocked"),
                                                                             (None, "unqueued")]


def test_ready_anchor_names_main_not_the_branch(repo, tmp_path):
    main = _git(repo, "rev-parse", "--short", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    (repo / "NEXT.md").write_text(QUEUE.replace("дальше | t | PLAN этап 1 ← №1 | предложено", "дальше | t | PLAN этап 1 ← №1 | запущено"))
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "№42 запущено")  # the working branch
    code, err = _launch("s", {"description": "№42 продолжить этап дальше", "prompt": "Сделай строку №42."})
    assert code == 2 and f"`⚓ NEXT.md@{main}`" in err and "not «предложено»" not in err


# NEXT №85: a launch with a basis is returned when its row is taken. The comment's shape is the one automerge posted on
# lab#104 (merged as 238f148, `chain.py merged`): first words, then a fenced json block with `free` per `auto` verdict.
def _comment(sha, n, free, reasons=()):
    record = {"merge": sha, "anchor": f"NEXT.md@{sha[:7]}", "verdicts": [
        {"n": n, "verdict": "auto", "reasons": [], "free": free, "free_reasons": list(reasons), "prs_checked": True}]}
    return {"body": f"automerge: слито как {sha}. Вердикты автозапуска на коммите влития.\n\n```json\n"
                    f"{json.dumps(record, ensure_ascii=False)}\n```\n"}


@pytest.fixture
def merged_repo(repo, tmp_path, monkeypatch):
    from buddie import effects
    (repo / "buddie.toml").write_text(CONFIG + 'comment = "automerge: слито как"\n')
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "config")
    _git(repo, "remote", "add", "origin", "https://github.com/tsyyan/lab.git")
    short = _merge(repo, 104)
    sha = _git(repo, "rev-parse", short)
    comments = {}
    monkeypatch.setattr(effects, "github_get", lambda path: comments.get(path))
    monkeypatch.setenv("BUDDIE_GITHUB", "1")
    return short, sha, comments


def test_launch_returned_when_the_automerge_comment_says_taken(merged_repo, tmp_path):
    short, sha, comments = merged_repo
    path = "/repos/tsyyan/lab/issues/104/comments?per_page=100"
    comments[path] = [{"body": "ci зелёный"}, _comment(sha, 2, False, ["ветка claude/project-thread-x отметила строку"])]
    code, err = _launch("s", {"description": "№2 продолжить этап", "prompt": f"`⚓ NEXT.md@{short}`"})
    assert code == 2 and "№2 уже взята (automerge tsyyan/lab#104)" in err and "claude/project-thread-x" in err
    comments[path] = [_comment(sha, 2, True)]
    assert _launch("s", {"description": "№2", "prompt": f"`⚓ NEXT.md@{short}`"}) == (0, "")
    comments[path] = [_comment("f" * 40, 2, False)]  # a comment about another merge does not count
    assert _launch("s", {"description": "№2", "prompt": f"`⚓ NEXT.md@{short}`"}) == (0, "")
    lines = [e["launch"] for e in _journal(tmp_path, "launch")]
    assert [(e["outcome"], e.get("free")) for e in lines] == [("taken", False), ("passed", None), ("passed", None)]


def test_free_command_after_the_comment_and_without_it(merged_repo, tmp_path, monkeypatch):
    short, sha, comments = merged_repo
    comments["/repos/tsyyan/lab/issues/104/comments?per_page=100"] = [_comment(sha, 2, True)]
    taken = tmp_path / "taken.py"
    taken.write_text("import json, sys\nprint(json.dumps({'n': int(sys.argv[1]), 'free': False, "
                     "'reasons': ['ветка claude/y отметила строку']}))\nsys.exit(1)\n")
    monkeypatch.setenv("BUDDIE_FREE", f"python3 {taken} {{n}}")
    # the comment's free: true is as of the merge; a branch that took the row since is found by the command
    code, err = _launch("s", {"description": "№2", "prompt": f"`⚓ NEXT.md@{short}`"})
    assert code == 2 and "(free)" in err and "claude/y" in err
    monkeypatch.setenv("BUDDIE_GITHUB", "0")  # no comment: the command alone
    assert _launch("s", {"description": "№2", "prompt": f"`⚓ NEXT.md@{short}`"})[0] == 2
    # a person's choice is checked by the command too
    hook.log({"at": "2026-10-04T10:00:00Z", "session": "s", "choice": {
        "id": "abc123", "options": [{"key": "№3", "label": "№3"}], "chosen": ["№3"], "other": []}})
    assert _launch("s", {"description": "№3", "prompt": "`⚓ choice:abc123=№3`"})[0] == 2
    monkeypatch.setenv("BUDDIE_FREE", "python3 -c 'print(\"not json\")'")  # no answer: unknown, passes
    assert _launch("s", {"description": "№2", "prompt": f"`⚓ NEXT.md@{short}`"}) == (0, "")
    # a taken launch keeps a launch promise: the row runs, only not from here
    _stop("coord", "Запущу №2.", tmp_path)
    monkeypatch.setenv("BUDDIE_FREE", f"python3 {taken} {{n}}")
    assert _launch("coord", {"description": "№2", "prompt": f"`⚓ NEXT.md@{short}`"})[0] == 2
    assert promises.open_promises([tmp_path / "repo"], None) == []
