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


def test_prose_work_claims_are_counted_not_blocked(tmp_path, monkeypatch):
    text = ("PR слит, CI зелёный.\nСлито `⚓ pr:o/r#54=merged`.\nPR сольются сами, надо прогнать.\n"
            "тесты прошли, все\nстатус `merged` в коде\n\nСледующий шаг: дальше `⚓ pr:o/r#54=merged`.")
    pred = verify(text, quotes=False, mandate=False, github=fake_github)["predicate"]
    assert pred["summary"]["work"] == {"anchored": 2, "broken": 0, "prose": 2}
    assert pred["prose_work"][0].startswith("line 1:") and "2 work claims in prose" in pred["line"]
    monkeypatch.setenv("BUDDIE_LOG", "0")
    monkeypatch.setenv("BUDDIE_GITHUB", "0")
    event = {"hook_event_name": "PreToolUse", "tool_name": "mcp__hearthbot__reply", "cwd": str(tmp_path),
             "session_id": "s1", "tool_input": {"text": text}}
    assert hook.run(event, io.StringIO()) == 0
    event["tool_input"]["text"] = "PR слит `⚓ pr:o/r#54=merged`.\n\nСледующий шаг: дальше."
    assert hook.run(event, io.StringIO()) == 0
    logged = [json.loads(x) for x in (tmp_path / "shared-log" / "s1.jsonl").read_text().splitlines()]
    assert [x["work"]["prose"] for x in logged] == [2, 0] and logged[0]["session"] == "s1"

    import importlib.util
    from pathlib import Path
    path = Path(__file__).parents[1] / "dogfood" / "effects" / "measure.py"
    if not path.is_file():  # dogfood/ stays in lab, the public repo has no measure.py
        return
    spec = importlib.util.spec_from_file_location("measure", path)
    measure = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(measure)
    blocked = dict(logged[1], exit=2, at="0", sha256="x", work={"anchored": 1, "broken": 1, "prose": 0})
    result = measure.measure([blocked] + logged + [logged[1]])
    assert result["answers"] == 2 and result["sessions"] == 1
    assert result["total"] == {"anchored": 3, "broken": 0, "prose": 2, "blocked_before": 1, "caught_broken": 1}
    assert result["rows"][0]["caught_broken"] == 1 and result["rows"][0]["tool"] == "mcp__hearthbot__reply"


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
