"""MCP over stdio is newline-delimited JSON-RPC in UTF-8, whatever the code page of the machine the server runs on.

2.0.0 read sys.stdin, which decodes with the locale's encoding: on Windows with a cp1251 or cp1252 code page a report's
⚓, «» and Cyrillic arrived garbled, and a false `pr:` anchor came out as a line with counts and no anchor instead of a
checked anchor (docs/distribution.md, Windows input encoding). PYTHONIOENCODING=cp1251 gives a child Python the same
stdin on every OS, so the launcher tests below reproduce that machine on Linux and macOS too."""
import io
import json
import os
import subprocess
import sys
from pathlib import Path

from buddie import mcp

ROOT = Path(__file__).resolve().parents[1]
REPORT = "Тест: PR слит. ⚓ `pr:octo/app#54=merged`\n\nОн сказал «привет» 3 раза."
CALL = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "verify_report", "arguments": {"text": REPORT, "github": False, "fetch": False}}}
LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


def _line(msg) -> bytes:
    return (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")


def _serve_bytes(data: bytes) -> list[dict]:
    """The server as a client sees it: bytes in on stdin, one JSON reply per line out."""
    out = io.StringIO()
    assert mcp.serve(io.BytesIO(data), out) == 0
    return [json.loads(line) for line in out.getvalue().splitlines()]


def _predicate(reply: dict) -> dict:
    content = reply["result"]["structuredContent"]
    return content.get("predicate", content)


def _assert_read_as_written(pred: dict):
    # the anchor is recognized as one, and the line with a count comes back character for character
    assert [(a["anchor"], a["kind"]) for a in pred["anchors"]] == [("pr:octo/app#54=merged", "pr")]
    assert pred["unanchored"] == ["line 3: Он сказал «привет» 3 раза."]


def test_utf8_bytes_are_read_as_utf8():
    listed, called = _serve_bytes(_line(LIST) + _line(CALL))
    assert listed["id"] == 1 and called["id"] == 2
    _assert_read_as_written(_predicate(called))


def test_a_line_that_is_not_utf8_is_a_parse_error_and_the_server_goes_on():
    bad = "Он сказал".encode("cp1251")  # a client that wrote the locale's bytes: not UTF-8
    data = b'{"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"text": "' + bad + b'"}}\n'
    error, called = _serve_bytes(data + _line(CALL))
    assert error["id"] is None and error["error"]["code"] == -32700 and "UTF-8" in error["error"]["message"]
    _assert_read_as_written(_predicate(called))


def test_eof_blank_lines_crlf_and_a_last_line_without_newline():
    assert _serve_bytes(b"") == []
    assert _serve_bytes(b"\n\r\n  \n") == []
    listed, called = _serve_bytes(_line(LIST).replace(b"\n", b"\r\n") + _line(CALL).rstrip(b"\n"))
    assert listed["id"] == 1
    _assert_read_as_written(_predicate(called))


def test_text_streams_given_by_a_caller_still_work():
    out = io.StringIO()
    mcp.serve(io.StringIO(json.dumps(CALL, ensure_ascii=False) + "\n"), out)
    _assert_read_as_written(_predicate(json.loads(out.getvalue())))


def _launch(data: bytes, encoding: str) -> list[dict]:
    """run.py serve as a client starts it, with stdin decoded as `encoding` by default (Windows' cp1251 here)."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    env.update(PYTHONIOENCODING=encoding, PYTHONUTF8="0")
    out = subprocess.run([sys.executable, str(ROOT / "run.py"), "serve"], input=data, capture_output=True, env=env,
                         timeout=120)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    return [json.loads(line) for line in out.stdout.decode("utf-8").splitlines()]


def test_the_server_reads_utf8_on_a_cp1251_machine():
    listed, called = _launch(_line(LIST) + _line(CALL), "cp1251")
    assert [t["name"] for t in listed["result"]["tools"]] == [t["name"] for t in mcp.TOOLS]
    _assert_read_as_written(_predicate(called))


def test_the_server_reads_utf8_on_a_utf8_machine():
    _, called = _launch(_line(LIST) + _line(CALL), "utf-8")
    _assert_read_as_written(_predicate(called))
