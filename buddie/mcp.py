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
MAX_REPORT_BYTES = 16 * 2**20  # a report to verify: text or file

_REPORT = {
    "text": {"type": "string", "description": "the report itself (Markdown); or give path"},
    "path": {"type": "string", "description": "a Markdown file to check instead of text"},
}
# What a client model needs to write a checkable report. Clients without buddie's skill (ChatGPT, claude.ai, Codex
# without the plugin) get only this and the tool descriptions; the examples are tested (tests/test_instructions.py).
QUOTE_EXAMPLE = ("Article 2.10 says «Юридическое лицо, присоединившее другое юридическое лицо, подлежит ответственности» "
                 "([КоАП РФ, ст. 2.10](https://www.zakonrf.info/koap/2.10/)).")
ANCHOR_EXAMPLE = "The fix is merged and CI passed. ⚓ `pr:octo/app#54=merged@9653a7c` ⚓ `ci:octo/app@9653a7c=success`"
FORMAT = (
    "buddie checks by code, without a model, only two things. "
    "1) Quotations: words inside “…”, «…» or \"…\", at least 12 characters, copied character for character from the page, "
    "with a Markdown link to that same page in the same sentence, e.g. " + QUOTE_EXAMPLE + " "
    "Call snap with the URL first and copy the words from source_text, not from memory or a summary. "
    "A paraphrase, a quote without a link and a link without a quote are not checked. "
    "2) Anchors: the sign ⚓ and then, in backticks, `pr:OWNER/REPO#N=merged@SHA` or `=open`, "
    "`ci:OWNER/REPO@SHA=success`, `path#sha256` or `path@commit` (a file in a repo checkout), "
    "`run:COMMAND => OUTPUT` (a command and what it printed), e.g. " + ANCHOR_EXAMPLE + ". "
)
OUTCOMES = (
    "Outcomes: FAIL means a quote is not in its source or an anchor does not hold: fix each blocking item, or keep it "
    "and add a line starting with 'buddie:' that says what is unverified and why. GAPS means something could not be "
    "checked (source unreachable, anchor not checkable here): say what. PASS means every quote was found and every "
    "anchor holds. EMPTY means the text had no quotations and no anchors, so nothing was verified: it is not a pass. "
    "Do not delete a true claim only to get PASS. Put the receipt's predicate.line under the report, copied from the "
    "tool's result; never write a receipt line yourself, and if the tool cannot be called, say that nothing was checked."
)
INSTRUCTIONS = ("Before you accept a report or hand in a final answer that quotes sources or states facts about a repo, "
                "a PR or CI, call verify_report with the whole text. " + FORMAT + OUTCOMES)

