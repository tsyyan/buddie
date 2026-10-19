"""Offline: snapshots are added to a temp store, anchors are checked against a temp git repo."""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from buddie import anchors, hook, mcp
from buddie.verify import verify
from verbatim.store import Store

ROOT = Path(__file__).resolve().parents[1]
URL = "https://news.example.org/outage"
PAGE = ("<html><body><article><h1>Outage</h1><p>" + "Background paragraph about the service. " * 40
        + "</p><p>The company said the outage began at 14:59 UTC and was resolved within two hours.</p>"
        "</article></body></html>").encode()
GOOD = f"The vendor wrote that “the outage began at 14:59 UTC and was resolved within two hours” ([report]({URL}))."
BAD = f"The vendor wrote that “the outage began at 14:58 UTC and was resolved within two hours” ([report]({URL}))."


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "store"
    Store(path).add(URL, PAGE, content_type="text/html")
    monkeypatch.setenv("VERBATIM_STORE", str(path))
    monkeypatch.setenv("BUDDIE_LOG", str(tmp_path / "hook.jsonl"))
    return str(path)


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    (path / "data.txt").write_bytes(b"hello\n")
    git = ["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(git + ["add", "."], check=True)
    subprocess.run(git + ["commit", "-qm", "init"], check=True)
    commit = subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    return path, commit, hashlib.sha256(b"hello\n").hexdigest()


def test_found_quote_passes(store):
    pred = verify(GOOD, store=store, fetch=False)["predicate"]
    assert pred["outcome"] == "PASS"
    assert pred["quotes"][0]["verdict"] == "FOUND"
    assert pred["quotes"][0]["sha256"] == hashlib.sha256(PAGE).hexdigest()
    assert pred["line"] == "buddie PASS: quotes 1/1 found"


def test_wrong_digit_fails_with_closest(store):
    pred = verify(BAD, store=store, fetch=False)["predicate"]
    assert pred["outcome"] == "FAIL"
    assert pred["quotes"][0]["closest"]["ratio"] > 0.9
    assert "14:59" in pred["blocking"][0]


def test_unread_source_is_a_gap_not_a_failure(store):
    text = "It said “a sentence on a page nobody fetched” ([x](https://unfetched.example.org/a))."
    assert verify(text, store=store, fetch=False)["predicate"]["outcome"] == "GAPS"


def test_receipt_is_an_in_toto_statement(store):
    receipt = verify(GOOD, name="r.md", store=store, fetch=False)
    assert receipt["_type"] == "https://in-toto.io/Statement/v1"
    assert receipt["subject"][0]["digest"]["sha256"] == hashlib.sha256(GOOD.encode()).hexdigest()


def test_anchors(repo):
    path, commit, sha = repo
    text = (f"`⚓ data.txt#{sha[:12]}` `⚓ data.txt#{'0' * 12}` `⚓ data.txt@{commit[:7]}` "
            f"`⚓ gone.txt@{commit[:7]}` `⚓ other.txt#{'a' * 12}` `⚓ data.txt@{'b' * 7}` `⚓ x.count=3`")
    got = [a["status"] for a in anchors.check_text(text, [path])]
    assert got == ["HOLDS", "BROKEN", "HOLDS", "BROKEN", "UNCHECKABLE", "UNCHECKABLE", "UNCHECKABLE"]
    pred = verify(text, repos=[path], quotes=False)["predicate"]
    assert pred["outcome"] == "FAIL" and len(pred["blocking"]) == 2


def test_anchor_sign_before_the_backticks(repo):
    """NEXT №67: the skill writes ⚓ `path@commit`; E016 found 18 of 36 reports in that form, judged as unanchored."""
    path, commit, sha = repo
    inside = f"`⚓ data.txt#{sha[:12]}` and `⚓ data.txt#{'0' * 12}`"
    outside = f"⚓ `data.txt#{sha[:12]}` and ⚓`data.txt#{'0' * 12}`"
    assert anchors.ANCHOR.findall(outside) == anchors.ANCHOR.findall(inside)
    got = [a["status"] for a in anchors.check_text(outside, [path])]
    assert got == ["HOLDS", "BROKEN"]
    assert verify(outside, repos=[path], quotes=False)["predicate"]["outcome"] == "FAIL"
    # the sign as code of its own, or right after other code, is not an anchor around the next code span
    assert anchors.ANCHOR.findall("all `⚓` anchors in `markdown` hold") == []
    assert anchors.ANCHOR.findall("`code`⚓ `x.count=3`") == ["x.count=3"]


@pytest.mark.skipif(not (ROOT.parents[1] / "tools" / "anchors.py").is_file(), reason="outside lab")
def test_lab_facts_resolve():
    lab = ROOT.parents[1]
    value = anchors.check_text("`⚓ e002.claims=115`", [lab])[0]
    assert value["status"] == "HOLDS"


def test_empty():
    assert verify("nothing here", quotes=True, fetch=False)["predicate"]["outcome"] == "EMPTY"


def _rpc(*msgs):
    out = io.StringIO()
    mcp.serve(io.StringIO("".join(json.dumps(m) + "\n" for m in msgs)), out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_mcp_protocol(store):
    init, listed, called, bad = _rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "verify_report", "arguments": {"text": BAD, "fetch": False, "repos": []}}},
        {"jsonrpc": "2.0", "id": 4, "method": "nope"})
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert {t["name"] for t in listed["result"]["tools"]} == {"verify_report", "snap", "source_text", "summary"}
    assert called["result"]["content"][0]["text"].startswith("buddie FAIL")
    assert called["result"]["structuredContent"]["predicate"]["outcome"] == "FAIL"
    assert bad["error"]["code"] == -32601


