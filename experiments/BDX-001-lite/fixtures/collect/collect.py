"""Record one environment for BDX-001 Lite: a buddie diagnostics document and the outputs of every shell-menu command.

Run on the machine (or in the container) being recorded, from a buddie checkout:

  python experiments/BDX-001-lite/fixtures/collect/collect.py --env-id ENV --host-alias ALIAS --out DIR

What it does, and nothing else:
  1. writes a temporary grants file (every baseline category + development.containers, no directory roots) into a
     temporary config directory and points buddie at it through APPDATA / XDG_CONFIG_HOME for its own subprocess
     only: the person's real grants file is never read or changed;
  2. runs `python -m buddie snapshot --category <every category> --tool <every catalog tool>` (the real CLI, buddie's
     own collectors, unmodified) and `diagnostics.catalog()` (what `environment_snapshot(list: true)` returns);
  3. runs every command of shell_menu.json in this machine's default shell (PowerShell 5.1 on Windows, bash
     elsewhere), each with a timeout, and keeps stdout, stderr and the exit status;
  4. replaces this machine's user name and host name with fixed placeholders (privacy), recording only that it did.

Nothing is added to buddie's output: the document is written as buddie wrote it, then redacted.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
TIMEOUT = 60
MAX_OUT = 8192


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def decode(data: bytes) -> str:
    if data.count(b"\0") > len(data) // 4:  # UTF-16 (some Windows programs)
        return data.decode("utf-16-le", "replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp866" if os.name == "nt" else "latin-1", "replace")


class Redactor:
    def __init__(self, alias: str):
        users = {getpass.getuser(), Path.home().name, os.environ.get("USERNAME", ""), os.environ.get("USER", "")}
        host = socket.gethostname().split(".")[0]
        names = [(u, "user") for u in sorted(users, key=len, reverse=True)] + [(host, alias)]
        self.pairs = [(v, rep) for v, rep in names if v and len(v) >= 3]
        self.count = 0

    def __call__(self, text: str) -> str:
        for value, rep in self.pairs:
            text, n = re.subn(re.escape(value), rep, text, flags=re.IGNORECASE)
            self.count += n
        return text


def buddie_env(config: Path) -> dict:
    env = dict(os.environ, PYTHONPATH=str(REPO), PYTHONUTF8="1")
    env["APPDATA" if os.name == "nt" else "XDG_CONFIG_HOME"] = str(config)
    return env


def collect_buddie(out: Path, red: Redactor) -> dict:
    sys.path.insert(0, str(REPO))
    from buddie import diagnostics, probes
    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp)
        (config / "buddie").mkdir()
        (config / "buddie" / "environment.toml").write_text(
            'version = 1\nallow = ["baseline", "development.containers"]\nroots = []\n', encoding="utf-8")
        env = buddie_env(config)
        cats = list(diagnostics.REGISTRY) + list(diagnostics.UNSUPPORTED)
        cmd = [sys.executable, "-m", "buddie", "snapshot", "--task", "BDX-001 fixture collection",
               "--json", str(out / "buddie_full.json")]
        for c in cats:
            cmd += ["--category", c]
        for t in sorted(probes.TOOLS):
            cmd += ["--tool", t]
        started = now()
        run = subprocess.run(cmd, env=env, capture_output=True, timeout=300)
        catalog = subprocess.run([sys.executable, "-c", "import json; from buddie import diagnostics; "
                                  "print(json.dumps(diagnostics.catalog(), ensure_ascii=False))"],
                                 env=env, capture_output=True, timeout=60)
    full = out / "buddie_full.json"
    full.write_text(red(full.read_text(encoding="utf-8")), encoding="utf-8")
    (out / "buddie_catalog.json").write_text(red(decode(catalog.stdout)), encoding="utf-8")
    return {"command": "python -m buddie snapshot --category <all %d> --tool <all %d> --json buddie_full.json"
                       % (len(cats), len(probes.TOOLS)),
            "exit": run.returncode, "started_at": started, "stdout_line": red(decode(run.stdout)).splitlines()[:1],
            "catalog_exit": catalog.returncode}


def collect_shell(out: Path, red: Redactor) -> dict:
    menu = json.loads((HERE / "shell_menu.json").read_text(encoding="utf-8"))
    if os.name == "nt":
        shell = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]
        name = "Windows PowerShell 5.1 (powershell.exe -NoProfile)"
    else:
        shell, name = ["bash", "-c"], "bash -c (non-login, non-interactive)"
    env = dict(os.environ, WSL_UTF8="1")
    records = []
    for item in menu["items"]:
        at = now()
        try:
            run = subprocess.run(shell + [item["id"]], capture_output=True, timeout=TIMEOUT, env=env)
            stdout, stderr, code = decode(run.stdout), decode(run.stderr), run.returncode
        except subprocess.TimeoutExpired:
            stdout, stderr, code = "", f"[timed out after {TIMEOUT}s]", None
        except FileNotFoundError as error:
            stdout, stderr, code = "", f"[shell not available: {error}]", None
        records.append({"command": item["id"], "recorded_at": at, "exit": code,
                        "stdout": red(stdout)[:MAX_OUT], "stderr": red(stderr)[:MAX_OUT],
                        "truncated": len(stdout) > MAX_OUT or len(stderr) > MAX_OUT})
    menu_sha = hashlib.sha256((HERE / "shell_menu.json").read_bytes()).hexdigest()
    doc = {"shell": name, "menu_sha256": menu_sha, "records": records}
    (out / "shell.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"shell": name, "commands": len(records), "menu_sha256": menu_sha}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-id", required=True)
    ap.add_argument("--host-alias", required=True, help="placeholder written in place of this host's name")
    ap.add_argument("--out", required=True)
    ap.add_argument("--note", default="", help="how this environment was set up (container, runner image, ...)")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    red = Redactor(args.host_alias)
    meta = {"env_id": args.env_id, "collected_at": now(), "note": args.note,
            "collector": "experiments/BDX-001-lite/fixtures/collect/collect.py",
            "platform": {"system": platform.system(), "machine": platform.machine()},
            "python": platform.python_version()}
    meta["buddie"] = collect_buddie(out, red)
    meta["shell"] = collect_shell(out, red)
    meta["redaction"] = {"replaced": ["user name -> 'user'", "host name -> host alias"],
                         "host_alias": args.host_alias, "replacements": red.count}
    from buddie import __version__
    meta["buddie_version"] = __version__
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"env": args.env_id, "buddie_exit": meta["buddie"]["exit"], "commands": meta["shell"]["commands"],
                      "replacements": red.count}))
    return 0 if meta["buddie"]["exit"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
