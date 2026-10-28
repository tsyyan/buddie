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


def test_without_buddie_toml_only_what_is_false_goes_back(plain):
    """1.1, before the plugin directory: someone who only installed the plugin is not returned every final answer
    for having no anchor; an anchor that does not hold still goes back."""
    assert config.levels({}, configured=False) == config.ZERO_CONFIG
    assert _stop(plain, BARE) == (0, "", "")
    assert _stop(plain, "I updated the README with the install steps.") == (0, "", "")
    assert _stop(plain, "Done `⚓ build=ok`.\n\nThe PR is merged.") == (0, "", "")
    (plain / "README.md").write_text("hi\n", encoding="utf-8")
    code, err, _ = _stop(plain, "Done. ⚓ `README.md#" + "0" * 64 + "`")
    assert code == 2 and err.startswith(hook.RETURNED) and "sha256 is now" in err and hook.FIX in err
    assert hook.SHOWN in err  # a Stop's answer is already shown: only the corrections come back, not a second copy


def test_a_project_with_buddie_toml_keeps_the_full_defaults(plain):
    (plain / "buddie.toml").write_text("[journal]\ntext = false\n", encoding="utf-8")
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
    """The hook as Claude Code runs it, on every OS of CI: with no buddie.toml a bare Stop and an anchored one pass,
    a PreToolUse with a run: anchor the session does not show goes back; after `buddie init` the bare Stop would go
    back, and the intro mode turns that into a warning."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BUDDIE_", "VERBATIM_"))}
    env.update(BUDDIE_LOG=str(tmp_path / "hook.jsonl"), BUDDIE_STATE=str(tmp_path / "pending"),
               BUDDIE_INTRO=str(tmp_path / "intro.json"), BUDDIE_SHARED_LOG="0", BUDDIE_GITHUB="0",
               BUDDIE_FETCH="0", BUDDIE_REPOS=str(tmp_path), VERBATIM_STORE=str(tmp_path / "store"))

    def hook_run(name, transcript):
        p = subprocess.run(launcher, input=_event(name, transcript, tmp_path), capture_output=True, env=env,
                           cwd=tmp_path, timeout=120)
        return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")

    assert hook_run("stop.json", "transcript.jsonl")[0] == 0  # no buddie.toml: an unanchored answer is not false
    assert hook_run("stop.json", "transcript-anchored.jsonl")[0] == 0
    code, _, err = hook_run("pretooluse.json", "transcript.jsonl")
    assert code == 2 and "anchor line 1" in err and hook.SHOWN not in err  # a tool's text is resent whole
    (tmp_path / "buddie.toml").write_text(config.TEMPLATE, encoding="utf-8")
    code, out, err = hook_run("stop.json", "transcript.jsonl")
    assert code == 0 and "intro, final 1 of" in json.loads(out)["systemMessage"]


def test_without_buddie_toml_a_false_quote_goes_back(plain):
    from buddie.verbatim.store import Store
    url = "https://status.example.com/incidents/42"
    page = "<html><body>" + "<p>We saw elevated error rates on the API between 14:59 and 15:41 UTC.</p>" * 30 + "</body></html>"
    Store(plain / "store").add(url, page.encode(), content_type="text/html")
    good = f"The status page says “elevated error rates on the API between 14:59 and 15:41 UTC” ([status]({url}))."
    bad = good.replace("14:59", "14:58")
    assert _stop(plain, good)[0] == 0
    code, err, _ = _stop(plain, bad)
    assert code == 2 and err.startswith(hook.RETURNED) and "not found" in err


def test_a_disclosure_covers_a_false_quote_only_after_it_was_returned(plain, monkeypatch):
    """Eval run of 2026-10-20: an altered quote went out under a 'buddie: unverified' line written before any check."""
    from buddie.verbatim.store import Store
    url = "https://status.example.com/incidents/42"
    page = "<html><body>" + "<p>We saw elevated error rates on the API between 14:59 and 15:41 UTC.</p>" * 30 + "</body></html>"
    Store(plain / "store").add(url, page.encode(), content_type="text/html")
    bad = (f"The status page says “elevated error rates on the API between 14:58 and 15:41 UTC” ([status]({url})).\n\n"
           "buddie: unverified, I could not open the page")
    code, err, _ = _stop(plain, bad)
    assert code == 2 and "written before buddie checked it" in err
    assert _stop(plain, bad)[0] == 0  # returned once: the line now discloses what buddie found
    monkeypatch.setenv("BUDDIE_STATE", "0")  # returns not tracked: as before 1.1
    assert _stop(plain, bad.replace("status page says", "page says"))[0] == 0
