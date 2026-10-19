"""A remote MCP server: Streamable HTTP (MCP 2025-06-18), stdlib only, for clients that cannot start a local
process (ChatGPT apps and connectors, claude.ai custom connectors, the API's MCP connector).

    buddie serve --http [--host 127.0.0.1] [--port 8000]

POST /mcp takes one JSON-RPC message and answers with application/json (no SSE stream: every tool returns one
result); a notification gets 202. GET /healthz is for load balancers. The server keeps no sessions.

Whoever can reach the URL can call the tools, so the remote surface is narrower than stdio's:
- tools: verify_report, snap, source_text. No `summary` (it reads the hook's journal on this machine).
- no argument names a file or a directory on the server: no `path`, `repos`, `store`, `transcript`; no `access`
  cascade. Repo anchors (`path#sha256`, `path@commit`, `fact=`) are UNCHECKABLE here, `run:` too; quotes, numbers
  and `pr:`/`ci:` (public GitHub) are checked as locally.
- fetches go only to http(s) on ports 80 and 443 of public addresses, every hop of a redirect included, and the
  socket connects to the address that was checked (no DNS rebinding between check and connect).

Environment: BUDDIE_HTTP_TOKEN (when set, `Authorization: Bearer <token>` is required), BUDDIE_HTTP_ORIGINS (comma
list of browser origins allowed; a request with any other Origin header gets 403), BUDDIE_HTTP_MAX_BYTES (request
body, default 1 MB), BUDDIE_HTTP_WORKERS (calls at once, default 8; more get 503), VERBATIM_STORE (snapshot store,
shared by all callers: snapshots are of public pages and content-addressed), BUDDIE_GITHUB_TOKEN (read by pr:/ci:
for every caller: give it no scopes beyond public data).
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import os
import socket
import sys
import threading
import urllib.request
from http.client import HTTPConnection, HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from buddie import __version__, mcp

PORTS = (80, 443)
MAX_URLS = 20


class Blocked(OSError):
    """A fetch to an address the remote server must not reach."""


def public_url(url: str) -> str | None:
    """Why `url` may not be fetched from the remote server, or None when it may (scheme and port only)."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        return f"only http and https URLs, not {parts.scheme or 'none'}"
    if not parts.hostname:
        return "no host"
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return "bad port"
    return None if port in PORTS else f"port {port}: only 80 and 443"


