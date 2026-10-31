"""BDX-003, the product run: Claude Code itself, headless, without and with the released buddie plugin.

Two tasks (PROTOCOL.md, 2026-10-31, product run):
  paragraph  a unit's paragraph, "return it ready to send" (arm A's words): the model is not asked to check.
  summary    a source page of an OK unit, "summarize it with two exact quotations": the model quotes on its own.
Two conditions, set up by the workflow as two HOME directories: `without` (plain Claude Code) and `with` (buddie
installed from its marketplace). In `with` buddie's hook reads the run's snapshots (BUDDIE_STORES=data/store), the
copies the judge reads too, so a page that changed since cannot make buddie and the judge disagree.

Every run is one `claude -p` call; its stream (stream-json) is reduced to what the reader saw: the assistant's text
messages in order. Rows go to --out (resumable: done unit/task/condition/rep are skipped).

    python product.py --units data/units.json --eligible data/eligible.json --store data/store \
        --homes "$RUNNER_TEMP/homes" --out data/product-runs.jsonl --model claude-opus-5
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import arms  # noqa: E402
from common import append_jsonl, read_json, read_jsonl  # noqa: E402

CLI = os.environ.get("CLAUDE_CLI", "@anthropic-ai/claude-code@2.1.310")
ASK_SUMMARY = ("Read the page at {url} and write a short paragraph (3 to 4 sentences) for a reader about what it says. "
               "Include at least two direct quotations from the page in quotation marks, each followed by the link "
               "as a markdown link. Reply with the paragraph only.")
# what a user lets a session do without asking: read the web; in `with`, buddie's own tools as well
BUDDIE_TOOLS = ("WebFetch mcp__plugin_buddie_buddie__snap mcp__plugin_buddie_buddie__source_text "
                "mcp__plugin_buddie_buddie__verify_report")
ALLOWED = {"without": "WebFetch", "with": BUDDIE_TOOLS, "hook": BUDDIE_TOOLS, "hookonly": "WebFetch"}
# hook (first try): the release with its skills taken out of the installed copy; its MCP tools still led the model to
# snap and verify before answering, so it is kept as an exploratory variant. hookonly: skills and MCP server taken
# out, only the hooks left: nothing invites a check before the answer, the Stop hook still checks it (PROTOCOL).


def bad(row: dict) -> str | None:
    """Why a run says nothing about the model: the API failed (Claude Code prints its error as the answer)."""
    if row.get("error"):
        return row["error"]
    if row.get("is_error"):
        return "result is_error"
    if any(t.lstrip().startswith(("API Error", "Failed to authenticate", "Credit balance")) for t in row["texts"]):
        return "API error as the answer: " + next(t for t in row["texts"] if t.lstrip().startswith(
            ("API Error", "Failed to authenticate", "Credit balance")))[:160]
    if not row.get("input_tokens") and (row.get("turns") or 0) <= 1:
        return "no tokens used"
    return None


def prompt(task: str, unit: dict) -> str:
    if task == "paragraph":
        return f"Paragraph:\n\n{unit['paragraph']}\n\n{arms.ASK_A}"
    return ASK_SUMMARY.format(url=unit["url"])


def reduce_stream(raw: str) -> dict:
    """What the run showed and cost: the assistant's text messages in order, tool calls, hook returns, usage."""
    texts, tools, returns, denied, result = [], [], 0, 0, {}
    for line in raw.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        if e.get("type") == "result":
            result = e
        if e.get("type") == "system" and e.get("subtype") == "permission_denied":
            denied += 1
        m = e.get("message")
        content = m.get("content") if isinstance(m, dict) else None
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if e.get("type") == "assistant" and c.get("type") == "text" and c.get("text", "").strip():
                texts.append(c["text"])
            elif e.get("type") == "assistant" and c.get("type") == "tool_use":
                tools.append(c.get("name"))
            elif e.get("type") == "user" and c.get("type") == "text" and "Stop hook feedback" in c.get("text", ""):
                returns += 1
    u = result.get("usage") or {}
    return {"texts": texts, "tools": tools, "hook_returns": returns, "denied": denied,
            "is_error": bool(result.get("is_error")),
            "turns": result.get("num_turns"), "subtype": result.get("subtype"),
            "input_tokens": sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                              "cache_read_input_tokens")),
            "output_tokens": int(u.get("output_tokens") or 0), "cost_usd": result.get("total_cost_usd")}


