"""buddie 0.8 (NEXT №93, audit/20 §3.2–3.3, §5.1): levels per class of claims, `buddie init` and the intro mode, the
hook launcher on every OS, and a smoke run of the hook on recorded-shape events."""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from buddie import cli, config, hook

ROOT = Path(__file__).resolve().parents[1]
EVENTS = Path(__file__).resolve().parent / "events"
BARE = "Done: 3 of 3 tests pass.\n\nThe PR is merged."


@pytest.fixture
def plain(tmp_path, monkeypatch):
    """The plugin's defaults: no project mark, no lab gates, a repo dir of its own."""
    for k in ("BUDDIE_FINAL", "BUDDIE_GATES"):
        monkeypatch.delenv(k, raising=False)
    for k, v in (("BUDDIE_FETCH", "0"), ("BUDDIE_GITHUB", "0"), ("BUDDIE_LOG", str(tmp_path / "hook.jsonl")),
                 ("BUDDIE_STATE", str(tmp_path / "pending")), ("BUDDIE_REPOS", str(tmp_path)),
                 ("VERBATIM_STORE", str(tmp_path / "store"))):
        monkeypatch.setenv(k, v)
    return tmp_path


def _stop(tmp_path, answer):
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": answer}]}}),
                 encoding="utf-8")
    event = {"hook_event_name": "Stop", "session_id": "s", "cwd": str(tmp_path), "transcript_path": str(t)}
    err, out = io.StringIO(), io.StringIO()
    code = hook.run(event, err, out)
    return code, err.getvalue(), out.getvalue()


def test_classes_of_blocking_items():
    assert config.classify("quote q1 not found in https://x.org: “a”") == "quotes"
    assert config.classify("anchor line 3 ⚓ pr:o/r#1=merged: open") == "anchors"
    assert config.classify("final answer has no anchor: anchor its result") == "final"
    assert config.classify("number without anchor, line 2: 3 of 4") == "final"
    assert config.classify("number n1 “40%” not found in https://x.org") == "numbers"
    assert config.classify("work claimed in prose, line 1: “merged”") == "prose"
    assert config.classify("done line 4: no anchor") == "work"
    assert config.classify("context: 250000 tokens") is None


def test_levels_file_then_env(monkeypatch):
    monkeypatch.delenv("BUDDIE_GATES", raising=False)
    assert config.levels({}) == config.DEFAULTS
    lv = config.levels({"gates": {"prose": "block", "quotes": "loud", "nope": "off"}})
    assert lv["prose"] == "block" and lv["quotes"] == "block" and "nope" not in lv
    monkeypatch.setenv("BUDDIE_GATES", "prose=off, numbers=block")
    lv = config.levels({"gates": {"prose": "block"}})
    assert lv["prose"] == "off" and lv["numbers"] == "block"


def test_default_prose_warns_and_final_blocks(plain):
    code, err, out = _stop(plain, BARE)
    assert code == 2 and "final answer has no anchor" in err and "work claimed in prose" not in err
    anchored = "Done `⚓ build=ok`.\n\nThe PR is merged."
    code, err, out = _stop(plain, anchored)
    assert code == 0 and err == ""
    msg = json.loads(out)["systemMessage"]
    assert msg.startswith("buddie warns:") and "work claimed in prose, line 3" in msg


def test_levels_from_buddie_toml(plain):
    (plain / "buddie.toml").write_text('[gates]\nfinal = "off"\nprose = "block"\n', encoding="utf-8")
    code, err, _ = _stop(plain, BARE)
    assert code == 2 and "work claimed in prose" in err and "final answer has no anchor" not in err
    (plain / "buddie.toml").write_text('[gates]\nfinal = "off"\nprose = "off"\n', encoding="utf-8")
    assert _stop(plain, BARE) == (0, "", "")


