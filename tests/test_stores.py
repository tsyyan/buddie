"""NEXT №37: the hook judges web quotes against the snapshots the session took, not only the default store."""
from __future__ import annotations

import io
import json
import subprocess

import pytest

from buddie import hook
from buddie.stores import UnionStore, session_stores
from verbatim.store import Store

from test_buddie import BAD, GOOD, PAGE, URL

CHANGED = PAGE.replace(b"14:59", b"15:30")


@pytest.fixture
def bare(tmp_path, monkeypatch):
    """No store in the hook's environment, nothing fetched: only what the session's own stores hold counts."""
    monkeypatch.delenv("VERBATIM_STORE", raising=False)
    monkeypatch.delenv("BUDDIE_STORES", raising=False)
    monkeypatch.setenv("BUDDIE_FETCH", "0")
    monkeypatch.setenv("BUDDIE_GITHUB", "0")
    monkeypatch.setenv("BUDDIE_LOG", str(tmp_path / "hook.jsonl"))
    monkeypatch.setenv("BUDDIE_REPOS", str(tmp_path / "norepo"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def transcript(path, command):
    rows = [{"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": command}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "snapped 1"}]}}]
    path.write_text("\n".join(json.dumps(r) for r in rows))
    return str(path)


def event(tmp, text, transcript_path=None):
    return {"hook_event_name": "PreToolUse", "tool_name": "mcp__hearthbot__reply", "cwd": str(tmp / "work"),
            "session_id": "s1", "transcript_path": transcript_path, "tool_input": {"text": text}}


def test_store_exported_in_the_threads_shell_is_found(bare):
    (bare / "work").mkdir()
    Store(bare / "snaps").add(URL, PAGE, content_type="text/html")
    t = transcript(bare / "t.jsonl", f"export VERBATIM_STORE={bare}/snaps && verbatim snap {URL}")
    err = io.StringIO()
    assert hook.run(event(bare, BAD, t), err) == 2
    assert "14:59" in err.getvalue() and str(bare / "snaps") in err.getvalue()
    assert hook.run(event(bare, GOOD, t), io.StringIO()) == 0
    logged = [json.loads(x) for x in (bare / "hook.jsonl").read_text().splitlines()]
    assert logged[-1]["quotes"] == {"FOUND": 1} and logged[-1]["stores"] == 1 and logged[-1]["outcome"] == "PASS"

    import importlib.util
    from pathlib import Path
    path = Path(__file__).parents[1] / "dogfood" / "effects" / "measure.py"
    if not path.is_file():  # dogfood/ stays in lab
        return
    spec = importlib.util.spec_from_file_location("measure", path)
    measure = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(measure)
    rows = [dict(x, final=True, work={"anchored": 0, "broken": 0, "prose": 0}) for x in logged]
    result = measure.measure(rows, quotes=True)
    assert result["answers"] == 1 and result["total"]["quotes_found"] == 1 and result["total"]["blocked_before"] == 1


def test_without_the_sessions_store_a_wrong_quote_slipped_through(bare):
    """What the hook did before №37: the thread's store unseen, nothing fetched, a wrong quote only a gap."""
    (bare / "work").mkdir()
    Store(bare / "snaps").add(URL, PAGE, content_type="text/html")
    assert hook.run(event(bare, BAD), io.StringIO()) == 0
    assert json.loads((bare / "hook.jsonl").read_text().splitlines()[-1])["quotes"] == {"SOURCE_UNAVAILABLE": 1}


def test_relative_store_and_dotverbatim_next_to_cwd(bare):
    (bare / "work").mkdir()
    Store(bare / "work" / "out").add(URL, PAGE, content_type="text/html")
    t = transcript(bare / "t.jsonl", f"verbatim snap --store out {URL}")
    assert session_stores(bare / "work", [], t) == [bare / "work" / "out"]
    Store(bare / "work" / ".verbatim").add("https://other.example/x", b"<p>x</p>")
    assert session_stores(bare / "work", [], None) == [bare / "work" / ".verbatim"]


def test_uncommitted_sources_of_a_repo(bare, monkeypatch):
    repo = bare / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    Store(repo / "experiments" / "E1" / "sources").add(URL, PAGE, content_type="text/html")
    monkeypatch.setenv("BUDDIE_REPOS", str(repo))
    (bare / "work").mkdir()
    assert session_stores(bare / "work", [repo]) == [repo / "experiments" / "E1" / "sources"]
    assert hook.run(event(bare, BAD), io.StringIO()) == 2
    assert hook.run(event(bare, GOOD), io.StringIO()) == 0


def test_union_reads_every_root_and_writes_only_the_first(tmp_path):
    Store(tmp_path / "a").add(URL, PAGE, fetched_at="2026-10-03T01:00:00Z")
    Store(tmp_path / "b").add(URL, CHANGED, fetched_at="2026-10-03T02:00:00Z")
    Store(tmp_path / "b").record(URL, {"sha256": None, "fetched_at": "2026-10-03T03:00:00Z", "error": "HTTP 403"})
    union = UnionStore(tmp_path / "main", [tmp_path / "a", tmp_path / "b"])
    newest = union.latest(URL)  # the newest snapshot with bytes, a later failed fetch does not hide it
    assert union.read(newest["sha256"]) == CHANGED
    union.record("https://new.example/", {"sha256": None, "fetched_at": "2026-10-03T04:00:00Z"})
    assert list(Store(tmp_path / "main").index()) == ["https://new.example/"]
    assert "https://new.example/" not in Store(tmp_path / "a").index()
