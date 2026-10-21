"""A check that could not be done is not a pass: a buddie.toml that cannot be read, an error inside the check, and
findings that do not match the receipt's items each stop an answer with the reason, once."""
from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

from buddie import cli, config, hook, mandate, resolved, verify

HELLO = hashlib.sha256(b"hello\n").hexdigest()[:12]
GOOD = f"Done. `⚓ data.txt#{HELLO}`"
BROKEN_ANCHOR = f"Done. `⚓ data.txt#{'0' * 12}`"
BAD_TOML, BAD_UTF8 = "this is [ not toml", b'[gates]\nquotes = "\xff\xfe"\n'


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k in ("BUDDIE_FINAL", "BUDDIE_GATES", "BUDDIE_TRANSCRIPT", "CLAUDE_PLUGIN_OPTION_READ_TRANSCRIPT", "BUDDIE_NUMBERS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in (("BUDDIE_FETCH", "0"), ("BUDDIE_GITHUB", "0"), ("BUDDIE_LOG", str(tmp_path / "hook.jsonl")),
                 ("BUDDIE_STATE", str(tmp_path / "pending")), ("BUDDIE_SHARED_LOG", "0"), ("BUDDIE_INTRO", "0"),
                 ("VERBATIM_STORE", str(tmp_path / "store")), ("BUDDIE_LESSONS", "0"), ("BUDDIE_PROMISES", "0")):
        monkeypatch.setenv(k, v)

    def repos(*tomls):
        out = []
        for i, t in enumerate(tomls):
            r = tmp_path / f"r{i}"
            r.mkdir()
            (r / "data.txt").write_bytes(b"hello\n")
            if t is not None:
                (r / "buddie.toml").write_bytes(t if isinstance(t, bytes) else t.encode("utf-8"))
            out.append(r)
        monkeypatch.setenv("BUDDIE_REPOS", (";" if sys.platform == "win32" else ":").join(map(str, out)))
        return out
    return tmp_path, repos


def main(event: dict, monkeypatch, capsys) -> tuple[int, str, str]:
    """The hook as Claude Code runs it: JSON on stdin, through main()."""
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(event).encode("utf-8"))))
    code = hook.main()
    got = capsys.readouterr()
    return code, got.err, got.out


def stop(repo: Path, text: str, **extra) -> dict:
    return {"hook_event_name": "Stop", "session_id": "s", "cwd": str(repo), "last_assistant_message": text, **extra}


def last_line(tmp: Path) -> dict:
    return json.loads((tmp / "hook.jsonl").read_text(encoding="utf-8").splitlines()[-1])


# --- a buddie.toml that cannot be read ----------------------------------------------------------------------------

@pytest.mark.parametrize("bad, why", [(BAD_TOML, "not valid TOML"), (BAD_UTF8, "not UTF-8")])
def test_a_broken_buddie_toml_does_not_turn_the_gate_off(env, monkeypatch, capsys, bad, why):
    tmp, repos = env
    [repo] = repos(bad)
    code, err, _ = main(stop(repo, BROKEN_ANCHOR), monkeypatch, capsys)
    assert code == 2 and "data.txt" in err  # the check ran, on buddie's defaults
    assert "buddie.toml" in err and why in err and "hook error" not in err
    code, err, _ = main(stop(repo, GOOD), monkeypatch, capsys)  # nothing false, but the config is not the project's
    assert code == 2 and why in err
    line = last_line(tmp)
    assert line["exit"] == 2 and line["config_errors"][0]["reason"].startswith(why)
    assert line["outcome"] == "PASS"  # the receipt's outcome is the checks', the return is the gate's


def test_a_read_error_is_a_config_error(env, monkeypatch, capsys):
    tmp, repos = env
    [repo] = repos('[gates]\nquotes = "warn"\n')
    real = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes",
                        lambda self: (_ for _ in ()).throw(PermissionError(13, "denied")) if self.name == "buddie.toml"
                        else real(self))
    code, err, _ = main(stop(repo, GOOD), monkeypatch, capsys)
    assert code == 2 and "cannot be read" in err and "denied" in err