TOOLS = [
    {
        "name": "verify_report",
        "description": "Check a report before accepting or passing it on: every quote must be in the bytes of the "
                       "source it links to (verbatim), every `⚓` anchor must hold in the repos, on GitHub (pr:, ci:) or "
                       "in the session transcript (run:). Returns a receipt with outcome FAIL / GAPS / PASS / EMPTY, "
                       "the blocking items and a one-line summary. Only quotations in quotation marks with a link to "
                       "their page in the same sentence, and ⚓ anchors in backticks, are checked: write e.g. "
                       + QUOTE_EXAMPLE + " EMPTY means nothing was checkable, not that the text is right.",
        "inputSchema": {"type": "object", "properties": dict(_REPORT, **{
            "repos": {"type": "array", "items": {"type": "string"},
                      "description": "repo checkouts for anchors (default: the git repo at or under the server's cwd; "
                                     "in Codex none, so pass the workspace path)"},
            "fetch": {"type": "boolean", "default": True, "description": "snapshot cited URLs not in the store yet"},
            "access": {"type": "string", "description": "verbatim --access for unreadable pages, e.g. 'default'"},
            "store": {"type": "string", "description": "snapshot store (default $VERBATIM_STORE or ./.verbatim)"},
            "transcript": {"type": "string", "description": "Claude Code session jsonl for run: anchors"},
            "numbers": {"type": "string", "enum": ["gap", "fail", "off"], "default": "gap",
                        "description": "a number of a cited sentence not in its source: gap, fail or off"},
            "github": {"type": "boolean", "default": True, "description": "ask GitHub for pr:/ci: anchors"},
            "profile": {"type": "string", "enum": ["developer", "research", "complete", "custom"],
                        "description": "what to check (default: everything): developer (repo, PR, CI, run: and work "
                                       "claims), research (quotes and numbers), complete, or custom with modules "
                                       "and/or checks. What a profile leaves out is not checked, and the result says"
                                       " so"},
            "modules": {"type": "array", "items": {"type": "string", "enum": ["sources", "github", "execution"]},
                        "description": "custom: these verification modules: sources (quotes, numbers), github (repo "
                                       "anchors, pr:, ci:), execution (run:, choice:, work claims)"},
            "receipt": {"type": "string", "enum": ["v0", "v1"], "default": "v0",
                        "description": "receipt contract of the result: v0 (default) or v1, which also says what was "
                                       "checked, what was not and why (scope, coverage)"},
            "checks": {"type": "array", "items": {"type": "string"},
                       "description": "custom: these checks (quote, number, file_anchor, commit_anchor, fact_anchor, "
                                      "pr_anchor, ci_anchor, run_anchor, choice_anchor, work_claim, other_anchor)"},
        })},
    },
    {
        "name": "snap",
        "description": "Snapshot URLs (bytes by sha256) so quotes can be taken from and checked against them. Call "
                       "it before quoting a page, then copy the words from source_text and link the same URL.",
        "inputSchema": {"type": "object", "required": ["urls"], "properties": {
            "urls": {"type": "array", "items": {"type": "string"}}, "store": {"type": "string"}}},
    },
    {
        "name": "source_text",
        "description": "Visible text of a snapshot (URL or sha256 prefix). With grep, only the matches with context. "
                       "Copy quotes from here character for character, put them in quotation marks “…” or «…», and "
                       "link the snapshot's URL right after the quote in the same sentence.",
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
    """The report and its name. `path` is a file the client names on purpose, as `buddie verify FILE` would read it:
    any regular file the user running the server can read (the client's tool approval is the consent). Nothing in a
    report makes buddie open a path of its own; that is what anchors.py's repo rule is for."""
    if args.get("text"):
        if len(args["text"]) > MAX_REPORT_BYTES:
            raise ValueError(f"text over {MAX_REPORT_BYTES // 2**20} MiB")
        return args["text"], "report"
    if args.get("path"):
        path = Path(args["path"])
        if not path.is_file():
            raise ValueError(f"{path}: not a regular file")
        with path.open("rb") as f:
            data = f.read(MAX_REPORT_BYTES + 1)
        if len(data) > MAX_REPORT_BYTES:
            raise ValueError(f"{path}: over {MAX_REPORT_BYTES // 2**20} MiB")
        from buddie.anchors import text_of
        return text_of(data), args["path"]
    raise ValueError("give text or path")


def default_repos() -> list[Path]:
    """The repos around the cwd, unless BUDDIE_DEFAULT_REPOS=none: Codex starts plugin servers in the plugin's own
    copy (.codex-plugin/plugin.json), where the cwd is buddie's repository, not the user's."""
    from buddie.anchors import find_repos
    return [] if os.environ.get("BUDDIE_DEFAULT_REPOS") == "none" else find_repos(Path.cwd())


def verify_report(args: dict) -> tuple[dict, bool]:
    from buddie.effects import github_get
    from buddie import profiles, receipts
    from buddie.verify import assessment
    text, name = _report(args)
    version = receipts.version_of(args.get("receipt"))
    repos = [Path(r) for r in args["repos"]] if args.get("repos") else default_repos()
    got = assessment(text, args.get("modules"), name=name, repos=repos, store=args.get("store"),
                     fetch=args.get("fetch", True), access=args.get("access"),
                     github=github_get if args.get("github", True) else None, transcript=args.get("transcript"),
                     numbers=args.get("numbers", "gap"), profile=args.get("profile"), checks=args.get("checks"))
    # the receipt in the contract asked for is the result; what a profile left out goes with it as text (handle)
    return receipts.render(got, version), False, profiles.note(got.effective, got.coverage)


def snap(args: dict) -> tuple[dict, bool]:
    from buddie.verbatim.store import Store
    store, out = Store(args.get("store")), []
    for url in args["urls"]:
        e = store.fetch(url)
        out.append({"url": url, "sha256": e.get("sha256"), "http_status": e.get("http_status"),
                    "bytes": e.get("bytes"), "error": e.get("error")})
    return {"snapshots": out}, not any(o["sha256"] for o in out)


def source_text(args: dict) -> tuple[dict, bool]:
    from buddie.verbatim.store import Store
    from buddie.verbatim.textlayer import Unreadable, layers
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

# MCP tool annotations (clients and app directories ask for them): nothing here changes the user's data; the
# fetching tools reach the open web, summary only reads this machine's journal
_ANNOTATIONS = {
    "verify_report": {"title": "Verify a report", "openWorldHint": True},
    "snap": {"title": "Snapshot pages", "openWorldHint": True},
    "source_text": {"title": "Read a snapshot", "openWorldHint": False},
    "summary": {"title": "Subagent summary", "openWorldHint": False},
}
for _tool in TOOLS:
    _tool["annotations"] = dict(_ANNOTATIONS[_tool["name"]], readOnlyHint=True, destructiveHint=False,
                                idempotentHint=True)


def handle(msg: dict, handlers: dict | None = None) -> dict | None:
    """The response to one JSON-RPC message; None for notifications. handlers: the tool set (remote.py's is
    narrower)."""
    handlers = HANDLERS if handlers is None else handlers
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None
    try:
        if method == "initialize":
            asked = (msg.get("params") or {}).get("protocolVersion")
            result = {"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                      "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": "buddie", "version": __version__},
                      "instructions": INSTRUCTIONS}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            if name not in handlers:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {name}"}}
            try:
                data, is_error, *note = handlers[name](params.get("arguments") or {})
            except Exception as error:  # a tool failure is a result the model can read, not a protocol error
                data, is_error, note = {"error": f"{type(error).__name__}: {error}"}, True, []
            text = json.dumps(data, ensure_ascii=False, indent=1)
            if name == "verify_report" and not is_error:
                from buddie import receipts
                first = receipts.line(data) if data.get("predicateType") == receipts.V1 else data["predicate"]["line"]
                text = first + "\n" + "".join(f"{n}\n" for n in note if n) + text
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