def _connect(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, *args, **kwargs):
    """socket.create_connection that resolves the host once, refuses non-public addresses and connects to the
    address it checked."""
    host, port = address
    if port not in PORTS:
        raise Blocked(f"port {port}: only 80 and 443")
    error = None
    for family, kind, proto, _, sockaddr in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        ip = ipaddress.ip_address(sockaddr[0].split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise Blocked(f"{host} resolves to {ip}, not a public address")
        sock = socket.socket(family, kind, proto)
        try:
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            sock.connect(sockaddr)
            return sock
        except OSError as e:
            sock.close()
            error = e
    raise error or OSError(f"no address for {host}")


class _Guarded:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _connect


class GuardedHTTPConnection(_Guarded, HTTPConnection):
    pass


class GuardedHTTPSConnection(_Guarded, HTTPSConnection):
    pass


class _HTTP(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(GuardedHTTPConnection, req)


class _HTTPS(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(GuardedHTTPSConnection, req, context=self._context)


def guarded_opener() -> urllib.request.OpenerDirector:
    """http(s) only (no file:, ftp:, data:), no proxies from the environment, guarded sockets, redirects followed
    through the same guard."""
    opener = urllib.request.OpenerDirector()
    for handler in (urllib.request.ProxyHandler({}), urllib.request.UnknownHandler(), _HTTP(), _HTTPS(),
                    urllib.request.HTTPDefaultErrorHandler(), urllib.request.HTTPRedirectHandler(),
                    urllib.request.HTTPErrorProcessor()):
        opener.add_handler(handler)
    return opener


# --- the tools as the remote server offers them -------------------------------------------------------------------

def _only(args: dict, allowed: set[str]) -> None:
    extra = sorted(set(args) - allowed)
    if extra:
        raise ValueError(f"not available on the remote server: {', '.join(extra)}")


def verify_report(args: dict) -> tuple[dict, bool]:
    from buddie.effects import github_get
    from buddie.verify import verify
    _only(args, {"text", "fetch", "numbers", "github"})
    if not args.get("text"):
        raise ValueError("give text")
    receipt = verify(args["text"], name="report", repos=[], fetch=args.get("fetch", True), mandate=False,
                     github=github_get if args.get("github", True) else None, numbers=args.get("numbers", "gap"))
    return receipt, False


def snap(args: dict) -> tuple[dict, bool]:
    _only(args, {"urls"})
    urls = list(args.get("urls") or [])
    if len(urls) > MAX_URLS:
        raise ValueError(f"at most {MAX_URLS} URLs per call")
    for url in urls:
        if why := public_url(url):
            raise ValueError(f"{url}: {why}")
    return mcp.snap({"urls": urls})


def source_text(args: dict) -> tuple[dict, bool]:
    _only(args, {"ref", "grep", "context"})
    return mcp.source_text(args)


HANDLERS = {"verify_report": verify_report, "snap": snap, "source_text": source_text}
_DROP = {"verify_report": {"path", "repos", "store", "transcript", "access"}, "snap": {"store"},
         "source_text": {"store"}}


def tools() -> list[dict]:
    """The stdio tools without the arguments the remote server refuses."""
    out = []
    for tool in mcp.TOOLS:
        if tool["name"] not in HANDLERS:
            continue
        schema = dict(tool["inputSchema"])
        schema["properties"] = {k: v for k, v in schema["properties"].items() if k not in _DROP[tool["name"]]}
        if tool["name"] == "verify_report":
            schema["required"] = ["text"]
            schema["properties"]["text"] = {"type": "string", "description": "the report itself (Markdown)"}
        out.append(dict(tool, inputSchema=schema))
    return out


def handle(msg: dict) -> dict | None:
    """mcp.handle with the remote tool set."""
    method = msg.get("method")
    if method == "tools/list" and msg.get("id") is not None:
        return {"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": tools()}}
    if method == "tools/call":
        name = (msg.get("params") or {}).get("name")
        if name not in HANDLERS:
            return {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32602, "message": f"unknown tool {name}"}}
    return mcp.handle(msg, handlers=HANDLERS)


# --- HTTP ------------------------------------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = f"buddie/{__version__}"
    protocol_version = "HTTP/1.1"
    token: str | None = None
    origins: frozenset[str] = frozenset()
    max_bytes = 1 << 20
    slots = threading.BoundedSemaphore(8)

    def log_message(self, fmt, *args):  # no request lines with report text or tokens: method, path, status only
        sys.stderr.write(f"{self.log_date_time_string()} {fmt % args}\n")

    def _send(self, status: int, body: dict | str | None = None, headers: dict | None = None) -> None:
        data = b"" if body is None else (body if isinstance(body, str) else json.dumps(body, ensure_ascii=False))
        data = data.encode("utf-8") if isinstance(data, str) else data
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        if body is not None:
            self.send_header("Content-Type", "application/json" if not isinstance(body, str) else "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _refused(self) -> bool:
        origin = self.headers.get("Origin")
        if origin and origin not in self.origins:
            self._send(403, {"error": "origin not allowed"})
            return True
        if self.token:
            given = self.headers.get("Authorization", "")
            if not hmac.compare_digest(given.encode(), f"Bearer {self.token}".encode()):
                self._send(401, {"error": "bearer token required"}, {"WWW-Authenticate": 'Bearer realm="buddie"'})
                return True
        return False

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/healthz":
            return self._send(200, {"ok": True, "version": __version__})
        if path == "/mcp":
            return self._send(405, {"error": "this server sends no event stream; POST JSON-RPC to /mcp"},
                              {"Allow": "POST"})
        if path == "/":
            return self._send(200, f"buddie {__version__}: MCP endpoint at /mcp\n")
        self._send(404, {"error": "not found"})

    def do_DELETE(self):
        self._send(405, {"error": "no sessions to end"}, {"Allow": "POST"})

    def do_POST(self):
        if urlsplit(self.path).path != "/mcp":
            return self._send(404, {"error": "not found"})
        if self._refused():
            return
        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError:
            return self._send(411, {"error": "Content-Length required"})
        if length > self.max_bytes:
            return self._send(413, {"error": f"body over {self.max_bytes} bytes"})
        raw = self.rfile.read(length)
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            return self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(error)}})
        if not isinstance(msg, dict):
            return self._send(400, {"jsonrpc": "2.0", "id": None,
                                    "error": {"code": -32600, "message": "one JSON-RPC message per request"}})
        if not self.slots.acquire(blocking=False):
            return self._send(503, {"error": "busy, retry later"}, {"Retry-After": "5"})
        try:
            reply = handle(msg)
        finally:
            self.slots.release()
        if reply is None:
            return self._send(202)
        self._send(200, reply)


def make_server(host: str = "127.0.0.1", port: int = 8000, *, token: str | None = None,
                origins: list[str] | None = None, max_bytes: int | None = None,
                workers: int | None = None) -> ThreadingHTTPServer:
    env = os.environ
    attrs = {
        "token": token if token is not None else (env.get("BUDDIE_HTTP_TOKEN") or None),
        "origins": frozenset(origins if origins is not None else
                             [o.strip() for o in env.get("BUDDIE_HTTP_ORIGINS", "").split(",") if o.strip()]),
        "max_bytes": max_bytes or int(env.get("BUDDIE_HTTP_MAX_BYTES") or 1 << 20),
        "slots": threading.BoundedSemaphore(workers or int(env.get("BUDDIE_HTTP_WORKERS") or 8)),
    }
    urllib.request.install_opener(guarded_opener())  # every fetch in this process: verbatim, GitHub, redirects
    return ThreadingHTTPServer((host, port), type("BuddieHandler", (Handler,), attrs))


def serve(host: str = "127.0.0.1", port: int = 8000) -> int:
    server = make_server(host, port)
    sys.stderr.write(f"buddie {__version__}: MCP over HTTP at http://{host}:{server.server_port}/mcp"
                     f"{' (bearer token required)' if server.RequestHandlerClass.token else ''}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
