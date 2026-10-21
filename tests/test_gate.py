"""PR #27: the gate takes each item's class from its finding, and the event is resolved once. The gate's output on
819 scenarios is held equal to what it was before (tests/data/gate_golden.json)."""
from __future__ import annotations

import hashlib
import io
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from buddie import config, core, hook, mandate, resolved
from buddie.config import Source
from buddie.verbatim.store import Store
from buddie.verify import assess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import gate_scenarios as gs  # noqa: E402


def test_the_gate_answers_every_scenario_as_before():
    """Exit codes, what the model reads (stderr), what the person sees (stdout) and the journal lines, for each
    answer x config x environment x event, each run twice (the second meets the first's pending return)."""
    golden = json.loads((ROOT / "tests" / "data" / "gate_golden.json").read_text(encoding="utf-8"))
    now = gs.run_all()
    assert set(now) == set(golden)
    for key in golden:
        assert now[key] == golden[key], key


# --- typed classes ------------------------------------------------------------------------------------------------

@pytest.fixture
def world(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "data.txt").write_bytes(b"hello\n")
    Store(tmp_path / "store").add(gs.URL, gs.PAGE, content_type="text/html")
    return repo, str(tmp_path / "store")


@pytest.mark.parametrize("numbers", ["gap", "fail"])
@pytest.mark.parametrize("text", [gs.TEXTS["mixed"], gs.TEXTS["number_miss"], gs.TEXTS["bad_quote"],
                                  f"{gs.BROKEN} `⚓ ../x#{'0' * 12}` `⚓ not an anchor` `⚓ data.txt@{'b' * 7}` `⚓ x.count=3`"])
def test_typed_classes_equal_the_words_classes(world, text, numbers):
    repo, store = world
    receipt, found, _ = assess(text, store=store, fetch=False, repos=[repo], numbers=numbers)
    pred = receipt["predicate"]
    typed = hook.gate_items(pred, found, numbers)
    assert typed == [(i, config.classify(i)) for i in pred["blocking"]]
    assert all(cls is not None for _, cls in typed)


def test_an_unknown_check_blocks_whatever_the_levels_say(world, monkeypatch):
    """A check the gate has no class for gets none, and an item with no class blocks: a level set to warn or off
    for a known class does not reach it."""
    repo, store = world
    receipt, found, _ = assess(gs.TEXTS["bad_quote"], store=store, fetch=False, repos=[repo])
    monkeypatch.setattr(config, "CLASS_OF_CHECK", {k: v for k, v in config.CLASS_OF_CHECK.items()
                                                   if k is not core.Check.QUOTE})
    [(item, cls)] = hook.gate_items(receipt["predicate"], found, "gap")
    lv = config.levels({"gates": {"quotes": "off"}})
    assert cls is None and lv.get(cls or "", "block") == "block"


def test_a_count_mismatch_falls_back_to_the_words(world):
    repo, store = world
    receipt, found, _ = assess(gs.TEXTS["bad_quote"], store=store, fetch=False, repos=[repo])
    pred = dict(receipt["predicate"], blocking=receipt["predicate"]["blocking"] + ["anchor line 9 ⚓ x: made up"])
    assert hook.gate_items(pred, found, "gap") == [(i, config.classify(i)) for i in pred["blocking"]]


def test_blocking_findings_follow_the_receipt_order(world):
    repo, store = world
    receipt, found, _ = assess(gs.TEXTS["mixed"] + " " + gs.TEXTS["number_miss"], store=store, fetch=False,
                               repos=[repo], numbers="fail")
    from buddie.verify import blocking_findings
    behind = blocking_findings(found, "fail")
    assert [f.check for f in behind] == [core.Check.QUOTE, core.Check.FILE_ANCHOR, core.Check.NUMBER]
    assert len(behind) == len(receipt["predicate"]["blocking"])


# --- the resolved event context -----------------------------------------------------------------------------------

def _repo(base: Path, name: str, toml: str | None) -> Path:
    r = base / name
    r.mkdir()
    if toml is not None:
        (r / "buddie.toml").write_text(toml, encoding="utf-8")
    return r


@pytest.mark.parametrize("tomls", [
    (None, None), ('[gates]\nquotes = "warn"\n', None), (None, '[mandate]\nfinal_mark = "Done"\n'),
    ('[gates]\nprose = "block"\n', '[mandate]\nfinal_mark = "X"\nqueue = "Q.md"\n'),
    ('[mandate]\nqueue = "A.md"\n', '[mandate]\nfinal_mark = "B"\n'), ('not toml [', '[mandate]\nfinal_mark = "B"\n'),
    ('[intro]\nfinals = 3\n[transcript]\nread = false\n[journal]\ntext = true\n', None)])