def test_one_broken_file_among_several_repos(env, monkeypatch, capsys):
    tmp, repos = env
    first, second = repos('[gates]\nanchors = "warn"\nfinal = "off"\n', BAD_TOML)
    ctx = resolved.resolve({"cwd": str(first)})
    assert ctx.config == {"gates": {"anchors": "warn", "final": "off"}} and ctx.level["anchors"] == "warn"
    assert [e.path for e in ctx.config_errors] == [second / "buddie.toml"]
    code, err, _ = main(stop(first, BROKEN_ANCHOR), monkeypatch, capsys)
    assert code == 2 and str(second / "buddie.toml") in err.replace("\\\\", "\\")


def test_nothing_of_a_broken_file_is_used(env):
    _, repos = env
    [repo] = repos(b'[mandate]\nfinal_mark = "(?!)"\nask_words = "(a+)+$"\n\xff')
    ctx = resolved.resolve({"cwd": str(repo)})
    assert ctx.final_mark is None and ctx.mandate == {} and ctx.config == {}
    assert ctx.level == config.levels({}, configured=True)  # the full defaults, not the fresh-install ones
    with pytest.raises(config.ConfigError, match="not UTF-8"):
        mandate.load_config(repo)


def test_the_return_does_not_loop_and_a_disclosure_passes(env, monkeypatch, capsys):
    tmp, repos = env
    [repo] = repos(BAD_TOML)
    assert main(stop(repo, GOOD, stop_hook_active=True), monkeypatch, capsys)[0] == 0
    text = GOOD + "\nbuddie: the project's buddie.toml is broken, so its own settings were not applied."
    assert main(stop(repo, text), monkeypatch, capsys)[0] == 2  # written before buddie said anything
    assert main(stop(repo, text), monkeypatch, capsys)[0] == 0  # after the return


def test_fixing_the_file_ends_the_return(env, monkeypatch, capsys):
    tmp, repos = env
    [repo] = repos(BAD_TOML)
    assert main(stop(repo, GOOD), monkeypatch, capsys)[0] == 2
    (repo / "buddie.toml").write_text('[gates]\nfinal = "off"\n', encoding="utf-8")
    code, err, _ = main(stop(repo, GOOD), monkeypatch, capsys)
    assert (code, err) == (0, "") and "config_errors" not in last_line(tmp)


def test_events_without_text_pass_with_a_broken_file(env, monkeypatch, capsys):
    tmp, repos = env
    [repo] = repos(BAD_TOML)
    for event in ({"hook_event_name": "SessionStart", "session_id": "s", "cwd": str(repo)},
                  {"hook_event_name": "PostToolUse", "session_id": "s", "cwd": str(repo), "tool_name": "Read"},
                  {"hook_event_name": "SubagentStart", "session_id": "s", "cwd": str(repo), "agent_id": "a"},
                  stop(repo, "   ")):
        assert main(event, monkeypatch, capsys)[0] == 0, event["hook_event_name"]


def test_cli_status_says_the_file_is_broken(env, capsys):
    _, repos = env
    [repo] = repos(BAD_TOML)
    assert cli.main(["status", "--repo", str(repo)]) == 0
    assert "cannot be read" in capsys.readouterr().out


# --- an error inside the check ------------------------------------------------------------------------------------

def _explode(*a, **k):
    raise RuntimeError("the checker broke")


def test_an_error_in_the_check_returns_the_answer_once(env, monkeypatch, capsys):
    tmp, repos = env
    [repo] = repos(None)
    monkeypatch.setattr(verify, "assess", _explode)
    code, err, _ = main(stop(repo, GOOD), monkeypatch, capsys)
    assert code == 2 and "could not check" in err and "RuntimeError: the checker broke" in err
    assert main(stop(repo, GOOD, stop_hook_active=True), monkeypatch, capsys)[0] == 0  # re-entered: no loop
    sent = {"hook_event_name": "PreToolUse", "session_id": "s", "cwd": str(repo), "tool_name": "mcp__x__send_message",
            "tool_input": {"text": GOOD}}
    assert main(sent, monkeypatch, capsys)[0] == 2  # a text tool's message is held the same way
    assert main(stop(repo, GOOD + "\nbuddie: not checked, buddie failed."), monkeypatch, capsys)[0] == 0
    assert main(stop(repo, "  "), monkeypatch, capsys)[0] == 0  # nothing to check


