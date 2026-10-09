"""Effect anchors (pr:, ci:, run:) offline: GitHub is a dict of canned responses, the transcript a temp jsonl."""
from __future__ import annotations

import io
import json

from buddie import effects, hook
from buddie.verify import verify

MERGE, HEAD = "9653a7cd6f02818c34cd3902da879711b03a5919", "dbf390f479dee4806b67d6d62d90aeec7fc12843"
API = {
    "/repos/o/r/pulls/54": {"state": "closed", "merged": True, "merge_commit_sha": MERGE, "head": {"sha": HEAD}},
    "/repos/o/r/pulls/55": {"state": "open", "merged": False, "draft": True, "head": {"sha": HEAD}},
    f"/repos/o/r/commits/{HEAD[:7]}/check-runs?per_page=100&page=1":
        {"check_runs": [{"name": "check", "status": "completed", "conclusion": "success"},
                        {"name": "lint", "status": "completed", "conclusion": "skipped"}]},
    f"/repos/o/r/commits/{HEAD[:7]}/status": {"statuses": []},
    "/repos/o/r/commits/abcdef0/check-runs?per_page=100&page=1":
        {"check_runs": [{"name": "check", "status": "completed", "conclusion": "failure"}]},
    "/repos/o/r/commits/abcdef0/status": {"statuses": [{"context": "deploy", "state": "pending"}]},
}


def fake_github(path):
    return API.get(path)


def offline(path):
    raise effects.GitHubUnavailable("GitHub 503")


def judge(text, **kw):
    return [a["status"] for a in verify(text, quotes=False, mandate=False, **kw)["predicate"]["anchors"]]


def test_pr_states():
    text = (f"`⚓ pr:o/r#54=merged@{MERGE[:7]}` `⚓ pr:o/r#54=merged@{HEAD[:7]}` `⚓ pr:o/r#54=open` "
            f"`⚓ pr:o/r#54=closed` `⚓ pr:o/r#55=draft@{HEAD[:7]}` `⚓ pr:o/r#55=open` `⚓ pr:o/r#55=merged` "
            "`⚓ pr:o/r#99=merged`")
    assert judge(text, github=fake_github) == ["HOLDS", "BROKEN", "BROKEN", "HOLDS", "HOLDS", "HOLDS", "BROKEN",
                                               "UNCHECKABLE"]


def test_ci_on_a_commit():
    text = (f"`⚓ ci:o/r@{HEAD[:7]}=success` `⚓ ci:o/r@{HEAD[:7]}/check=success` `⚓ ci:o/r@{HEAD[:7]}/nope=success` "
            "`⚓ ci:o/r@abcdef0=success` `⚓ ci:o/r@abcdef0=pending` `⚓ ci:o/r@abcdef0/check=failure`")
    got = verify(text, quotes=False, mandate=False, github=fake_github)["predicate"]
    assert [a["status"] for a in got["anchors"]] == ["HOLDS", "HOLDS", "UNCHECKABLE", "BROKEN", "HOLDS", "HOLDS"]
    assert "check=failure" in got["anchors"][3]["why"]
    assert got["notes"] == [effects.NOTE]  # a green CI is reported as what it is, not as correct code


def test_github_unreachable_or_off_is_a_gap_not_a_failure():
    text = "`⚓ pr:o/r#54=merged` `⚓ ci:o/r@abcdef0=success`"
    assert judge(text, github=offline) == ["UNCHECKABLE"] * 2
    pred = verify(text, quotes=False, mandate=False)["predicate"]
    assert pred["outcome"] == "GAPS" and "offline" in pred["gaps"][0]


