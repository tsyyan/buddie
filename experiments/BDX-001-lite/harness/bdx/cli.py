"""BDX-001 Lite command line (run from experiments/BDX-001-lite/harness):

  python -m bdx plan --set smoke|full --reps N --seed S --out ../results/<batch>
  python -m bdx preview ../results/<batch> [--run RUN_ID]    the exact prompts and tools, no model call
  python -m bdx run ../results/<batch> --backend claude-cli --model MODEL [--limit N] [--confirm-cost]
  python -m bdx evaluate ../results/<batch>                  deterministic evaluation + summary
  python -m bdx packet ../results/<batch>                    blinded manual-review packet

A plan fixes the run order (shuffled with the seed) before anything runs; `run` executes pending runs in that order
and writes one record per run under runs/. Model backends cost usage: `run` refuses without --confirm-cost.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from bdx import BUDGET, CONDITIONS, ROOT, backends, fixtures, prompts, scenarios, tools

sys.path.insert(0, str(ROOT / "evaluation"))
RUN_SCHEMA = "bdx-001-lite/run-v1"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture_digests(s: scenarios.Scenario) -> dict:
    out = {}
    for b in s.bindings.values():
        for f in ("buddie_full.json", "buddie_catalog.json", "shell.json", "meta.json"):
            out[f"{b['env']}/{f}"] = _sha(fixtures.RAW / b["env"] / f)
    return out


def plan(args) -> int:
    ids = scenarios.smoke() if args.set == "smoke" else list(scenarios.load())
    runs = [{"scenario": sid, "condition": c, "repetition": r} for sid in ids for c in CONDITIONS
            for r in range(1, args.reps + 1)]
    random.Random(args.seed).shuffle(runs)
    for i, r in enumerate(runs):
        r["order"] = i
        r["run_id"] = f"{r['scenario']}-{r['condition']}-r{r['repetition']}"
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "runs").mkdir(exist_ok=True)
    doc = {"schema": "bdx-001-lite/plan-v1", "created_at": now(), "set": args.set, "reps": args.reps,
           "seed": args.seed, "budget": BUDGET, "runs": runs,
           "inputs_sha256": {"scenarios.json": _sha(scenarios.PATH),
                             "ground_truth.json": _sha(ROOT / "evaluation" / "ground_truth.json"),
                             "shell_menu.json": _sha(fixtures.MENU)}}
    (out / "plan.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(f"{len(runs)} runs planned in {out / 'plan.json'}")
    return 0


def prepare(entry: dict) -> dict:
    s = scenarios.load()[entry["scenario"]]
    return {**entry, "_scenario": s,
            "prompts": {"system": prompts.system(entry["condition"], s), "user": prompts.user(s)},
            "tools_available": tools.specs(entry["condition"], s)}


def preview(args) -> int:
    batch = Path(args.batch)
    for e in json.loads((batch / "plan.json").read_text(encoding="utf-8"))["runs"]:
        if args.run and e["run_id"] != args.run:
            continue
        r = prepare(e)
        print(f"===== {r['run_id']} (order {r['order']})\n--- system\n{r['prompts']['system']}\n--- user\n"
              f"{r['prompts']['user']}\n--- tools: {[t['name'] for t in r['tools_available']]}\n")
    return 0


def record(r: dict, out: dict, backend: str, model: str | None, started: str) -> dict:
    calls = out.get("tool_calls") or []
    counted = [c for c in calls if c.get("counted")]
    s = r["_scenario"]
    envs = sorted({b["env"] for b in s.bindings.values()})
    return {
        "schema": RUN_SCHEMA, "run_id": r["run_id"], "order": r["order"], "scenario": r["scenario"],
        "condition": r["condition"], "repetition": r["repetition"],
        "backend": {"name": backend, "model_requested": model, "model_reported": out.get("model_reported"),
                    "cli_version": out.get("cli_version"), "flags": out.get("flags")},
        "prompts": r["prompts"], "tools_available": r["tools_available"],
        "tool_calls": calls, "tool_used": bool(counted), "diagnostic_iterations": len(counted),
        "items_requested": [c.get("items") for c in counted],
        "response_bytes_total": sum(c["response_bytes"] for c in counted),
        "final_text": out.get("final_text"), "started_at": started, "duration_s": out.get("duration_s"),
        "num_turns": out.get("num_turns"), "usage": out.get("usage"), "cost_usd": out.get("cost_usd"),
        "status": "ok" if not out.get("failure") else "harness_failure", "failure": out.get("failure"),
        "isolation": out.get("isolation"), "exit_code": out.get("exit_code"),
        "fixtures": {"environments": envs, "sha256": fixture_digests(s),
                     "buddie_version": {e: fixtures.env(e)["meta"]["buddie_version"] for e in envs},
                     "collected_at": {e: fixtures.env(e)["meta"]["collected_at"] for e in envs}},
    }


def run(args) -> int:
    batch = Path(args.batch)
    if args.backend == "claude-cli" and not args.confirm_cost:
        print("claude-cli uses the logged-in account's usage: pass --confirm-cost once it is approved",
              file=sys.stderr)
        return 2
    import os
    if args.backend == "claude-cli" and not os.environ.get("ANTHROPIC_API_KEY") and not args.allow_host_context:
        print(f"refused before any run: {backends.HOST_CONTEXT}", file=sys.stderr)
        return 2
    entries = json.loads((batch / "plan.json").read_text(encoding="utf-8"))["runs"]
    done = 0
    for e in entries:
        path = batch / "runs" / f"{e['run_id']}.json"
        if path.exists():
            continue
        if args.limit is not None and done >= args.limit:
            break
        r = prepare(e)
        started = now()
        print(f"[{e['order']}] {e['run_id']} ...", flush=True)
        try:
            out = backends.claude_cli(r, args.model, allow_host_context=args.allow_host_context)
        except (backends.HarnessFailure, OSError, TimeoutError) as error:
            out = {"failure": f"harness: {type(error).__name__}: {error}"}
        except Exception as error:  # noqa: BLE001 - a crashed run is recorded, not lost
            out = {"failure": f"harness: {type(error).__name__}: {error}"}
        rec = record(r, out, args.backend, args.model, started)
        (batch / "events").mkdir(exist_ok=True)
        (batch / "events" / f"{e['run_id']}.jsonl").write_text(
            "\n".join(json.dumps(x, ensure_ascii=False) for x in out.get("events") or []), encoding="utf-8")
        path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"    {rec['status']} {rec['failure'] or ''} {rec['duration_s']}s calls={rec['diagnostic_iterations']}",
              flush=True)
        done += 1
        if rec["failure"] == "isolation_violation":
            print("isolation violated: stopping the batch", file=sys.stderr)
            return 1
        time.sleep(1)
    return 0


def _used_relevant(rec: dict, gt: dict) -> bool | None:
    if rec["condition"] == "A":
        return None
    wanted = set(gt["relevant_sources"][rec["condition"]])
    got = {i for items in rec["items_requested"] for i in (items or [])}
    return bool(wanted & got)


def evaluate(args) -> int:
    import evaluate as ev
    batch = Path(args.batch)
    gt = ev.ground_truth()
    rows = []
    for p in sorted((batch / "runs").glob("*.json")):
        rec = json.loads(p.read_text(encoding="utf-8"))
        verdict = ev.judge(rec["scenario"], rec["final_text"])     # blind: scenario id and answer only
        lab = ev.label(verdict, rec["condition"], rec["status"])
        usage = rec.get("usage") or {}
        rows.append({"run_id": rec["run_id"], "scenario": rec["scenario"], "condition": rec["condition"],
                     "label": lab, "verdict": verdict, "tool_used": rec["tool_used"],
                     "diagnostic_iterations": rec["diagnostic_iterations"],
                     "response_bytes_total": rec["response_bytes_total"],
                     "used_relevant_source": _used_relevant(rec, gt[rec["scenario"]]),
                     "context_sufficient": gt[rec["scenario"]]["coverage"]["buddie" if rec["condition"] == "C"
                                                                           else "shell"]
                     if rec["condition"] != "A" else "none",
                     "duration_s": rec["duration_s"], "input_tokens": usage.get("input_tokens"),
                     "output_tokens": usage.get("output_tokens"),
                     "cache_read_tokens": usage.get("cache_read_input_tokens"),
                     "cache_creation_tokens": usage.get("cache_creation_input_tokens"),
                     "cost_usd": rec.get("cost_usd")})
    summary = summarize(rows)
    (batch / "evaluations.json").write_text(json.dumps({"evaluated_at": now(), "rows": rows, "summary": summary},
                                                       ensure_ascii=False, indent=1), encoding="utf-8")
    for c, m in summary.items():
        print(c, json.dumps(m, ensure_ascii=False))
    return 0


def summarize(rows: list[dict]) -> dict:
    out = {}
    for c in CONDITIONS:
        rs = [r for r in rows if r["condition"] == c and r["label"] != "HARNESS_FAILURE"]
        n = len(rs)
        if not n:
            out[c] = {"n": 0, "harness_failures": sum(r["condition"] == c for r in rows)}
            continue
        count = lambda lab: sum(r["label"] == lab for r in rs)  # noqa: E731
        appl = [r for r in rs if r["label"] == "APPLICABLE"]
        out[c] = {
            "n": n, "harness_failures": sum(r["condition"] == c and r["label"] == "HARNESS_FAILURE" for r in rows),
            "applicable": count("APPLICABLE"), "ARR": round(count("APPLICABLE") / n, 3),
            "inapplicable": count("INAPPLICABLE"), "justified_clarification": count("JUSTIFIED_CLARIFICATION"),
            "unjustified_clarification": count("UNJUSTIFIED_CLARIFICATION"), "no_result": count("NO_RESULT"),
            "unsupported_assumption_runs": sum(bool(r["verdict"]["assumption_hits"]) for r in rs),
            "UAR": round(sum(bool(r["verdict"]["assumption_hits"]) for r in rs) / n, 3),
            "tool_use_rate": round(sum(r["tool_used"] for r in rs) / n, 3) if c != "A" else None,
            "mean_diagnostic_iterations": round(statistics.mean(r["diagnostic_iterations"] for r in rs), 2),
            "mean_response_bytes": round(statistics.mean(r["response_bytes_total"] for r in rs)),
            "used_relevant_source": sum(bool(r["used_relevant_source"]) for r in rs) if c != "A" else None,
            "median_duration_s": statistics.median(r["duration_s"] or 0 for r in rs),
            "median_duration_applicable_s": statistics.median(r["duration_s"] for r in appl) if appl else None,
            "manual_review": sum(bool(r["verdict"]["manual_review"]) for r in rs),
            "total_cost_usd": round(sum(r["cost_usd"] or 0 for r in rs), 4),
        }
    return out


def packet(args) -> int:
    """Answers for manual review without condition, model or tool transcript, in a seeded shuffle."""
    import evaluate as ev
    batch = Path(args.batch)
    items = []
    for p in sorted((batch / "runs").glob("*.json")):
        rec = json.loads(p.read_text(encoding="utf-8"))
        key = hashlib.sha256(f"bdx-blind:{rec['run_id']}".encode()).hexdigest()[:10]
        items.append({"blind_id": key, "scenario": rec["scenario"],
                      "user_message": rec["prompts"]["user"], "answer": rec["final_text"],
                      "auto": ev.judge(rec["scenario"], rec["final_text"])})
    random.Random(7).shuffle(items)
    (batch / "blind_packet.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    key = {hashlib.sha256(f"bdx-blind:{p.stem}".encode()).hexdigest()[:10]: p.stem
           for p in (batch / "runs").glob("*.json")}
    (batch / "blind_key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(f"{len(items)} items in {batch / 'blind_packet.json'} (key kept apart in blind_key.json)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bdx")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--set", choices=["smoke", "full"], default="smoke")
    p.add_argument("--reps", type=int, default=1)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=plan)
    p = sub.add_parser("preview")
    p.add_argument("batch")
    p.add_argument("--run")
    p.set_defaults(func=preview)
    p = sub.add_parser("run")
    p.add_argument("batch")
    p.add_argument("--backend", choices=["claude-cli"], default="claude-cli")
    p.add_argument("--model", required=True)
    p.add_argument("--limit", type=int)
    p.add_argument("--confirm-cost", action="store_true")
    p.add_argument("--allow-host-context", action="store_true",
                   help="run claude -p without --bare (no API key): the host's OS/shell/date reach every condition")
    p.set_defaults(func=run)
    p = sub.add_parser("evaluate")
    p.add_argument("batch")
    p.set_defaults(func=evaluate)
    p = sub.add_parser("packet")
    p.add_argument("batch")
    p.set_defaults(func=packet)
    args = ap.parse_args(argv)
    return args.func(args)