def run_one(task: str, unit: dict, condition: str, homes: Path, store: Path, model: str, max_turns: int,
            timeout: int) -> dict:
    work = homes / f"work-{condition}-{os.getpid()}"
    work.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HOME=str(homes / condition))
    if condition in ("with", "hook", "hookonly"):
        env["BUDDIE_STORES"] = str(store.resolve())
    cmd = ["npx", "--yes", CLI, "-p", prompt(task, unit), "--model", model, "--output-format", "stream-json",
           "--verbose", "--max-turns", str(max_turns), "--allowedTools", ALLOWED[condition]]
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, timeout=timeout)
        out, err = p.stdout, p.stderr[-400:]
    except subprocess.TimeoutExpired as e:
        out, err = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), "timeout"
    row = reduce_stream(out)
    row["seconds"] = round(time.monotonic() - t0, 1)
    if not row["texts"]:
        row["error"] = err or "no assistant text"
    elif bad(row):
        row["error"] = bad(row)
    return row


def plan(units: list[dict], eligible: dict, n_error: int, n_ok: int, n_summary: int, reps: int,
         seed: int, conditions: tuple = ("without", "with")) -> list[tuple]:
    ok = [u for u in units if eligible.get(u["id"], {}).get("eligible")]
    rng = random.Random(seed)
    rng.shuffle(ok)
    err = [u for u in ok if u["gold"] == "ERROR"][:n_error]
    good = [u for u in ok if u["gold"] == "OK"]
    seen, sources = set(), []
    for u in good:  # one summary per source page
        if u["url"] not in seen:
            seen.add(u["url"])
            sources.append(u)
    jobs = [("paragraph", u) for u in err + good[:n_ok]] + [("summary", u) for u in sources[:n_summary]]
    out = []
    for task, u in jobs:
        for rep in range(reps if task == "paragraph" and u["gold"] == "ERROR" else 1):
            order = random.Random(f"{seed}:{u['id']}:{task}:{rep}")  # per unit, so adding a condition keeps the rest
            conds = list(conditions)
            order.shuffle(conds)  # which condition runs first: randomized, recorded by order of rows
            out += [(task, u, c, rep) for c in conds]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", required=True)
    ap.add_argument("--eligible", required=True)
    ap.add_argument("--store", required=True)
    ap.add_argument("--homes", required=True, help="dir with without/ and with/ HOME directories (workflow sets up)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="claude-opus-5")
    ap.add_argument("--n-error", type=int, default=100)
    ap.add_argument("--n-ok", type=int, default=50)
    ap.add_argument("--n-summary", type=int, default=50)
    ap.add_argument("--reps", type=int, default=1, help="repeats of ERROR paragraphs (variance on a subset)")
    ap.add_argument("--seed", type=int, default=20261031)
    ap.add_argument("--conditions", default="without,with", help="of without, with, hook")
    ap.add_argument("--max-turns", type=int, default=12)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--minutes", type=float, default=300)
    a = ap.parse_args(argv)
    units = {u["id"]: u for u in read_json(Path(a.units))["units"]}
    eligible = {r["id"]: r for r in read_json(Path(a.eligible))["rows"]}
    out = Path(a.out)
    done = {(r["unit"], r["task"], r["condition"], r["rep"]) for r in read_jsonl(out) if not bad(r)} \
        if out.exists() else set()
    conditions = tuple(a.conditions.split(","))
    if set(conditions) - set(ALLOWED):
        ap.error(f"unknown condition in --conditions {a.conditions!r}")
    jobs = plan(list(units.values()), eligible, a.n_error, a.n_ok, a.n_summary, a.reps, a.seed, conditions)
    deadline = time.monotonic() + a.minutes * 60
    left = [j for j in jobs if (j[1]["id"], j[0], j[2], j[3]) not in done]
    print(f"::notice title=BDX-003 product plan::{len(jobs)} runs planned, {len(left)} left", flush=True)
    for task, u, cond, rep in left:
        if time.monotonic() > deadline:
            print("time is up; the next chunk resumes", flush=True)
            break
        row = run_one(task, u, cond, Path(a.homes), Path(a.store), a.model, a.max_turns, a.timeout)
        row.update(unit=u["id"], task=task, condition=cond, rep=rep, model=a.model, gold=u["gold"],
                   url=u["url"])
        append_jsonl(out, row)
        line = (f"{task} {u['id']} {u['gold']} {cond} rep {rep}: texts {len(row['texts'])}, turns {row['turns']}, "
                f"returns {row['hook_returns']}, denied {row['denied']}, tools {row['tools'][:6]}, in/out "
                f"{row['input_tokens']}/{row['output_tokens']}, {row['seconds']}s "
                f"{('ERROR ' + row['error'][:200]) if 'error' in row else ''}")
        print(f"::notice title=BDX-003 product run::{line}".replace("\n", " "), flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 - shown as an annotation (the run's log is not readable from where it is read)
        import traceback
        print(f"::error title=BDX-003 product failed::{type(e).__name__}: {e} | "
              + " | ".join(traceback.format_exc().splitlines()[-6:]))
        raise
