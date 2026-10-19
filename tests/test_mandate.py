"""Work claims (buddie v0.2, NEXT №28): offline, on a temp git repo with its own buddie.toml, plus lab's real queue."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from buddie import hook
from buddie import mandate as man
from buddie.verify import verify

LAB = Path(__file__).resolve().parents[3]

CONFIG = """
[mandate]
ask_words = 'опублик|внешн'
messages = "messages.jsonl"
messages_complete = true

[[mandate.refs]]
pattern = 'PLAN этап (?P<stage>\\d+(?:[–-]\\d+)?)'
doc = "PLAN.md"
level = "stage"

[[mandate.refs]]
pattern = 'audit/(?P<nn>\\d{2})(?: §(?P<sec>\\d+(?:\\.\\d+)*))?'
doc = "audit/{nn}"
"""
HEAD = "| # | Предложение | Источник | Основание | Статус |\n|---|---|---|---|---|\n"
MESSAGES = [
    {"id": "m1", "at": "2026-10-01T20:56:25Z", "author": "user", "text": "автосоздание разрешено, если план совпадает"},
    {"id": "m2", "at": "2026-10-01T19:02:22Z", "edited_at": "2026-10-01T19:03:40Z", "author": "user",
     "text": "аудит и шаги принимаем и приступаем к реализации"},
]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    (path / "buddie.toml").write_text(CONFIG, encoding="utf-8")
    (path / "data.txt").write_bytes(b"hello\n")
    (path / "messages.jsonl").write_text("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in MESSAGES))
    (path / "ACCEPTED.md").write_text("| Область | Слова |\n|---|---|\n| `PLAN этап 0-3` | x |\n| `audit/07 §2` | x |\n",
                                      encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    git(path, "add", ".")
    git(path, "commit", "-qm", "init")
    commit = git(path, "rev-parse", "--short", "HEAD")
    rows = [f"a | т | PLAN этап 2 | выполнено `⚓ data.txt@{commit}`",
            "b | т | PLAN этап 2 ← №1 | предложено",
            "c | т | PLAN этап 3 ← №1 | предложено",
            "d | т | audit/07 §2.1 ← №1 | предложено",
            "e | т | PLAN этап 2 | выполнено",
            "f | т | PLAN этап 2 ← №1 | предложено, опубликовать"]
    rows[5] = "опубликовать отчёт | т | PLAN этап 2 ← №1 | предложено"
    (path / "NEXT.md").write_text(HEAD + "".join(f"| {i} | {r} |\n" for i, r in enumerate(rows, 1)), encoding="utf-8")
    git(path, "add", ".")
    git(path, "commit", "-qm", "queue")
    return path


def claims(repo, text, **kw):
    return man.check_text(text, man.load_config(repo), **kw)


def test_verdicts_follow_the_plan(repo):
    m = man.Mandate(man.load_config(repo))
    assert m.verdict(2)["verdict"] == "auto"
    assert "stage" in m.verdict(3)["reasons"][0]          # PLAN stage 2 → 3 is the user's call
    assert any("another plan" in r for r in m.verdict(4)["reasons"])
    assert any("outward" in r for r in m.verdict(6)["reasons"])


def test_done_claims(repo):
    out = claims(repo, "Шаг №1 выполнен.\nШаг №5 выполнен.\nШаг №2 выполнен.\nШаг №2 ещё не выполнен.\nШаг №9 done")
    assert [c["status"] for c in out] == [man.HOLDS, man.UNSUPPORTED, man.BROKEN, man.BROKEN]


def test_auto_claim_is_recomputed(repo):
    ok, wrong = claims(repo, "Запускаю сам (вердикт `auto`): шаг №2.\nЗапускаю сам (вердикт `auto`): шаг №3.")
    assert ok["status"] == man.HOLDS
    assert wrong["status"] == man.BROKEN and "computed ask" in wrong["why"]
    # a parent named in the sentence is not a claim about the parent
    (c,) = claims(repo, "№2 ← №1, вердикт auto")
    assert c["row"] == 2
    (c,) = claims(repo, "вердикт `auto`: следующая правка")
    assert c["status"] == man.UNSUPPORTED


def test_anchored_queue_is_judged_at_its_commit(repo):
    before = git(repo, "rev-parse", "--short", "HEAD")
    text = (repo / "NEXT.md").read_text(encoding="utf-8").replace("PLAN этап 2 ← №1 | предложено |",
                                                                  "PLAN этап 2 ← №1 | выполнено |", 1)
    (repo / "NEXT.md").write_text(text, encoding="utf-8")
    git(repo, "commit", "-qam", "row 2 done")
    (c,) = claims(repo, "Вердикт `auto` для №2.")
    assert c["status"] == man.BROKEN                       # now it is done, not proposed
    (c,) = claims(repo, f"Вердикт `auto` для №2 (`⚓ NEXT.md@{before}`).")
    assert c["status"] == man.HOLDS and c["rev"] == before


def test_consent_needs_the_users_words_at_that_time(repo):
    out = claims(repo, "\n".join([
        "Решение пользователя 2026-10-01 20:56 UTC: «автосоздание разрешено, если план совпадает».",
        "Пользователь принял аудит 2026-10-01 19:03 UTC: «аудит и шаги принимаем и приступаем к реализации».",
        "Пользователь одобрил 2026-10-02 10:00 UTC: «автосоздание разрешено, если план совпадает».",
        "Пользователь одобрил 2026-10-01: «публиковать можно без вопросов».",
        "Пользователь одобрил это направление.",
        "Пользователь одобрил: «автосоздание разрешено, если план совпадает».",
    ]))
    assert [c["status"] for c in out] == [man.HOLDS, man.HOLDS, man.BROKEN, man.BROKEN, man.UNSUPPORTED,
                                          man.UNSUPPORTED]
    assert out[0]["messages"] == ["m1"]


def test_partial_export_cannot_refute(repo):
    cfg = dict(man.load_config(repo), messages_complete=False)
    (c,) = man.check_text("Пользователь одобрил 2026-10-01: «публиковать можно без вопросов».", cfg)
    assert c["status"] == man.UNCHECKABLE


def test_next_step_names_its_row(repo):
    ok, missing, unknown = claims(repo, "Следующий шаг: №2, продолжить.\nСледующий шаг: продолжить.\nСледующий шаг: №40.")
    assert ok["status"] == man.HOLDS and ok["computed"] == "auto"
    assert missing["status"] == man.UNSUPPORTED
    assert unknown["status"] == man.BROKEN


def test_queue_and_accepted(repo):
    q = man.check_queue(man.load_config(repo))
    assert [d["status"] for d in q["done"]] == [man.HOLDS, man.UNSUPPORTED]
    assert [v["verdict"] for v in q["proposed"]] == ["auto", "ask", "ask", "ask"]
    assert {a["scope"]: a["status"] for a in man.check_accepted(man.load_config(repo))} == \
        {"PLAN этап 0-3": man.UNSUPPORTED, "audit/07 §2": man.UNSUPPORTED}


def test_receipt_and_hook(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("BUDDIE_LOG", str(tmp_path / "hook.jsonl"))
    pred = verify("Запускаю сам (вердикт `auto`): шаг №3.", repos=[repo], quotes=False)["predicate"]
    assert pred["outcome"] == "FAIL"
    assert pred["summary"]["mandate"] == {"verdict:BROKEN": 1}
    assert "work claims 0/1 hold, 1 broken" in pred["line"]
    assert verify("Запускаю сам: шаг №3.", repos=[repo], quotes=False, mandate=False)["predicate"]["outcome"] == "EMPTY"
    monkeypatch.setenv("BUDDIE_REPOS", str(repo))
    monkeypatch.setenv("BUDDIE_FETCH", "0")
    event = {"hook_event_name": "PreToolUse", "tool_name": "mcp__hearthbot__reply", "cwd": str(repo),
             "tool_input": {"text": "Запускаю сам (вердикт `auto`): шаг №3."}}
    assert hook.run(event, err=open(os.devnull, "w")) == 2


@pytest.mark.skipif(not (LAB / "tools" / "chain.py").is_file(), reason="outside lab")
def test_lab_config_matches_chain_py():
    """buddie's generic queue rule on lab's buddie.toml gives tools/chain.py's verdict for every row of NEXT.md."""
    sys.path.insert(0, str(LAB / "tools"))
    import chain
    table = chain.rows()
    m = man.Mandate(man.load_config(LAB))
    assert set(m.table) == set(table)
    assert [m.verdict(n)["verdict"] for n in sorted(table)] == [chain.verdict(n, table)["verdict"] for n in sorted(table)]
    # and the same when time conditions are judged at a moment (NEXT №76): every row as if main got it at `start`
    assert (m.cfg["wait_words"], m.cfg["wait_not_before"], m.cfg["wait_delay"], m.cfg["wait_units"]) == (
        chain.CONDITION.pattern, chain.NOT_BEFORE.pattern, chain.DELAY.pattern, chain.UNIT_HOURS)
    for start, now in [("2026-10-03T01:00:00Z", "2026-10-03T02:00:00Z"), ("2026-10-03T01:00:00Z", "2026-10-05T02:00:00Z"),
                       (None, "2999-01-01T00:00:00Z")]:
        assert [m.verdict(n, start, now)["verdict"] for n in sorted(table)] == [
            chain.verdict(n, table, start=start, now=now)["verdict"] for n in sorted(table)]
    # and at the clock with each row's own start (NEXT №83): buddie's `appeared` is chain.py's, so the launch gate and
    # the summary give a row whose time came due the verdict `debt` gives it
    if history := chain._first_parent("HEAD"):
        appeared, now = chain._appeared(history)[0], chain._utc(datetime.now(timezone.utc).isoformat())
        h, head = man.Mandate(man.load_config(LAB), "HEAD"), chain.rows(chain._show("HEAD", "NEXT.md"))
        assert {n: h.appeared(n) for n in h.table} == {n: appeared.get(n) for n in head}
        assert [h.verdict_now(n, now)["verdict"] for n in sorted(h.table)] == [
            chain.verdict(n, head, start=appeared.get(n), now=now)["verdict"] for n in sorted(head)]


