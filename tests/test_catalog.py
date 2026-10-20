"""What the plugin directory and a fresh user see (1.1): transcript switch, the Stop text, the token, status, commands
and the listing fields."""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from buddie import cli, config, effects, hook

ROOT = Path(__file__).resolve().parents[1]
RUN_ANCHOR = "Tests pass. ⚓ `run:pytest -q => 41 passed`"


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    for k in ("BUDDIE_FINAL", "BUDDIE_GATES", "BUDDIE_TRANSCRIPT", "CLAUDE_PLUGIN_OPTION_READ_TRANSCRIPT"):
        monkeypatch.delenv(k, raising=False)
    for k, v in (("BUDDIE_FETCH", "0"), ("BUDDIE_GITHUB", "0"), ("BUDDIE_LOG", str(tmp_path / "hook.jsonl")),
                 ("BUDDIE_STATE", str(tmp_path / "pending")), ("BUDDIE_REPOS", str(tmp_path)),
                 ("VERBATIM_STORE", str(tmp_path / "store"))):
        monkeypatch.setenv(k, v)
    return tmp_path


def transcript(path: Path, text: str) -> str:
    rows = [{"type": "user", "message": {"content": "go"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}]
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return str(path)


def stop(tmp_path, *, message=None, log_text=None) -> tuple[int, str]:
    event = {"hook_event_name": "Stop", "session_id": "s", "cwd": str(tmp_path)}
    if log_text is not None:
        event["transcript_path"] = transcript(tmp_path / "t.jsonl", log_text)
    if message is not None:
        event["last_assistant_message"] = message
    err = io.StringIO()
    return hook.run(event, err, io.StringIO()), err.getvalue()


def test_reads_transcript_sources(monkeypatch):
    assert config.reads_transcript({}) is True
    assert config.reads_transcript({"transcript": {"read": False}}) is False
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_READ_TRANSCRIPT", "false")
    assert config.reads_transcript({}) is False
    monkeypatch.setenv("BUDDIE_TRANSCRIPT", "1")  # the env var wins over the plugin option and the file
    assert config.reads_transcript({"transcript": {"read": False}}) is True


def test_stop_text_prefers_the_event_message(tmp_path):
    log = transcript(tmp_path / "t.jsonl", "an older answer the log still ends with")
    assert hook.stop_text({"transcript_path": log, "last_assistant_message": "the answer just sent"}) == "the answer just sent"
    assert hook.stop_text({"transcript_path": log, "last_assistant_message": "  "}).startswith("an older answer")


def test_a_run_anchor_with_transcript_off_is_unchecked_not_broken(fresh, monkeypatch):
    # the log shows no such run: read, the anchor is BROKEN and goes back
    code, err = stop(fresh, message=RUN_ANCHOR, log_text="hello")
    assert code == 2 and "run:pytest -q" in err
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_READ_TRANSCRIPT", "false")
    assert stop(fresh, message=RUN_ANCHOR, log_text="hello") == (0, "")
    entry = json.loads((fresh / "hook.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert entry["effects"] == {"run:UNCHECKABLE": 1} and entry["exit"] == 0


def test_an_ambient_github_token_is_never_sent(monkeypatch):
    seen = []

    def fake(req, timeout=None):
        seen.append(dict(req.header_items()))
        raise urllib.error.HTTPError(req.full_url, 404, "nope", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    for k in ("BUDDIE_GITHUB_TOKEN", "CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_ambient")
    assert effects.github_get("/repos/o/r/pulls/1") is None
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN", "ghp_given")
    effects.github_get("/repos/o/r/pulls/1")
    assert "Authorization" not in seen[0] and seen[1]["Authorization"] == "Bearer ghp_given"


def test_status_tells_a_fresh_install_from_a_configured_project(fresh, monkeypatch, capsys):
    monkeypatch.chdir(fresh)
    (fresh / "README.md").write_text("hi\n", encoding="utf-8")
    stop(fresh, message="Done. ⚓ `README.md#" + "0" * 64 + "`")  # the hash does not match: returned
    assert cli.main(["status", "--repo", str(fresh)]) == 0
    out = capsys.readouterr().out
    assert "no buddie.toml (fresh-install defaults)" in out and "final=off" in out and "1 returned" in out
    (fresh / "buddie.toml").write_text(config.TEMPLATE, encoding="utf-8")
    assert cli.main(["status", "--repo", str(fresh)]) == 0
    out = capsys.readouterr().out
    assert "config: " + str(fresh / "buddie.toml") in out and "intro mode: 0 of 20" in out and "final=block" in out


def test_commands_and_listing_fields():
    for name in ("check", "status", "init"):
        head = (ROOT / "commands" / f"{name}.md").read_text(encoding="utf-8").split("---")[1]
        assert "description:" in head
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert (ROOT / manifest["icon"]).is_file()
    assert all(manifest[k].startswith("https://") for k in ("documentationUrl", "supportUrl", "privacyPolicyUrl"))
    assert {"github_token", "read_transcript"} <= set(manifest["userConfig"])
    assert manifest["userConfig"]["github_token"]["sensitive"] is True


def test_plugin_files_install_nothing_unpinned():
    """The directory flags download-and-run commands; skills, commands and hooks are what an installed plugin runs or
    tells Claude to run. A pip install there names one exact release, and that release is this one."""
    import re
    from buddie import __version__
    pin = re.compile(r"pip install[^\n`]*?\bbuddie==([\d.]+)")
    for path in [*(ROOT / "skills").rglob("*.md"), *(ROOT / "commands").glob("*.md"), *(ROOT / "hooks").iterdir()]:
        text = path.read_text(encoding="utf-8")
        assert "git+https" not in text and not re.search(r"\b(?:npx|uvx|pipx run)\b", text), path
        for line in re.findall(r"pip install[^\n`]*", text):
            assert pin.search(line) and pin.search(line).group(1) == __version__, (path, line)