def _transcript(tmp_path, calls, sub=()):
    def rows(items, tag=""):
        out = []
        for i, (name, args, result, error) in enumerate(items):
            uid = f"toolu_{tag}{name}{i}"
            out.append({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": uid, "name": name, "input": args}]}})
            out.append({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": uid, "content": result, "is_error": error}]}})
        return "\n".join(json.dumps(r) for r in out)
    path = tmp_path / "session.jsonl"
    path.write_text(rows(calls))
    if sub:
        (tmp_path / "session" / "subagents").mkdir(parents=True)
        (tmp_path / "session" / "subagents" / "agent-1.jsonl").write_text(rows(sub, "sub"))
    return str(path)


def test_run_against_the_transcript(tmp_path):
    t = _transcript(tmp_path, [
        ("Bash", {"command": "python3 -m pytest -q tests"}, "........\n41 passed in 3.2s", False),
        ("Bash", {"command": "echo '12 passed'"}, "12 passed", False),
        ("Bash", {"command": "make broken"}, "Error 2", True),
        ("mcp__hearthbot__reply", {"text": "ran ruff check, 0 errors"}, "sent", False),
    ], sub=[("Bash", {"command": "ruff check ."}, [{"type": "text", "text": "All checks passed!"}], False)])
    text = ("`⚓ run:pytest -q => 41 passed` `⚓ run:pytest -q => 40 passed` `⚓ run:echo => 12 passed` "
            "`⚓ run:make broken` `⚓ run:ruff check => All checks passed!` `⚓ run:toolu_Bash0 => 41 passed` "
            "`⚓ run:cargo test` `⚓ run:ruff check, 0 errors`")
    got = verify(text, quotes=False, mandate=False, transcript=t)["predicate"]["anchors"]
    assert [a["status"] for a in got] == ["HOLDS", "BROKEN", "BROKEN", "BROKEN", "HOLDS", "HOLDS", "BROKEN", "BROKEN"]
    assert got[0]["tool_use_id"] == "toolu_Bash0"
    assert "written in the command" in got[2]["why"]
    assert "41 passed" in got[1]["why"]  # the miss shows what the output actually ends with
    assert judge("`⚓ run:pytest => 41 passed`") == ["UNCHECKABLE"]  # no transcript: nothing to judge against


def test_report_read_back_is_not_a_run(tmp_path):
    t = _transcript(tmp_path, [("Bash", {"command": "grep -n pytest report.md"},
                                "3: tests pass `⚓ run:pytest => 41 passed`", False)])
    assert judge("`⚓ run:pytest => 41 passed`", transcript=t) == ["BROKEN"]


def test_hook_blocks_a_false_work_claim(tmp_path, monkeypatch):
    monkeypatch.setenv("BUDDIE_LOG", "0")
    monkeypatch.setenv("BUDDIE_GITHUB", "0")
    t = _transcript(tmp_path, [("Bash", {"command": "pytest -q"}, "1 failed, 40 passed", True)])
    event = {"hook_event_name": "PreToolUse", "tool_name": "mcp__hearthbot__reply", "cwd": str(tmp_path),
             "transcript_path": t, "tool_input": {"text": "Тесты прошли `⚓ run:pytest -q => 41 passed`.\n\n"
                                                           "Следующий шаг: слить."}}
    err = io.StringIO()
    assert hook.run(event, err) == 2 and "1 failed, 40 passed" in err.getvalue()
    event["tool_input"]["text"] = "Тесты: `⚓ run:pytest -q => 40 passed`, один упал.\n\nСледующий шаг: починить."
    assert hook.run(event, io.StringIO()) == 0
    event["tool_input"]["text"] = "Слито `⚓ pr:o/r#54=merged`.\n\nСледующий шаг: дальше."  # GitHub off: a gap
    assert hook.run(event, io.StringIO()) == 0


def test_not_an_effect_anchor_is_broken():
    assert judge("`⚓ pr:o/r#54=landed`") == ["BROKEN"]


def test_prose_work_claims_are_counted_and_block_a_final_answer(tmp_path, monkeypatch):
    text = ("PR слит, CI зелёный.\nСлито `⚓ pr:o/r#54=merged`.\nPR сольются сами, надо прогнать.\n"
            "тесты прошли, все\nстатус `merged` в коде\n\nСледующий шаг: дальше `⚓ pr:o/r#54=merged`.")
    pred = verify(text, quotes=False, mandate=False, github=fake_github)["predicate"]
    assert pred["summary"]["work"] == {"anchored": 2, "broken": 0, "prose": 2}
    assert pred["prose_work"][0].startswith("line 1:") and "2 work claims in prose" in pred["line"]
    monkeypatch.setenv("BUDDIE_LOG", "0")
    monkeypatch.setenv("BUDDIE_GITHUB", "0")
    event = {"hook_event_name": "PreToolUse", "tool_name": "mcp__hearthbot__reply", "cwd": str(tmp_path),
             "session_id": "s1", "tool_input": {"text": text}}
    err = io.StringIO()
    assert hook.run(event, err) == 2  # a final answer: work claimed in prose returns it (NEXT №63)
    assert "work claimed in prose, line 1:" in err.getvalue() and "line 4:" in err.getvalue()
    event["tool_input"]["text"] = text + "\nbuddie: CI и тесты не проверял"  # a disclosure does not cover it
    err = io.StringIO()
    assert hook.run(event, err) == 2 and "does not cover" in err.getvalue()
    event["tool_input"]["text"] = text.replace("\n\nСледующий шаг: дальше `⚓ pr:o/r#54=merged`.", "")
    assert hook.run(event, io.StringIO()) == 0  # not a final answer: counted only
    event["tool_input"]["text"] = "PR слит `⚓ pr:o/r#54=merged`, ещё не влит lab#55.\n\nСледующий шаг: дальше."
    assert hook.run(event, io.StringIO()) == 0
    logged = [json.loads(x) for x in (tmp_path / "shared-log" / "s1.jsonl").read_text().splitlines()]
    assert [x["work"]["prose"] for x in logged] == [2, 2, 2, 0] and logged[0]["session"] == "s1"
    assert logged[0]["reasons"] == {"prose": 2} and logged[1]["gate"]["way"] == "returned"

    import importlib.util
    from pathlib import Path
    path = Path(__file__).parents[1] / "dogfood" / "effects" / "measure.py"
    if not path.is_file():  # dogfood/ stays in lab, the public repo has no measure.py
        return
    spec = importlib.util.spec_from_file_location("measure", path)
    measure = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(measure)
    blocked = dict(logged[3], exit=2, at="0", sha256="x", work={"anchored": 1, "broken": 1, "prose": 0})
    blocked.pop("gate", None)
    result = measure.measure([blocked] + logged + [logged[3]])
    assert result["answers"] == 2 and result["sessions"] == 1
    assert result["total"] == {"anchored": 2, "broken": 0, "prose": 2, "blocked_before": 3, "caught_broken": 1,
                               "returned_prose": 4, "quotes": 0, "quotes_found": 0, "quotes_not_found": 0}
    assert result["rows"][0]["caught_broken"] == 1 and result["rows"][0]["tool"] == "mcp__hearthbot__reply"
    assert measure.measure(logged, quotes=True)["answers"] == 0


def test_descriptions_and_plans_are_not_work_claims():
    # the three false hits of NEXT №45 (NEXT №52): a kind of step after «которые», a plan after «проверю, что»
    for line in ("В `launch` идут шаги `auto`, которые уже влиты, но ни одна ветка не пометила их «запущено».",
                 "`chain.py debt` будет показывать шаги с `auto`, которые слиты, но не запущены, и шаги с `ask`",
                 "Перед тем как ты его сольёшь, я проверю, что CI зелёный и в diff нет внутренних данных.",
                 "Убедимся, что тесты прошли.", "Нужно проверить, что PR слит.", "Дождусь, когда CI зелёный."):
        assert not effects.claims_work(line), line
    for line in ("PR слит.", "CI зелёный.", "Тесты прошли.", "lab#59 слит автомержем после зелёного CI",
                 "Я проверил, что CI зелёный.", "lab#64, который уже влит, чинит экспорт",
                 "PR, которые я открыл, слиты.", "41 passed", "прогнал pytest", "CI прошёл, PR влит"):
        assert effects.claims_work(line), line


def test_measure_recounts_prose_from_known_texts(tmp_path):
    import hashlib
    import importlib.util
    from pathlib import Path
    path = Path(__file__).parents[1] / "dogfood" / "effects" / "measure.py"
    if not path.is_file():  # dogfood/ stays in lab
        return
    spec = importlib.util.spec_from_file_location("measure", path)
    measure = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(measure)
    whole = "Шаги, которые слиты, но не запущены.\nPR слит.\n\nСледующий шаг: дальше."
    sha = hashlib.sha256(whole.encode()).hexdigest()
    texts = tmp_path / "texts.json"
    texts.write_text(json.dumps({"answers": [
        {"sha256": sha, "whole": True, "text": whole},
        {"sha256": "b" * 64, "whole": False, "counted": 1, "text": "Я проверю, что CI зелёный."}]}))
    row = {"at": "1", "session": "s", "exit": 0, "outcome": "PASS", "final": True}
    rows = [dict(row, sha256=sha, work={"anchored": 0, "broken": 0, "prose": 2}),
            dict(row, sha256="b" * 64, work={"anchored": 1, "broken": 0, "prose": 3}),
            dict(row, sha256="c" * 64, work={"anchored": 0, "broken": 0, "prose": 1})]
    got = [r["work"]["prose"] for r in measure.recount(rows, texts)]
    assert got == [1, 2, 1] and measure.measure(measure.recount(rows, texts))["total"]["prose"] == 4


def _answer_54(prefix: str):
    from pathlib import Path
    path = Path(__file__).parents[1] / "dogfood" / "effects" / "texts-2026-10-03-54.json"
    if not path.is_file():  # dogfood/ stays in lab
        return None
    answers = json.loads(path.read_text(encoding="utf-8"))["answers"]
    return next(a["text"] for a in answers if a["sha256"].startswith(prefix))


def test_disclosure_does_not_cover_a_broken_effect_anchor(tmp_path, monkeypatch):
    """NEXT №62: №40 13:55:00 sent `pr:tsyyan/lab#74=open` for a merged PR, a `buddie:` line let it through."""
    import pytest
    text = _answer_54("0420a9501547")
    if text is None:
        pytest.skip("dogfood/ is not exported")
    merged = {"/repos/tsyyan/lab/pulls/74": {"state": "closed", "merged": True, "merge_commit_sha": MERGE,
                                             "head": {"sha": "3735f409185b" + "0" * 28}}}
    monkeypatch.setattr(effects, "github_get", lambda path: merged.get(path))
    monkeypatch.setenv("BUDDIE_LOG", "0")
    monkeypatch.setenv("BUDDIE_FETCH", "0")
    event = {"hook_event_name": "PreToolUse", "tool_name": "mcp__hearthbot__reply", "cwd": str(tmp_path),
             "tool_input": {"text": text}}
    assert "\nbuddie:" in text
    err = io.StringIO()
    assert hook.run(event, err) == 2
    assert "PR is merged" in err.getvalue() and "does not cover a broken" in err.getvalue()
    without = "\n".join(line for line in text.splitlines() if not line.startswith("buddie:"))
    assert hook.run(dict(event, tool_input={"text": without}), io.StringIO()) == 2
    fixed = text.replace("pr:tsyyan/lab#74=open@3735f409185b", "pr:tsyyan/lab#74=merged")
    err = io.StringIO()
    hook.run(dict(event, tool_input={"text": fixed}), err)
    assert "pr:tsyyan/lab#74" not in err.getvalue()


def test_sign_before_the_backticks_is_no_way_around_the_gate(tmp_path, monkeypatch):
    """NEXT №67: the same broken `pr:` anchor written as ⚓ `pr:…` was not parsed, so the answer passed unchecked."""
    import pytest
    text = _answer_54("0420a9501547")
    if text is None:
        pytest.skip("dogfood/ is not exported")
    text = text.replace("`⚓ ", "⚓ `")
    assert "⚓ `pr:tsyyan/lab#74=open@3735f409185b`" in text
    merged = {"/repos/tsyyan/lab/pulls/74": {"state": "closed", "merged": True, "merge_commit_sha": MERGE,
                                             "head": {"sha": "3735f409185b" + "0" * 28}}}
    monkeypatch.setattr(effects, "github_get", lambda path: merged.get(path))
    monkeypatch.setenv("BUDDIE_LOG", "0")
    monkeypatch.setenv("BUDDIE_FETCH", "0")
    event = {"hook_event_name": "PreToolUse", "tool_name": "mcp__hearthbot__reply", "cwd": str(tmp_path),
             "tool_input": {"text": text}}
    err = io.StringIO()
    assert hook.run(event, err) == 2
    assert "PR is merged" in err.getvalue() and "does not cover a broken" in err.getvalue()


def test_disclosure_still_covers_a_quote_miss_next_to_an_effect_anchor(tmp_path, monkeypatch):
    monkeypatch.setattr(effects, "github_get", fake_github)
    monkeypatch.setenv("BUDDIE_LOG", "0")
    event = {"hook_event_name": "PreToolUse", "tool_name": "mcp__hearthbot__reply", "cwd": str(tmp_path),
             "tool_input": {"text": "Слито `⚓ pr:o/r#54=merged`. Итог: 3 из 4.\n"
                                    "buddie: 3 из 4 посчитано вручную\n\nСледующий шаг: дальше."}}
    assert hook.run(event, io.StringIO()) == 0
    event["tool_input"]["text"] = event["tool_input"]["text"].replace("#54=merged", "#55=merged")
    assert hook.run(event, io.StringIO()) == 2


def test_prose_line_of_audit15_returns_the_final_answer(tmp_path, monkeypatch):
    """NEXT №63: «в main влиты №40, №58, audit/14 и №55» (16:03:10, `0c9d12c6d34f`, EFFECTS.md №54) had no pr:
    anchor and left; now it is returned, and a `buddie:` line does not let it through."""
    import pytest
    text = _answer_54("0c9d12c6d34f")
    if text is None:
        pytest.skip("dogfood/ is not exported")
    monkeypatch.setenv("BUDDIE_LOG", "0")
    monkeypatch.setenv("BUDDIE_GITHUB", "0")
    monkeypatch.setenv("BUDDIE_FETCH", "0")
    monkeypatch.setenv("BUDDIE_STATE", str(tmp_path / "pending"))
    event = {"hook_event_name": "PreToolUse", "tool_name": "mcp__hearthbot__reply", "cwd": str(tmp_path),
             "session_id": "s63", "tool_input": {"text": text}}
    for t in (text, text + "\nbuddie: влития не проверены"):
        event["tool_input"]["text"] = t
        err = io.StringIO()
        assert hook.run(event, err) == 2
        assert "work claimed in prose, line 17: “С сегодняшних тредов в main влиты №40, №58" in err.getvalue()
    fixed = text.splitlines()
    fixed[16] = fixed[16].replace("в main влиты №40, №58, audit/14 и №55",
                                  "в main №40 `⚓ pr:tsyyan/lab#74=merged`, №58 `⚓ pr:tsyyan/lab#75=merged`")
    event["tool_input"]["text"] = "\n".join(fixed)
    err = io.StringIO()
    hook.run(event, err)
    assert "work claimed in prose" not in err.getvalue()


def test_negated_work_is_not_a_claim():
    from buddie.effects import claims_work
    for line in ("PR ещё не слит, жду CI.", "lab#80 not merged yet", "PR not yet merged"):
        assert not claims_work(line), line
    assert claims_work("PR слит, а lab#81 ещё не слит")
    # a quoted line is cited, not claimed (this thread's reply quoting the line of №54)
    assert not claims_work("правило ловит строку «в main влиты №40, №58…» из замера №54")
    assert claims_work("«Готово»: PR слит")


def test_conditions_and_adjectives_are_not_work_claims():
    """NEXT №128: the two false prose returns of №82 (dogfood/effects/prose-returns-2026-10-08-82.json), a plan
    after «Once» and «the merged code»; the six real ones of №82 stay claims."""
    for line in ("Следующий шаг: wake the lab#134 thread (row 118) so it updates those two anchors to the new hash "
                 "and pushes. Once automerge has merged it, start row 119 again.",
                 "Row №119 is now in the queue and waits for your consent. It checks that the start and stop lines "
                 "actually show up in the journal, in a container that already has the merged code.",
                 "As soon as CI is green, merge it.", "If tests pass, I will merge.", "a merged PR keeps its branch",
                 "После того как PR будет слит, запущу №119.", "Когда lab#5 слит, запусти №6.", "Как только CI зелёный, сливай."):
        assert not effects.claims_work(line), line
    for line in ("От тебя сейчас ничего не нужно. №91 и №94 слиты и в порядке.",
                 "Тред «проверь результаты облачных сессий»: №91 слит (lab#113 @58a2fdc), №94 слит (lab#114 @80be0bf)",
                 "launch (auto, слиты, не запущены): №106", "- The buddie tests pass (172), and so do the repo's tool tests",
                 "Yes, CI is green, and automerge merged lab#134 at 06:15 UTC. Nothing is needed from you.",
                 "The fix merged into main.", "That merged at 06:15.", "After CI went green, automerge merged lab#5.",
                 "lab#59 слит автомержем после зелёного CI"):
        assert effects.claims_work(line), line


def _turn(tmp_path, reply: str, error: bool, after: str) -> str:
    rows = [{"type": "user", "message": {"content": "check the PR"}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1",
                                                           "name": "mcp__hearthbot__reply", "input": {"text": reply}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": error,
                                                      "content": "hook error" if error else "sent"}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": after}]}}]
    path = tmp_path / "turn.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    return str(path)


def test_stop_after_a_final_reply_is_not_checked_for_prose(tmp_path, monkeypatch):
    """NEXT №128: 3 of 8 prose returns of №82 were Stop text after the final reply had already gone out; that text
    reaches no one. A reply the gate returned (an error result), or one in an earlier turn, does not count."""
    monkeypatch.setenv("BUDDIE_LOG", "0")
    monkeypatch.setenv("BUDDIE_GITHUB", "0")
    monkeypatch.setenv("BUDDIE_FETCH", "0")
    monkeypatch.setenv("BUDDIE_STATE", str(tmp_path / "pending"))
    monkeypatch.setenv("BUDDIE_GATES", "prose=block")
    reply = "Done `⚓ pr:o/r#5=merged`.\n\nСледующий шаг: row 119."
    after = "- The buddie tests pass (172).\n\nСледующий шаг: row 119."
    event = {"hook_event_name": "Stop", "cwd": str(tmp_path), "session_id": "s128",
             "transcript_path": _turn(tmp_path, reply, False, after)}
    assert hook.handed_in(event)
    err = io.StringIO()
    hook.run(event, err)
    assert "work claimed in prose" not in err.getvalue()
    event["transcript_path"] = _turn(tmp_path, reply, True, after)
    assert not hook.handed_in(event)
    err = io.StringIO()
    assert hook.run(event, err) == 2 and "work claimed in prose, line 1:" in err.getvalue()
    event["transcript_path"] = _turn(tmp_path, "Working on it.", False, after)  # not a final answer
    assert not hook.handed_in(event)
    path = tmp_path / "turn.jsonl"
    path.write_text(open(_turn(tmp_path, reply, False, after), encoding="utf-8").read().replace(
        '{"type": "assistant", "message": {"content": [{"type": "text"',
        '{"type": "user", "message": {"content": "next"}}\n{"type": "assistant", "message": {"content": [{"type": "text"'))
    event["transcript_path"] = str(path)
    assert not hook.handed_in(event)  # the reply went out in the turn before