def test_init_writes_defaults_and_intro_warns_until_n_finals(plain, monkeypatch, capsys):
    monkeypatch.chdir(plain)
    assert cli.main(["init", "--repo", str(plain)]) == 0
    assert cli.main(["init", "--repo", str(plain)]) == 1  # never overwritten
    cfg = config.load(plain / "buddie.toml")
    assert config.levels(cfg) == config.DEFAULTS and cfg["intro"]["finals"] == config.INIT_FINALS
    (plain / "buddie.toml").write_text(config.TEMPLATE.replace(f"finals = {config.INIT_FINALS}", "finals = 2"),
                                       encoding="utf-8")
    code, err, out = _stop(plain, BARE)
    msg = json.loads(out)["systemMessage"]
    assert code == 0 and err == "" and "intro, final 1 of 2" in msg and "final answer has no anchor" in msg
    assert "buddie intro --false" in msg
    assert cli.main(["intro", "--false", "--repo", str(plain)]) == 0  # a false return restarts the count
    assert "0 of 2" in capsys.readouterr().out
    assert _stop(plain, BARE)[0] == 0
    assert _stop(plain, BARE)[0] == 0
    code, err, _ = _stop(plain, BARE)  # the third final after the reset: the intro is over
    assert code == 2 and "final answer has no anchor" in err
    log = [json.loads(x) for x in (plain / "hook.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [e.get("intro", {}).get("seen") for e in log] == [1, 1, 2, None]


def test_enforce_ends_the_intro(plain, monkeypatch):
    monkeypatch.chdir(plain)
    assert cli.main(["init", "--repo", str(plain)]) == 0
    assert _stop(plain, BARE)[0] == 0
    assert cli.main(["enforce", "--repo", str(plain)]) == 0
    assert _stop(plain, BARE)[0] == 2


def test_summary_and_promises_are_off_by_default(plain, monkeypatch):
    from buddie import promises, summary
    calls = []
    monkeypatch.setattr(summary, "on_stop", lambda e: calls.append("summary") or "Summary first")
    monkeypatch.setattr(promises, "on_stop", lambda e: calls.append("promises") or None)
    ok = "Done `⚓ build=ok`."
    assert _stop(plain, ok)[0] == 0 and calls == []
    monkeypatch.setenv("BUDDIE_GATES", "summary=block,promises=warn")
    code, err, _ = _stop(plain, ok)
    assert code == 2 and "Summary first" in err and calls == ["summary", "promises"]


def test_hooks_run_through_the_launcher():
    cfg = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    commands = [h["command"] for groups in cfg["hooks"].values() for g in groups for h in g["hooks"]]
    assert commands and all(c == 'sh "${CLAUDE_PLUGIN_ROOT}/hooks/run.sh" hook' for c in commands)


def _launchers():
    out = []
    if shutil.which("sh"):
        out.append(["sh", (ROOT / "hooks" / "run.sh").as_posix(), "hook"])
    if shutil.which("buddie"):  # the clean install of CI (pip install of the public tree)
        out.append([shutil.which("buddie"), "hook"])
    return out or [[sys.executable, str(ROOT / "run.py"), "hook"]]


def _event(name, transcript, cwd):
    raw = (EVENTS / name).read_text(encoding="utf-8")
    raw = raw.replace("{transcript}", (EVENTS / transcript).as_posix()).replace("{cwd}", Path(cwd).as_posix())
    return raw.encode("utf-8")


@pytest.mark.parametrize("launcher", _launchers(), ids=lambda c: Path(c[0]).stem + "-" + Path(c[-2]).name)
def test_smoke_on_recorded_events(launcher, tmp_path):
    """The hook as Claude Code runs it, on every OS of CI: a bare Stop goes back, an anchored one passes, a
    PreToolUse with a run: anchor the session does not show goes back, and after `buddie init` nothing goes back."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BUDDIE_", "VERBATIM_"))}
    env.update(BUDDIE_LOG=str(tmp_path / "hook.jsonl"), BUDDIE_STATE=str(tmp_path / "pending"),
               BUDDIE_INTRO=str(tmp_path / "intro.json"), BUDDIE_SHARED_LOG="0", BUDDIE_GITHUB="0",
               BUDDIE_FETCH="0", BUDDIE_REPOS=str(tmp_path), VERBATIM_STORE=str(tmp_path / "store"))

    def hook_run(name, transcript):
        p = subprocess.run(launcher, input=_event(name, transcript, tmp_path), capture_output=True, env=env,
                           cwd=tmp_path, timeout=120)
        return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")

    code, _, err = hook_run("stop.json", "transcript.jsonl")
    assert code == 2 and "final answer has no anchor" in err and "⚓ run:python -m pytest -q => 3 passed" in err
    assert hook_run("stop.json", "transcript-anchored.jsonl")[0] == 0
    code, _, err = hook_run("pretooluse.json", "transcript.jsonl")
    assert code == 2 and "anchor line 1" in err
    (tmp_path / "buddie.toml").write_text(config.TEMPLATE, encoding="utf-8")
    code, out, err = hook_run("stop.json", "transcript.jsonl")
    assert code == 0 and "intro, final 1 of" in json.loads(out)["systemMessage"]