@pytest.mark.parametrize("env", [{}, {"BUDDIE_GATES": "quotes=off", "BUDDIE_FINAL": "M", "BUDDIE_TRANSCRIPT": "1"}])
def test_the_context_resolves_as_the_readers_it_replaces(tmp_path, monkeypatch, tomls, env):
    for k in ("BUDDIE_GATES", "BUDDIE_FINAL", "BUDDIE_TRANSCRIPT", "CLAUDE_PLUGIN_OPTION_READ_TRANSCRIPT",
              "BUDDIE_JOURNAL_TEXT"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    repos = [_repo(tmp_path, f"r{i}", t) for i, t in enumerate(tomls)]
    monkeypatch.setenv("BUDDIE_REPOS", ";".join(map(str, repos)) if sys.platform == "win32" else ":".join(map(str, repos)))
    event = {"hook_event_name": "Stop", "session_id": "s", "cwd": str(repos[0])}
    ctx = resolved.resolve(event)
    path, cfg = config.of_event(event)
    assert (ctx.config_path, ctx.config, ctx.final_mark) == (path, cfg, config.final_mark(event))
    assert ctx.levels == config.resolve_levels(cfg, path is not None)
    assert ctx.transcript == config.resolve_transcript(cfg) and ctx.journal_text == config.journal_text(cfg)
    try:
        expected = mandate.find_config(repos) or {}
    except Exception:  # a buddie.toml that does not parse: verify is left to raise, as it always did
        expected = True
    assert ctx.mandate == expected
    assert ctx.session == "s" and ctx.repos == tuple(repos)


def test_sources_keep_their_order_in_the_context(tmp_path, monkeypatch):
    repo = _repo(tmp_path, "r", '[gates]\nquotes = "off"\nprose = "off"\n[transcript]\nread = false\n')
    monkeypatch.setenv("BUDDIE_REPOS", str(repo))
    monkeypatch.setenv("BUDDIE_GATES", "prose=block")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_READ_TRANSCRIPT", "true")
    monkeypatch.delenv("BUDDIE_TRANSCRIPT", raising=False)
    ctx = resolved.resolve({"cwd": str(repo)})
    assert ctx.levels["quotes"] == config.Setting("off", Source.REPO)
    assert ctx.levels["prose"] == config.Setting("block", Source.USER)
    assert ctx.transcript == config.Setting("on", Source.USER)


def test_building_the_context_opens_no_connection(tmp_path, monkeypatch):
    repo = _repo(tmp_path, "r", '[gates]\nquotes = "warn"\n')
    monkeypatch.setenv("BUDDIE_REPOS", str(repo))
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("a connection"))
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("a connection"))
    assert resolved.resolve({"cwd": str(repo)}).config == {"gates": {"quotes": "warn"}}


@pytest.fixture
def counted(tmp_path, monkeypatch):
    """A Stop in a git repo with buddie.toml, the repo found from cwd (no BUDDIE_REPOS): git calls and buddie.toml
    reads counted."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "data.txt").write_bytes(b"hello\n")
    (repo / "NEXT.md").write_text(gs.QUEUE, encoding="utf-8")
    (repo / "buddie.toml").write_text('[gates]\nprose = "warn"\n[mandate]\nfinal_mark = "Done"\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for k in ("BUDDIE_REPOS", "BUDDIE_FINAL", "BUDDIE_GATES", "BUDDIE_TRANSCRIPT"):
        monkeypatch.delenv(k, raising=False)
    for k, v in (("BUDDIE_FETCH", "0"), ("BUDDIE_GITHUB", "0"), ("BUDDIE_LOG", str(tmp_path / "h.jsonl")),
                 ("BUDDIE_STATE", str(tmp_path / "p")), ("VERBATIM_STORE", str(tmp_path / "s")),
                 ("BUDDIE_SHARED_LOG", "0"), ("BUDDIE_INTRO", "0")):
        monkeypatch.setenv(k, v)
    calls = {"git": [], "toml": 0, "resolve": 0}
    real_run, real_read, real_resolve = subprocess.run, Path.read_text, resolved.resolve

    def run(cmd, *a, **k):
        if isinstance(cmd, list) and cmd and Path(str(cmd[0])).stem == "git":
            calls["git"].append(cmd[3] if len(cmd) > 3 else cmd[1])
        return real_run(cmd, *a, **k)

    def read_text(self, *a, **k):
        calls["toml"] += self.name == "buddie.toml"
        return real_read(self, *a, **k)

    def resolve(*a, **k):
        calls["resolve"] += 1
        return real_resolve(*a, **k)
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(resolved, "resolve", resolve)
    monkeypatch.setattr(config, "of_event", lambda e: pytest.fail("config.of_event on the hook's main path"))
    return repo, calls


@pytest.mark.parametrize("text, code", [(f"Done. `⚓ data.txt#{hashlib.sha256(b'hello' + bytes([10])).hexdigest()[:12]}`", 0),
                                        (f"Done. `⚓ data.txt#{'0' * 12}`", 2)])
def test_one_resolution_one_read_per_stop(counted, text, code):
    repo, calls = counted
    got = hook.run({"hook_event_name": "Stop", "session_id": "s", "cwd": str(repo), "last_assistant_message": text},
                   io.StringIO(), io.StringIO())
    assert got == code
    # before #27: 8 git calls and 6 reads of buddie.toml on the pass, 6 and 4 on the fail
    assert calls["resolve"] == 1 and calls["toml"] == 1
    assert calls["git"].count("rev-parse") == 1 and len(calls["git"]) <= 3  # + the session's stores: status, merge-base