def test_time_condition_comes_due():
    cfg = {**man.DEFAULTS, "waiting": "ждёт условия", "wait_words": r"\bчерез сутки|\bне раньше \d{4}-\d{2}-\d{2}|\bкогда наберутся",
           "wait_not_before": r"не раньше (?P<date>\d{4}-\d{2}-\d{2})(?:[ T](?P<time>\d{2}:\d{2}))?",
           "wait_delay": r"(?:через )?(?:(?P<k>\d+) )?(?P<unit>сут|час)\w*", "wait_units": {"сут": 24, "час": 1}}
    row = lambda text, status="предложено": {"text": text, "status": status}
    assert man.waits(cfg, row("через сутки снять")) == "через сутки"
    assert man.waits(cfg, row("через сутки снять"), "2026-10-03T01:00:00Z", "2026-10-04T00:59:00Z") == "через сутки"
    assert man.waits(cfg, row("через сутки снять"), "2026-10-03T01:00:00Z", "2026-10-04T01:00:00Z") is None
    assert man.waits(cfg, row("через сутки снять"), None, "2999-01-01T00:00:00Z") == "через сутки"  # no start, no due
    assert man.waits(cfg, row("не раньше 2026-10-04 02:00 UTC пройти"), None, "2026-10-04T02:00:00Z") is None
    assert man.waits(cfg, row("через сутки, когда наберутся 3"), "2026-10-03T01:00:00Z", "2026-10-05T00:00:00Z") == "когда наберутся"
    assert man.waits(cfg, row("через сутки снять", "предложено; ждёт условия"), "2026-10-03T01:00:00Z",
                     "2026-10-05T00:00:00Z") is None
    assert man.waits(cfg, row("снять", "предложено; ждёт условия"), "2026-10-03T01:00:00Z", "2026-10-05T00:00:00Z") == "status"


