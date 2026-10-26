"""A stdio MCP server serving one run's diagnostic tool from the recordings (for model backends that speak MCP).

  python harness/bdx/mcp_server.py --scenario ID --condition B|C --run-id RUN --log FILE

One process per run, so the budget and the log belong to that run alone. Every call is appended to FILE as one JSON
line (the router's record: arguments, response text, bytes).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bdx import scenarios, tools  # noqa: E402

PROTOCOL = "2025-06-18"


def handle(msg: dict, router: tools.Router, specs: list[dict], log: Path) -> dict | None:
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None
    if method == "initialize":
        asked = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL
        result = {"protocolVersion": asked, "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "diag", "version": "bdx-001-lite"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": t["name"], "description": t["description"], "inputSchema": t["input_schema"]}
                            for t in specs]}
    elif method == "tools/call":
        params = msg.get("params") or {}
        text, is_error = router.call(params.get("name"), params.get("arguments") or {})
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(router.calls[-1], ensure_ascii=False) + "\n")
        result = {"content": [{"type": "text", "text": text}], "isError": is_error}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--condition", required=True, choices=["B", "C"])
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--log", required=True)
    args = ap.parse_args()
    s = scenarios.load()[args.scenario]
    router = tools.Router(s, args.condition, args.run_id)
    specs = tools.specs(args.condition, s)
    log = Path(args.log)
    stdin = sys.stdin.buffer
    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw.decode("utf-8"))
        except ValueError:
            continue
        reply = handle(msg, router, specs, log)
        if reply is not None:
            sys.stdout.buffer.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
            sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