def test_an_error_elsewhere_does_not_block(env, monkeypatch, capsys):
    _, repos = env
    [repo] = repos(None)
    monkeypatch.setattr(hook, "session_start", _explode)
    code, err, _ = main({"hook_event_name": "SessionStart", "session_id": "s", "cwd": str(repo)}, monkeypatch, capsys)
    assert code == 0 and "RuntimeError" in err


# --- findings that do not match the receipt's items --------------------------------------------------------------

def test_a_mismatch_blocks_every_item_and_is_journaled(env, monkeypatch, capsys):
    tmp, repos = env
    [repo] = repos(None)
    monkeypatch.setenv("BUDDIE_GATES", "anchors=warn")
    assert main(stop(repo, BROKEN_ANCHOR), monkeypatch, capsys)[0] == 0  # matched: the level says warn
    monkeypatch.setattr(verify, "blocking_findings", lambda found, numbers="gap": [])
    code, err, _ = main(stop(repo, BROKEN_ANCHOR), monkeypatch, capsys)
    assert code == 2 and "data.txt" in err  # no item lost, none demoted by a level
    assert last_line(tmp)["typed_mismatch"] == {"findings": 0, "items": 1}
    items, mismatch = hook.gate_items({"blocking": ["anchor line 1 ⚓ x: y"]}, [], "gap")
    assert items == [("anchor line 1 ⚓ x: y", None)] and mismatch == {"findings": 0, "items": 1}


# --- a 'buddie:' line written before buddie said anything does not release an unchecked text ---------------------

PRE = "\nbuddie: some things here may be unchecked."


def journal(tmp: Path) -> list[dict]:
    return [json.loads(x) for x in (tmp / "hook.jsonl").read_text(encoding="utf-8").splitlines()]


def test_a_pre_written_disclosure_does_not_pass_a_broken_toml(env, monkeypatch, capsys):
    tmp, repos = env
    [repo] = repos(BAD_TOML)
    code, err, _ = main(stop(repo, GOOD + PRE), monkeypatch, capsys)
    assert code == 2 and "written before buddie checked it" in err
    # after the return, the same line is a disclosure the model wrote knowing: it passes
    assert main(stop(repo, GOOD + PRE), monkeypatch, capsys)[0] == 0


def test_a_pre_written_disclosure_does_not_pass_a_checker_error(env, monkeypatch, capsys):
    tmp, repos = env
    [repo] = repos(None)
    monkeypatch.setattr(verify, "assess", _explode)
    code, err, _ = main(stop(repo, GOOD + PRE), monkeypatch, capsys)
    assert code == 2 and "could not check" in err
    assert journal(tmp)[-1]["status"] == "internal_error"
    code, err, _ = main(stop(repo, GOOD + PRE), monkeypatch, capsys)  # now after a return
    assert code == 0 and journal(tmp)[-1]["status"] == "unchecked_disclosed"
    assert not any(line.get("outcome") == "PASS" for line in journal(tmp))


def test_a_pre_written_disclosure_does_not_pass_a_typed_mismatch(env, monkeypatch, capsys):
    tmp, repos = env
    [repo] = repos(None)
    monkeypatch.setattr(verify, "blocking_findings", lambda found, numbers="gap": [])
    code, err, _ = main(stop(repo, BROKEN_ANCHOR + PRE), monkeypatch, capsys)
    assert code == 2 and "written before buddie checked it" in err


def test_a_re_entered_stop_after_an_error_tells_the_person(env, monkeypatch, capsys):
    """Claude Code re-enters Stop (stop_hook_active) after a return; buddie never blocks there, so the loop ends.
    After an error return the answer that follows was not checked either: the person is told (systemMessage, which
    the agent does not write) and the journal says unchecked, never PASS."""
    tmp, repos = env
    [repo] = repos(None)
    monkeypatch.setattr(verify, "assess", _explode)
    assert main(stop(repo, GOOD), monkeypatch, capsys)[0] == 2
    code, err, out = main(stop(repo, GOOD, stop_hook_active=True), monkeypatch, capsys)
    assert code == 0 and "not checked" in json.loads(out)["systemMessage"]
    line = journal(tmp)[-1]
    assert (line["status"], line["by"]) == ("unchecked_disclosed", "buddie") and "outcome" not in line
    code, _, out = main(stop(repo, GOOD, stop_hook_active=True), monkeypatch, capsys)
    assert code == 0  # however many re-entries: never a block


