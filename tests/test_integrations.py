"""PR #32: the existing integrations, as their manifests start them. Each test reads the shipped configuration file
and checks the behaviour it leads to, so a manifest change cannot quietly undo a guarantee of buddie's code."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _env_of(server: dict, user_config: dict) -> dict:
    """The environment a manifest gives its MCP server, with ${user_config.X} filled in as the host would."""
    out = {}
    for k, v in (server.get("env") or {}).items():
        for name, value in user_config.items():
            v = v.replace("${user_config.%s}" % name, value)
        out[k] = v
    return out


class Recorder(BaseHTTPRequestHandler):
    seen: list = []

    def do_GET(self):  # noqa: N802 - http.server's name
        self.seen.append(self.headers.get("Authorization"))
        body = b'{"state": "open", "head": {"sha": "abc"}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def agent_api():
    handler = type("H", (Recorder,), {"seen": []})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", handler.seen
    srv.shutdown()
    srv.server_close()


def test_the_claude_code_mcp_server_does_not_send_the_plugins_token_where_the_environment_points(agent_api):
    """The plugin's token setting is the person's. .mcp.json hands it to the MCP server; an API named in the
    environment (which a project's settings can set) must not receive it, as the hook does not send it there (#29)."""
    base, seen = agent_api
    server = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["buddie"]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BUDDIE_", "CLAUDE_PLUGIN_OPTION_"))}
    env.update(_env_of(server, {"github_token": "pers0nal-token"}), BUDDIE_GITHUB_API=base)
    code = ("import sys; sys.path.insert(0, %r); from buddie import effects; effects.github_get('/repos/o/r/pulls/1')"
            % str(ROOT))
    subprocess.run([sys.executable, "-I", "-c", code], env=env, check=True, timeout=60)
    assert seen == [None]  # asked without the token


def test_the_claude_code_mcp_server_still_sends_the_plugins_token_to_github(monkeypatch):
    import io
    import urllib.request

    from buddie import effects
    server = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["buddie"]
    for k in ("BUDDIE_GITHUB_TOKEN", "CLAUDE_PLUGIN_OPTION_GITHUB_TOKEN", "BUDDIE_GITHUB_API"):
        monkeypatch.delenv(k, raising=False)
    for k, v in _env_of(server, {"github_token": "pers0nal-token"}).items():
        monkeypatch.setenv(k, v)
    asked = []

    class Answer(io.BytesIO):
        def geturl(self):
            return effects.DEFAULT_API + "/repos/o/r/pulls/1"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: asked.append(req) or Answer(b"{}"))
    effects.github_get("/repos/o/r/pulls/1")
    assert asked[0].get_header("Authorization") == "Bearer pers0nal-token"  # api.github.com: as before


@pytest.mark.parametrize("make, why", [
    (lambda d: ((d / "adir").mkdir(), d / "adir")[1], "is a directory"),
    (lambda d: ((d / "latin.md").write_bytes(b"\xff\xfe not utf8"), d / "latin.md")[1], "not UTF-8 (byte 0)"),
])
def test_a_report_that_cannot_be_read_is_an_input_error_not_a_fail(tmp_path, capsys, make, why):
    """exit 1 is the CLI's FAIL; a report buddie cannot read is exit 2 with the reason, as a missing one always was."""
    from buddie import cli
    path = make(tmp_path)
    assert cli.main(["verify", str(path), "--no-fetch", "--no-github"]) == 2
    err = capsys.readouterr().err
    assert why in err and "Traceback" not in err
    assert cli.main(["verify", str(tmp_path / "missing.md")]) == 2  # unchanged


def test_mcp_does_not_say_pass_means_everything_holds():
    from buddie import mcp
    assert "every quote was found and every anchor holds" not in mcp.INSTRUCTIONS
    assert "does not make the report true" in mcp.INSTRUCTIONS


def test_status_names_an_active_or_invalid_policy_and_says_nothing_without_one(tmp_path, monkeypatch, capsys):
    from buddie import cli, policy
    monkeypatch.chdir(tmp_path)
    cli.main(["status"])
    assert "policy:" not in capsys.readouterr().out  # no policy file: the output is as before
    place = tmp_path / "system" / "policy.toml"
    place.parent.mkdir()
    monkeypatch.setattr(policy, "location", lambda: place)
    monkeypatch.setattr(policy, "protection_problem", lambda p: None)
    place.write_text('version = 1\n[gates]\nquotes = "block"\n', encoding="utf-8")
    cli.main(["status"])
    assert "policy: active" in capsys.readouterr().out
    place.write_text("version = 9\n", encoding="utf-8")
    cli.main(["status"])
    out = capsys.readouterr().out
    assert "policy: INVALID" in out and "unsupported version" in out and "returns each answer" in out
