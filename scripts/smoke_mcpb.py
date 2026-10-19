"""Start the server of an unpacked .mcpb the way Claude Desktop does (python <dir>/run.py serve, from another cwd)
and check initialize and tools/list against manifest.json.

    python scripts/smoke_mcpb.py UNPACKED_DIR
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main(root: Path) -> int:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
    with tempfile.TemporaryDirectory() as cwd:
        out = subprocess.run([sys.executable, str(root / "run.py"), "serve"], cwd=cwd, capture_output=True,
                             input="".join(json.dumps(m) + "\n" for m in msgs), text=True, encoding="utf-8",
                             timeout=60, env={"VERBATIM_STORE": str(Path(cwd) / "store"), "PATH": "",
                                              "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")})
    replies = [json.loads(line) for line in out.stdout.splitlines()]
    info = replies[0]["result"]["serverInfo"]
    tools = [t["name"] for t in replies[1]["result"]["tools"]]
    assert info["version"] == manifest["version"], (info, manifest["version"])
    assert tools == [t["name"] for t in manifest["tools"]], (tools, manifest["tools"])
    print(f"bundle {manifest['name']} {manifest['version']}: server answers, tools {', '.join(tools)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