def test_mcp_source_text(store):
    (res,) = _rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"name": "source_text", "arguments": {"ref": URL, "grep": "14:5\\d"}}})
    assert "14:59 UTC" in res["result"]["structuredContent"]["matches"][0]["text"]


def test_hook_blocks_fail_and_lets_disclosed_through(store, monkeypatch, tmp_path):
    monkeypatch.setenv("BUDDIE_FETCH", "0")
    event = {"hook_event_name": "PreToolUse", "tool_name": "mcp__hearthbot__reply", "cwd": str(tmp_path),
             "tool_input": {"text": BAD}}
    err = io.StringIO()
    assert hook.run(event, err) == 2
    assert "not found" in err.getvalue()
    event["tool_input"]["text"] = BAD + "\n\nbuddie: the 14:58 quote is not in the source, kept as the agent's claim"
    assert hook.run(event, io.StringIO()) == 0
    event["tool_input"]["text"] = GOOD
    assert hook.run(event, io.StringIO()) == 0


def test_hook_final_answer_must_carry_its_numbers(store, repo, monkeypatch, tmp_path):
    import hashlib
    monkeypatch.setenv("BUDDIE_FETCH", "0")
    monkeypatch.setenv("BUDDIE_REPOS", str(repo))
    sha = hashlib.sha256(b"hello\n").hexdigest()[:12]
    event = {"hook_event_name": "PreToolUse", "tool_name": "mcp__hearthbot__reply", "cwd": str(tmp_path),
             "tool_input": {"text": "Done: 3 из 4 checks pass.\n\nСледующий шаг: run it again."}}
    err = io.StringIO()
    assert hook.run(event, err) == 2
    assert "no anchor" in err.getvalue() and "3 из 4" in err.getvalue()
    event["tool_input"]["text"] = f"Done: 3 из 4 checks pass `⚓ data.txt#{sha}`.\n\nСледующий шаг: run it again."
    assert hook.run(event, io.StringIO()) == 0
    event["tool_input"]["text"] = "Done: 3 из 4 checks pass.\nbuddie: counted by hand\n\nСледующий шаг: rerun."
    assert hook.run(event, io.StringIO()) == 0
    event["tool_input"]["text"] = "Interim: 3 из 4 checks pass."  # not a final answer: a signal, not a block
    assert hook.run(event, io.StringIO()) == 0
    monkeypatch.setenv("BUDDIE_FINAL", "")
    event["tool_input"]["text"] = "Done: 3 из 4.\n\nСледующий шаг: rerun."
    assert hook.run(event, io.StringIO()) == 0
    logged = [json.loads(x) for x in (tmp_path / "hook.jsonl").read_text().splitlines()]
    assert [x["exit"] for x in logged] == [2, 0, 0, 0, 0] and logged[0]["final"] is True