def test_a_re_entered_stop_after_a_broken_toml_tells_the_person(env, monkeypatch, capsys):
    tmp, repos = env
    [repo] = repos(BAD_TOML)
    assert main(stop(repo, GOOD), monkeypatch, capsys)[0] == 2
    code, _, out = main(stop(repo, GOOD, stop_hook_active=True), monkeypatch, capsys)
    assert code == 0 and "buddie.toml" in json.loads(out)["systemMessage"]


def test_a_re_entered_stop_after_an_ordinary_return_is_unchanged(env, monkeypatch, capsys):
    tmp, repos = env
    [repo] = repos(None)
    assert main(stop(repo, BROKEN_ANCHOR), monkeypatch, capsys)[0] == 2
    assert main(stop(repo, GOOD, stop_hook_active=True), monkeypatch, capsys) == (0, "", "")


def test_recovery_between_attempts_is_checked_normally(env, monkeypatch, capsys):
    tmp, repos = env
    [repo] = repos(None)
    monkeypatch.setattr(verify, "assess", _explode)
    assert main(stop(repo, GOOD + PRE), monkeypatch, capsys)[0] == 2
    monkeypatch.undo()  # the checker works again; undo also dropped the fixture's environment, set it back
    for k, v in (("BUDDIE_FETCH", "0"), ("BUDDIE_GITHUB", "0"), ("BUDDIE_LOG", str(tmp / "hook.jsonl")),
                 ("BUDDIE_STATE", str(tmp / "pending")), ("BUDDIE_SHARED_LOG", "0"), ("BUDDIE_INTRO", "0"),
                 ("VERBATIM_STORE", str(tmp / "store")), ("BUDDIE_REPOS", str(repo)), ("BUDDIE_PROMISES", "0")):
        monkeypatch.setenv(k, v)
    code, _, _ = main(stop(repo, BROKEN_ANCHOR + PRE), monkeypatch, capsys)  # the check runs: the anchor is false
    assert code == 0 and journal(tmp)[-1]["outcome"] == "FAIL"  # a disclosure after a return, as always
    assert main(stop(repo, GOOD), monkeypatch, capsys)[0] == 0 and journal(tmp)[-1]["outcome"] == "PASS"


def test_an_ordinary_disclosure_after_a_false_quote_still_passes(env, monkeypatch, capsys):
    tmp, repos = env
    [repo] = repos(None)
    assert main(stop(repo, BROKEN_ANCHOR), monkeypatch, capsys)[0] == 2
    assert main(stop(repo, BROKEN_ANCHOR + "\nbuddie: the anchor is stale."), monkeypatch, capsys)[0] == 0


def test_a_text_tool_after_an_error(env, monkeypatch, capsys):
    tmp, repos = env
    [repo] = repos(None)
    monkeypatch.setattr(verify, "assess", _explode)
    sent = {"hook_event_name": "PreToolUse", "session_id": "s", "cwd": str(repo), "tool_name": "mcp__x__send_message",
            "tool_input": {"text": GOOD + PRE}}
    assert main(sent, monkeypatch, capsys)[0] == 2  # pre-written: held
    assert main(sent, monkeypatch, capsys)[0] == 0  # after the return: let out, unchecked and disclosed
    assert journal(tmp)[-1]["status"] == "unchecked_disclosed"


def test_without_return_state_an_error_is_always_held(env, monkeypatch, capsys):
    """BUDDIE_STATE=0: buddie cannot tell a line written after its return, so no line releases an unchecked text;
    only the re-entered Stop ends it, with the person told."""
    tmp, repos = env
    [repo] = repos(None)
    monkeypatch.setenv("BUDDIE_STATE", "0")
    monkeypatch.setattr(verify, "assess", _explode)
    assert main(stop(repo, GOOD + PRE), monkeypatch, capsys)[0] == 2
    assert main(stop(repo, GOOD + PRE), monkeypatch, capsys)[0] == 2
    assert main(stop(repo, GOOD, stop_hook_active=True), monkeypatch, capsys)[0] == 0
