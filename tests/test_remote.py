"""The remote MCP server (buddie/remote.py): Streamable HTTP, the narrower tool set, the fetch guard."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from buddie import remote


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("VERBATIM_STORE", str(tmp_path / "store"))
    servers = []

    def start(**kwargs):
        s = remote.make_server("127.0.0.1", 0, **{"token": "", "origins": [], **kwargs})
        threading.Thread(target=s.serve_forever, daemon=True).start()
        servers.append(s)
        return f"http://127.0.0.1:{s.server_port}"

    yield start
    for s in servers:
        s.shutdown()
        s.server_close()
    urllib.request.install_opener(None)


def call(base, body, headers=None, method="POST", path="/mcp"):
    """(status, headers, parsed body) through a plain opener: the test talks to 127.0.0.1, which the guard refuses."""
    data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    plain = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with plain.open(req, timeout=20) as r:
            raw = r.read()
            return r.status, r.headers, json.loads(raw) if raw and r.headers.get_content_type() == "application/json" else raw
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, e.headers, json.loads(raw) if raw else None


def rpc(method, params=None, mid=1):
    return {"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}


def test_initialize_and_the_remote_tool_set(server):
    base = server()
    status, _, body = call(base, rpc("initialize", {"protocolVersion": "2025-06-18"}))
    assert status == 200 and body["result"]["protocolVersion"] == "2025-06-18"
    _, _, body = call(base, rpc("tools/list"))
    tools = {t["name"]: t for t in body["result"]["tools"]}
    assert set(tools) == {"verify_report", "snap", "source_text"}
    props = tools["verify_report"]["inputSchema"]["properties"]
    assert not {"path", "repos", "store", "transcript", "access"} & set(props)
    assert tools["verify_report"]["inputSchema"]["required"] == ["text"]
    assert all(t["annotations"]["readOnlyHint"] and not t["annotations"]["destructiveHint"] for t in tools.values())


def test_verify_report_over_http(server):
    base = server()
    report = "Done. ⚓ `README.md#0000000000000000000000000000000000000000000000000000000000000000`\n"
    _, _, body = call(base, rpc("tools/call", {"name": "verify_report",
                                               "arguments": {"text": report, "fetch": False, "github": False}}))
    result = body["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["predicate"]["outcome"] == "GAPS"  # no repos on the server: UNCHECKABLE


@pytest.mark.parametrize("name,arguments,needle", [
    ("verify_report", {"path": "/etc/passwd"}, "path"),
    ("verify_report", {"text": "x", "repos": ["/"]}, "repos"),
    ("verify_report", {"text": "x", "transcript": "/root/.claude/x.jsonl"}, "transcript"),
    ("snap", {"urls": ["file:///etc/passwd"]}, "only http and https"),
    ("snap", {"urls": ["http://example.com:22/"]}, "port 22"),
    ("snap", {"urls": ["https://example.com/"], "store": "/tmp"}, "store"),
    ("source_text", {"ref": "x", "store": "/"}, "store"),
])
def test_refused_arguments_are_tool_errors(server, name, arguments, needle):
    _, _, body = call(server(), rpc("tools/call", {"name": name, "arguments": arguments}))
    assert body["result"]["isError"] is True and needle in body["result"]["structuredContent"]["error"]


def test_summary_is_not_offered(server):
    _, _, body = call(server(), rpc("tools/call", {"name": "summary", "arguments": {}}))
    assert body["error"]["code"] == -32602


def test_http_edges(server):
    base = server()
    assert call(base, {"jsonrpc": "2.0", "method": "notifications/initialized"})[0] == 202
    assert call(base, None, method="GET")[0] == 405
    assert call(base, None, method="GET", path="/healthz")[2]["ok"] is True
    assert call(base, [rpc("ping")])[0] == 400
    assert call(base, b"{nope")[2]["error"]["code"] == -32700
    assert call(base, rpc("ping"), path="/other")[0] == 404


def test_token_origin_and_size(server):
    base = server(token="s3cret", origins=["https://chatgpt.com"], max_bytes=200)
    assert call(base, rpc("ping"))[0] == 401
    assert call(base, rpc("ping"), {"Authorization": "Bearer s3cret"})[0] == 200
    assert call(base, rpc("ping"), {"Authorization": "Bearer s3cret", "Origin": "https://evil.example"})[0] == 403
    assert call(base, rpc("ping"), {"Authorization": "Bearer s3cret", "Origin": "https://chatgpt.com"})[0] == 200
    big = rpc("tools/call", {"name": "verify_report", "arguments": {"text": "x" * 500}})
    assert call(base, big, {"Authorization": "Bearer s3cret"})[0] == 413


@pytest.mark.parametrize("address", [("127.0.0.1", 80), ("localhost", 443), ("10.0.0.1", 80), ("169.254.169.254", 80),
                                     ("::1", 443), ("example.com", 22)])
def test_guard_refuses_private_addresses_and_ports(address):
    with pytest.raises(remote.Blocked):
        remote._connect(address, timeout=2)


def test_guarded_connections_and_opener():
    with pytest.raises(remote.Blocked):
        remote.GuardedHTTPConnection("127.0.0.1", 80, timeout=2).connect()
    with pytest.raises(remote.Blocked):
        remote.GuardedHTTPSConnection("127.0.0.1", 443, timeout=2).connect()
    opener = remote.guarded_opener()
    with pytest.raises(urllib.error.URLError, match="unknown url type"):
        opener.open("file:///etc/passwd", timeout=2)
    with pytest.raises(urllib.error.URLError):
        opener.open("http://127.0.0.1/", timeout=2)


def test_an_early_answer_reaches_the_client_and_ends_the_connection(server):
    """413 (too large), 401 (no token) and 404 (another path) are answered before the body is read. The server reads
    and drops what was declared and closes the connection: a socket closed with unread bytes is reset on Windows,
    and the client lost the answer (WinError 10053, about one call in forty before)."""
    import socket
    from urllib.parse import urlsplit
    base = server(token="s3cret", max_bytes=200)
    host, port = urlsplit(base).hostname, urlsplit(base).port
    body = json.dumps(rpc("tools/call", {"name": "verify_report", "arguments": {"text": "x" * 500}})).encode()
    for path, auth, want in [(b"/mcp", "Bearer s3cret", b" 413 "), (b"/mcp", "Bearer wrong", b" 401 "),
                             (b"/other", "Bearer s3cret", b" 404 ")] * 30:
        with socket.create_connection((host, port), timeout=10) as s:
            s.sendall(b"POST " + path + b" HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                      + b"Authorization: "
                      + auth.encode() + b"\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
            got = b""
            while chunk := s.recv(65536):
                got += chunk
        head = got.split(b"\r\n\r\n", 1)[0]
        assert want in head.split(b"\r\n")[0] and b"Connection: close" in head, got[:200]
