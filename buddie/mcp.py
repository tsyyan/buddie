"""A local MCP server over stdio: newline-delimited JSON-RPC 2.0, no SDK, no dependencies.

Tools:
  verify_report   the receipt for a report (text or file): quotes against their snapshots, anchors against repos
  snap            snapshot URLs into the store before reading them (quote from bytes, not from a summary)
  source_text     visible text of a snapshot, optionally only around a regex: copy quotes from here
  summary         when no subagent is left: what was done and lost, the next steps with auto/ask, a choice card
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from buddie import __version__

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
TEXT_LIMIT = 20000

_REPORT = {
    "text": {"type": "string", "description": "the report itself (Markdown); or give path"},
    "path": {"type": "string", "description": "a Markdown file to check instead of text"},
}
TOOLS = [
    {
        "name": "verify_report",
        "description": "Check a report before accepting or passing it on: every quote must be in the bytes of the "
                       "source it links to (verbatim), every `⚓` anchor must hold in the repos, on GitHub (pr:, ci:) or in the session transcript (run:). Returns a receipt "
                       "with outcome FAIL / GAPS / PASS / EMPTY, the blocking items and a one-line summary.",
        "inputSchema": {"type": "object", "properties": dict(_REPORT, **{
            "repos": {"type": "array", "items": {"type": "string"},
                      "description": "repo checkouts for anchors (default: the git repo at or under the cwd)"},
            "fetch": {"type": "boolean", "default": True, "description": "snapshot cited URLs not in the store yet"},
            "access": {"type": "string", "description": "verbatim --access for unreadable pages, e.g. 'default'"},
            "store": {"type": "string", "description": "snapshot store (default $VERBATIM_STORE or ./.verbatim)"},
            "transcript": {"type": "string", "description": "Claude Code session jsonl for run: anchors"},
            "numbers": {"type": "string", "enum": ["gap", "fail", "off"], "default": "gap",
                        "description": "a number of a cited sentence not in its source: gap, fail or off"},
            "github": {"type": "boolean", "default": True, "description": "ask GitHub for pr:/ci: anchors"},
        })},
    },
    {
        "name": "snap",
        "description": "Snapshot URLs (bytes by sha256) so quotes can be taken from and checked against them.",
        "inputSchema": {"type": "object", "required": ["urls"], "properties": {
            "urls": {"type": "array", "items": {"type": "string"}}, "store": {"type": "string"}}},
    },
    {
        "name": "source_text",
        "description": "Visible text of a snapshot (URL or sha256 prefix). With grep, only the matches with context. "
                       "Copy quotes from here character for character.",
        "inputSchema": {"type": "object", "required": ["ref"], "properties": {
            "ref": {"type": "string"}, "grep": {"type": "string"}, "context": {"type": "integer", "default": 160},
            "store": {"type": "string"}}},
    },
    {
        "name": "summary",
        "description": "When no subagent is left: the summary built by code from the hook's records (what each subagent "
                       "did with its receipt outcome, who was lost, the next steps with auto/ask verdicts, open PRs "
                       "and red CI) and `card`, a ready AskUserQuestion input with at most three steps and «Ничего не "
                       "запускать». Show `text` as is and ask with `card` unchanged; launch `auto` steps yourself and "
                       "the picked ones with the anchor ⚓ choice:<summary_id>=<step>.",
        "inputSchema": {"type": "object", "properties": {
            "session": {"type": "string", "description": "the session id (default: the one whose state changed last)"},
            "repos": {"type": "array", "items": {"type": "string"},
                      "description": "repo checkouts with buddie.toml for the queue (default: around the cwd)"},
            "queue": {"type": "boolean", "default": True, "description": "add the queue's proposed rows"},
            "stale": {"type": "integer", "default": 30, "description": "minutes before a silent subagent is lost"}}},
    },
]


def _report(args: dict) -> tuple[str, str]:
    if args.get("text"):
        return args["text"], "report"
    if args.get("path"):
        return Path(args["path"]).read_text(encoding="utf-8"), args["path"]
    raise ValueError("give text or path")


def verify_report(args: dict) -> tuple[dict, bool]:
    from buddie.anchors import find_repos
    from buddie.effects import github_get
    from buddie.verify import verify
    text, name = _report(args)
    repos = [Path(r) for r in args["repos"]] if args.get("repos") else find_repos(Path.cwd())
    receipt = verify(text, name=name, repos=repos, store=args.get("store"), fetch=args.get("fetch", True),
                     access=args.get("access"), github=github_get if args.get("github", True) else None,
                     transcript=args.get("transcript"), numbers=args.get("numbers", "gap"))
    return receipt, False


def snap(args: dict) -> tuple[dict, bool]:
    from verbatim.store import Store
    store, out = Store(args.get("store")), []
    for url in args["urls"]:
        e = store.fetch(url)
        out.append({"url": url, "sha256": e.get("sha256"), "http_status": e.get("http_status"),
                    "bytes": e.get("bytes"), "error": e.get("error")})
    return {"snapshots": out}, not any(o["sha256"] for o in out)


def source_text(args: dict) -> tuple[dict, bool]:
    from verbatim.store import Store
    from verbatim.textlayer import Unreadable, layers
    try:
        entry, data = Store(args.get("store")).resolve(args["ref"])
    except KeyError:
        return {"error": f"no snapshot for {args['ref']}; call snap first"}, True
    try:
        visible = layers(data, entry.get("content_type"), entry.get("content_encoding"))["visible"]
    except Unreadable as error:
        return {"error": str(error)}, True
    head = {"url": entry.get("final_url"), "sha256": entry["sha256"], "fetched_at": entry.get("fetched_at"),
            "chars": len(visible)}
    if not args.get("grep"):
        return dict(head, text=visible[:TEXT_LIMIT], truncated=len(visible) > TEXT_LIMIT), False
    pad = int(args.get("context", 160))
    hits = [{"offset": m.start(), "text": visible[max(0, m.start() - pad):m.end() + pad]}
            for m in re.finditer(args["grep"], visible, re.I)][:50]
    return dict(head, matches=hits), not hits


def summary(args: dict) -> tuple[dict, bool]:
    from buddie.anchors import find_repos
    from buddie.summary import summarize
    repos = [Path(r) for r in args["repos"]] if args.get("repos") else find_repos(Path.cwd())
    return summarize(args.get("session"), repos, queue=args.get("queue", True), stale=int(args.get("stale", 30))), False


HANDLERS = {"verify_report": verify_report, "snap": snap, "source_text": source_text, "summary": summary}


def handle(msg: dict) -> dict | None:
    """The response to one JSON-RPC message; None for notifications."""
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None
    try:
        if method == "initialize":
            asked = (msg.get("params") or {}).get("protocolVersion")
            result = {"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                      "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": "buddie", "version": __version__},
                      "instructions": "Before accepting an executor's report or sending a final answer that quotes "
                                      "sources or states repo facts, call verify_report and put its predicate.line "
                                      "next to the report. FAIL means fix or disclose before passing it on."}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            if name not in HANDLERS:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {name}"}}
            try:
                data, is_error = HANDLERS[name](params.get("arguments") or {})
            except Exception as error:  # a tool failure is a result the model can read, not a protocol error
                data, is_error = {"error": f"{type(error).__name__}: {error}"}, True
            text = json.dumps(data, ensure_ascii=False, indent=1)
            if name == "verify_report" and not is_error:
                text = data["predicate"]["line"] + "\n" + text
            elif name == "summary" and not is_error:
                text = data["text"] + "\n" + text
            result = {"content": [{"type": "text", "text": text}], "structuredContent": data, "isError": is_error}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    except Exception as error:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(error)}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(stdin=None, stdout=None) -> int:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as error:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(error)}}
        else:
            reply = handle(msg) if isinstance(msg, dict) else {
                "jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "batches are not supported"}}
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0