def test_plugin_default_final_answer_is_the_last_message_at_stop(store, repo, monkeypatch, tmp_path):
    """NEXT №91 (audit/19 Б3): without BUDDIE_FINAL or a final_mark in buddie.toml the final answer is the last
    message at Stop, in any language; a project that hands in results through a tool names its mark in buddie.toml."""
    monkeypatch.delenv("BUDDIE_FINAL")
    monkeypatch.setenv("BUDDIE_FETCH", "0")
    path, _, _ = repo
    monkeypatch.setenv("BUDDIE_REPOS", str(path))
    transcript = tmp_path / "t.jsonl"
    rows = [{"type": "user", "message": {"content": "go"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Done: 3 of 4 checks pass."}]}}]
    transcript.write_text("\n".join(json.dumps(r) for r in rows))
    stop = {"hook_event_name": "Stop", "transcript_path": str(transcript), "cwd": str(tmp_path)}
    err = io.StringIO()
    assert hook.run(stop, err) == 2 and "no anchor" in err.getvalue()
    reply = {"hook_event_name": "PreToolUse", "tool_name": "SendMessage", "cwd": str(tmp_path),
             "tool_input": {"message": "Done: 3 of 4 checks pass.\n\nСледующий шаг: rerun."}}
    assert hook.run(reply, io.StringIO()) == 0  # a message to another session is not the final answer by default
    (path / "buddie.toml").write_text('[mandate]\nfinal_mark = "Следующий шаг:"\n')
    (path / "NEXT.md").write_text("| # | Step | From | Basis | Status |\n|---|---|---|---|---|\n")
    assert hook.final_mark(reply) == "Следующий шаг:"
    assert hook.run(reply, io.StringIO()) == 2
    monkeypatch.setenv("BUDDIE_FINAL", "")
    assert hook.run(reply, io.StringIO()) == 0 and hook.run(stop, io.StringIO()) == 0


def test_hook_stop_reads_transcript_and_never_loops(store, monkeypatch, tmp_path):
    monkeypatch.setenv("BUDDIE_FETCH", "0")
    transcript = tmp_path / "t.jsonl"
    rows = [{"type": "user", "message": {"content": "go"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": BAD}]}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "x"}]}}]
    transcript.write_text("\n".join(json.dumps(r) for r in rows))
    event = {"hook_event_name": "Stop", "transcript_path": str(transcript), "cwd": str(tmp_path)}
    assert hook.run(event, io.StringIO()) == 2
    assert hook.run(dict(event, stop_hook_active=True), io.StringIO()) == 0


def test_launcher_serves_over_stdio(store):
    msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
    out = subprocess.run([sys.executable, str(ROOT / "run.py"), "serve"], input=msg, capture_output=True, text=True,
                         timeout=60)
    assert json.loads(out.stdout)["result"]["tools"][0]["name"] == "verify_report"


def test_plugin_manifests_parse():
    for rel in (".claude-plugin/plugin.json", ".mcp.json", "hooks/hooks.json"):
        json.loads((ROOT / rel).read_text())
    # lab keeps the marketplace at its root; the public buddie repo is plugin and marketplace at once
    home = ROOT if (ROOT / ".claude-plugin" / "marketplace.json").is_file() else ROOT.parents[1]
    market = json.loads((home / ".claude-plugin" / "marketplace.json").read_text())
    assert (home / market["plugins"][0]["source"] / ".claude-plugin" / "plugin.json").is_file()


def test_unanchored_counts_are_a_signal_not_a_failure():
    text = ("Прочитано 73 из 84 ссылок, ложных 11 %.\n"
            "PR lab#30 слит 2026-10-01 в 22:04, шаг №20.\n"
            "Цитат `⚓ e002.claims=115` из 115.")
    pred = verify(text, quotes=False)["predicate"]
    assert pred["summary"]["unanchored_count_lines"] == 1, pred["unanchored"]
    assert pred["unanchored"][0].startswith("line 1:")
    assert pred["outcome"] == "GAPS" and pred["line"].endswith("1 lines with counts and no anchor; 1 work claims in prose")


def test_lone_year_is_not_a_count():
    """NEXT №108: a year names a time, as a date does; the count next to it still counts."""
    assert anchors.counts("Населения по переписи 2020 года на странице нет") == []
    assert anchors.counts("Оценку на 2021 год я не стал выдавать, за 2024 год тоже") == []
    assert anchors.counts("Основана в 1987 году, founded in 1987; Population (2021); в марте 2024-го") == []
    assert anchors.counts("Вышел 14 марта 2024 года, published on 14 March 2024.") == []
    assert anchors.counts("в 2020–2021 гг. было 12 случаев") == ["12"]
    assert anchors.counts("Обработано 2000 строк, 3 теста прошли") == ["2000", "3"]
    assert anchors.counts("Population (2021): 51,880") == ["51,880"]


E017 = ROOT.parents[1] / "experiments" / "E017-subtle-traps" / "results-101" / "raw" / "gate"


@pytest.mark.skipif(not E017.is_dir(), reason="outside lab")
def test_e017_replay_years_are_not_returned():
    """E017 replay (NEXT №101): 46c483 was returned for lines 1, 5, 9 and e013da for line 10, which state only years
    («по переписи 2020 года», «за 2024 год»). Offline, with no page store, the lines whose numbers the gate found
    in a quote with its URL stay; the year-only lines are gone. 0c52bd keeps «3 теста прошли, 3 пропущены»."""
    expect = {"46c483": ["line 6", "line 7"], "e013da": ["line 6", "line 7"], "0c52bd": ["line 1"]}
    for rid, lines in expect.items():
        pred = verify((E017 / f"{rid}.0.md").read_text(encoding="utf-8"), quotes=False, mandate=False)["predicate"]
        assert [u.split(":")[0] for u in pred["unanchored"]] == lines, (rid, pred["unanchored"])


def test_number_next_to_a_found_quote_with_its_url_is_backed(store):
    """NEXT №71: a count on a line whose quote is FOUND at the URL of that same line has its source; without the URL
    on the line (no link, or the link on another line) it is still a number without anchor."""
    quote = "“the outage began at 14:59 UTC and was resolved within two hours”"
    linked = f"Down for 2 hours: {quote} ({URL})"
    text = "\n".join([linked, f"Down for 2 hours: {quote}.", f"Down for 2 hours: {quote}", f"Source: {URL}"])
    pred = verify(text, store=store, fetch=False)["predicate"]
    assert pred["quote_backed"] == [1]
    assert [u.split(":")[0] for u in pred["unanchored"]] == ["line 2", "line 3"]
    final = "Done.\n" + linked + "\nbuddie: the receipt is attached\n\nСледующий шаг: rerun."
    assert verify(final, store=store, fetch=False)["predicate"]["unanchored"] == []


E016 = ROOT.parents[1] / "experiments" / "E016-advice-vs-gates"


@pytest.mark.skipif(not (E016 / "results" / "runs.json").is_file(), reason="outside lab")
def test_e016_de7a5d_quote_backed_numbers_are_not_returned(tmp_path, monkeypatch):
    """E016 advice report de7a5d: lines 3, 4 and 6 quote the task page with its URL (FOUND 3/3) and were returned as
    'number without anchor' (results/regate_labels.json: false). Now they pass; strip a URL and that line returns."""
    from buddie import journal
    path = tmp_path / "store"
    page = "http://127.0.0.1:8765/t04/acme.html"
    Store(path).add(page, (E016 / "pages" / "t04" / "acme.html").read_bytes(), content_type="text/html")
    text = json.loads((E016 / "results" / "runs.json").read_text())["de7a5d"]["reports"][0]
    pred = verify(text, store=str(path), fetch=False, mandate=False)["predicate"]
    assert pred["summary"]["quotes"] == {"FOUND": 3} and pred["quote_backed"] == [3, 4, 6]
    assert pred["unanchored"] == [] and not hook.unbacked(pred)
    assert not [i for i in journal.flagged(pred, text, True) if i["kind"] == "final_bare"]
    cut = text.replace("» (" + page + ")", "»", 1)  # line 3 keeps its quote, loses its URL
    pred = verify(cut, store=str(path), fetch=False, mandate=False)["predicate"]
    assert pred["quote_backed"] == [4, 6] and pred["unanchored"][0].startswith("line 3:")
    assert hook.unbacked(pred) == ["number without anchor, " + pred["unanchored"][0]]


def test_unlinked_term_in_quotes_is_not_a_citation():
    pred = verify("Мы называем это «доказательный слой для чатов».", fetch=False)["predicate"]
    assert pred["outcome"] == "EMPTY" and pred["summary"]["unlinked_terms"] == 1
    pred = verify("The author said: “an evidence layer for chats”.", fetch=False)["predicate"]  # speaker cues are English
    assert pred["summary"]["quotes"] == {"NO_SOURCE": 1}


NUM_URL = "https://market.example/pos"
NUM_PAGE = ("<p>" + "Market background and other text. " * 40 + "</p><p>The tablet POS market was valued at "
            "USD 3.4 billion in 2022, growing at 7.1% a year.</p>").encode()


def test_numbers_not_in_source_are_a_gap_or_a_failure(tmp_path):
    path = tmp_path / "s"
    Store(path).add(NUM_URL, NUM_PAGE, content_type="text/html")
    good = f"The tablet POS market was worth $3.4 billion in 2022 ([Zion]({NUM_URL})).\n"
    bad = f"The tablet POS market was worth $3.4 billion in 2022 and grows 9.5% a year ([Zion]({NUM_URL})).\n"
    pred = verify(good, store=str(path), fetch=False)["predicate"]
    assert pred["outcome"] == "PASS" and pred["summary"]["numbers"] == {"FOUND": 2}
    assert pred["line"].startswith("buddie PASS: numbers 2/2 found")
    pred = verify(bad, store=str(path), fetch=False)["predicate"]
    assert pred["outcome"] == "GAPS" and "9.5%" in pred["gaps"][0]
    pred = verify(bad, store=str(path), fetch=False, numbers="fail")["predicate"]
    assert pred["outcome"] == "FAIL" and "9.5%" in pred["blocking"][0]
    assert verify(bad, store=str(path), fetch=False, numbers="off")["predicate"]["outcome"] == "EMPTY"


def test_a_number_missing_from_an_abstract_page_is_a_gap_even_in_fail_mode(tmp_path):
    # verbatim 0.3.6 (NEXT №66): an arXiv /abs/ page holds the abstract, not the numbers of the paper
    url = "https://arxiv.org/abs/1904.04178"
    path = tmp_path / "s"
    page = "<p>" + "Abstract: we study dropout and its effect on agreement with human ratings. " * 20 + "</p>"
    Store(path).add(url, page.encode(), content_type="text/html")
    text = f"Dropout of 5% raised the correlation with human ratings ([paper]({url})).\n"
    pred = verify(text, store=str(path), fetch=False, numbers="fail")["predicate"]
    assert pred["outcome"] == "GAPS" and pred["blocking"] == []
    assert pred["numbers"][0]["verdict"] == "UNCERTAIN" and pred["numbers"][0]["doubts"] == ["abstract_only"]
    assert "UNCERTAIN (abstract_only)" in pred["gaps"][0]


def test_one_version_everywhere():
    """The public tree carried 0.5 code as 0.3.0 (NEXT №51): package, pyproject and plugin must agree."""
    import tomllib
    from pathlib import Path
    from buddie import __version__
    root = Path(__file__).parents[1]
    assert tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"] == __version__
    plugin = root / ".claude-plugin" / "plugin.json"
    assert json.loads(plugin.read_text())["version"] == __version__