def test_queue_anchor_at_a_missing_commit_is_a_claim_not_a_crash(repo, tmp_path):
    # NEXT №105: `⚓ NEXT.md@<no such commit>` used to raise FileNotFoundError out of verify (exit 1, like FAIL)
    line = "Вердикт `auto` для №2 (`⚓ NEXT.md@deadbeef1234`)."
    (c,) = claims(repo, line)
    assert c["kind"] == "queue" and c["status"] == man.BROKEN and "deadbeef1234" in c["why"]
    receipt = verify(line, repos=[repo], quotes=False)
    assert receipt["predicate"]["outcome"] == "FAIL"
    assert any("queue line 1" in b for b in receipt["predicate"]["blocking"])
    # in a shallow clone the commit may lie below the cut: a gap, not a refutation
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{repo}", str(shallow)], check=True)
    (c,) = claims(shallow, line)
    assert c["status"] == man.UNCHECKABLE and "shallow" in c["why"]


def test_cli_missing_rev_is_a_usage_error(repo, tmp_path, capsys):
    from buddie.cli import main
    report = tmp_path / "r.md"
    report.write_text("Вердикт `auto` для №2 (`⚓ NEXT.md@deadbeef1234`).\n", encoding="utf-8")
    assert main(["verify", str(report), "--repo", str(repo), "--anchors-only", "--no-github"]) == 1   # FAIL
    assert main(["mandate", "queue", "--repo", str(repo), "--rev", "deadbeef1234"]) == 2
    assert "deadbeef1234" in capsys.readouterr().err
