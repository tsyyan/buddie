"""The benchmark's commands (README.md). Offline and model-free except where a person approved a live phase.

  smoke   --out FILE [--seed N] [--reps N]   every scenario x scripted candidate x condition, in a seeded random
                                             order, one fresh world per run; writes run records (JSON lines)
  replay  FILE                               runs the same plan again and compares every deterministic field
  analyze FILE [SUMMARY.json]                the metrics (analyze.py)
  serve   --arm control|treatment --world DIR
                                             the agent-facing MCP stdio server of one condition, on a fresh world:
                                             only that condition's tools, GitHub answers from the fixture
  plan    --approval FILE --out DIR          a live phase: checks the approval (approval.schema.json) and writes the
                                             randomized, paired run plan and the prompts; calls no model
  record  --run FILE                         one live run's transcript summary -> a run record with the
                                             independent label (the agent's claim is recorded, not trusted)

No command here calls a model, fetches a page or asks GitHub."""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
from pathlib import Path

import harness as H
import scenarios as S
import world as W

HERE = Path(__file__).resolve().parent
APPROVAL_FIELDS = {"provider", "model", "repetitions", "allowed_tools", "permissions", "max_cost_usd", "sampling",
                   "context", "reporting_rules", "approved_by", "approved_at", "pricing", "limits",
                   "final_authorization"}


def plan(seed: int, reps: int, only=None) -> list[tuple]:
    """(scenario, candidate, condition, repetition) for every run, shuffled by `seed` (recorded in each record);
    only: these scenario ids (a quick subset; the full plan is the benchmark)."""
    runs = [(s, c, arm, rep) for rep in range(reps) for s in S.SCENARIOS if only is None or s.sid in only
            for c in s.candidates for arm in H.ARMS]
    random.Random(seed).shuffle(runs)
    return runs


def smoke(seed: int, reps: int, only=None) -> list[dict]:
    out = []
    for order, (s, c, arm, rep) in enumerate(plan(seed, reps, only)):
        record = H.run(s, c, arm, repetition=rep, order=order, seed=seed)
        if problems := H.check_record(record):
            raise AssertionError(f"{s.sid}/{c.name}/{arm}: {problems}")
        out.append(record)
    return out


def write(records, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in records),
                    encoding="utf-8", newline="\n")


NONDETERMINISTIC = ("elapsed_s",)


def comparable(record: dict) -> dict:
    return {k: v for k, v in record.items() if k not in NONDETERMINISTIC}


def replay(path: Path) -> list[str]:
    import analyze
    old = analyze.load(path)
    seeds = {r["seed"] for r in old}
    reps = max(r["repetition"] for r in old) + 1
    only = {r["scenario"] for r in old}
    if len(seeds) != 1 or {r["phase"] for r in old} != {"smoke"}:
        return ["replay takes one smoke file with one seed"]
    new = smoke(seeds.pop(), reps, None if only == set(S.BY_ID) else only)
    if len(new) != len(old):
        return [f"{len(old)} runs recorded, {len(new)} replayed"]
    return [f"run {a['order']} ({a['scenario']}/{a['policy']}/{a['condition']}) differs"
            for a, b in zip(sorted(old, key=lambda r: r["order"]), new) if comparable(a) != comparable(b)]


def check_approval(doc) -> list[str]:
    if not isinstance(doc, dict):
        return ["an approval is a JSON object"]
    out = [f"missing {k}" for k in sorted(APPROVAL_FIELDS - set(doc))]
    if extra := sorted(set(doc) - APPROVAL_FIELDS):
        out.append(f"unknown fields {extra}")
    if not out:
        if not isinstance(doc["repetitions"], int) or not 1 <= doc["repetitions"] <= 50:
            out.append("repetitions is 1 to 50")
        if not isinstance(doc["max_cost_usd"], (int, float)) or doc["max_cost_usd"] <= 0:
            out.append("max_cost_usd is a positive number")
        if not set(doc["allowed_tools"]) <= {"verify_report", "feedback_start", "feedback_resolve"}:
            out.append("allowed_tools are the benchmark's MCP tools only")
        if not isinstance(doc["sampling"], dict) or "temperature" not in doc["sampling"] or \
                "effort" not in doc["sampling"]:
            out.append("sampling states the temperature (null where the API takes none) and the effort")
        if not isinstance(doc["pricing"], dict) or not isinstance(doc["limits"], dict) or \
                not isinstance(doc["final_authorization"], dict):
            out.append("pricing, limits and final_authorization are objects")
        if not str(doc["approved_by"]).strip() or not str(doc["approved_at"]).strip():
            out.append("approved_by and approved_at name the person and the time")
    return out


def live_plan(approval: dict, out: Path) -> dict:
    """The randomized, paired plan of a live phase: each (scenario, repetition) runs in both conditions, the order of
    the pair and of the pairs is random, every run on a fresh world and a fresh agent context."""
    rng = random.Random(f"{approval['approved_at']}:{approval['model']}")
    pairs = [(s.sid, rep) for rep in range(approval["repetitions"]) for s in S.SCENARIOS]
    rng.shuffle(pairs)
    runs = []
    for sid, rep in pairs:
        arms = list(H.ARMS)
        rng.shuffle(arms)
        runs += [{"order": len(runs), "scenario": sid, "repetition": rep, "condition": arm} for arm in arms]
    doc = {"approval": approval, "runs": runs, "prompts": {"task": "prompts/task.md", "control": "prompts/control.md",
                                                          "treatment": "prompts/treatment.md"},
           "server": {arm: f"python {HERE / 'bench.py'} serve --arm {arm} --world <fresh dir per run>"
                      for arm in H.ARMS}}
    out.mkdir(parents=True, exist_ok=True)
    (out / "plan.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
    return doc


def split_status(final: str) -> tuple[str, str | None]:
    """The report without its closing `STATUS:` line (prompts/task.md), and the claim that line makes."""
    lines = final.rstrip("\n").split("\n")
    if lines and lines[-1].strip().lower().startswith("status:"):
        said = lines[-1].split(":", 1)[1].strip().lower()
        return "\n".join(lines[:-1]).rstrip("\n"), "verified" if said == "verified" else "not_verified"
    return final, None


def record(run: dict) -> dict:
    """A live run's record: the transcript's facts as given, the label made here from the final report alone."""
    scenario = S.BY_ID[run["scenario"]]
    final, said = split_status(run["final_report"])
    run = dict(run, final_report=final, agent_claim=said or run.get("agent_claim") or "not_verified")
    with tempfile.TemporaryDirectory(prefix="fb-e2e-") as tmp, H.isolated(Path(tmp)) as world:
        labels = H.label(scenario, scenario.report, run["final_report"], run["agent_claim"], world)
    tools = list(run["tool_calls"])
    return {"schema": H.RECORD_V1, "phase": "live", "condition": run["condition"], "scenario": scenario.sid,
            "policy": f"agent:{run['model']}", "repetition": run["repetition"], "order": run["order"], "seed": None,
            "iteration_limit": S.ITERATION_LIMIT, "requirements": list(scenario.requirements),
            "attempts": len(run.get("revisions", [])), "rejected_attempts": int(run.get("rejected_attempts", 0)),
            "tool_calls": len(tools), "tools": tools, "elapsed_s": float(run["elapsed_s"]),
            "protocol": {"source": "transcript", "final_signal": run.get("final_signal")},
            "agent_claim": run["agent_claim"], "final_changed": run["final_report"] != scenario.report,
            "labels": labels, "tokens": run.get("tokens"), "cost_usd": run.get("cost_usd"),
            "cost_verifiable": bool(run.get("cost_verifiable")), "deviations": list(run.get("deviations", []))}


def serve(arm: str, directory: Path) -> int:
    """MCP over stdio for one condition (buddie.mcp.handle with the condition's tools only), on a fresh world."""
    from buddie import mcp
    tools = H.Tools(arm)
    with H.isolated(directory):
        for raw in sys.stdin.buffer:
            if not raw.strip():
                continue
            msg = json.loads(raw.decode("utf-8"))
            if msg.get("method") == "tools/list":
                reply = {"jsonrpc": "2.0", "id": msg.get("id"), "result": {"tools": tools.listed()}}
            elif msg.get("method") == "tools/call" and (msg.get("params") or {}).get("name") not in tools.allowed:
                reply = {"jsonrpc": "2.0", "id": msg.get("id"),
                         "error": {"code": -32602, "message": f"not a tool of the {arm} condition"}}
            else:
                reply = mcp.handle(msg)
            if reply is not None:  # MCP stdio is UTF-8 whatever the console's code page
                sys.stdout.buffer.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
                sys.stdout.buffer.flush()
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="bench.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("smoke")
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--seed", type=int, default=20261026)
    a.add_argument("--reps", type=int, default=1)
    sub.add_parser("replay").add_argument("file", type=Path)
    a = sub.add_parser("analyze")
    a.add_argument("file", type=Path)
    a.add_argument("summary", type=Path, nargs="?")
    a = sub.add_parser("serve")
    a.add_argument("--arm", choices=list(H.ARMS), required=True)
    a.add_argument("--world", type=Path, required=True)
    a = sub.add_parser("plan")
    a.add_argument("--approval", type=Path, required=True)
    a.add_argument("--out", type=Path, required=True)
    sub.add_parser("record").add_argument("--run", type=Path, required=True)
    args = p.parse_args(argv)
    if args.cmd == "smoke":
        records = smoke(args.seed, args.reps)
        write(records, args.out)
        side = args.out.with_name(args.out.stem + "-runtime.json")
        side.write_text(json.dumps(dict(H.runtime(), seed=args.seed, reps=args.reps, runs=len(records)), indent=1)
                        + "\n", encoding="utf-8", newline="\n")
        print(f"{len(records)} runs -> {args.out} (runtime: {side.name})")
        return 0
    if args.cmd == "replay":
        diffs = replay(args.file)
        print("\n".join(diffs) if diffs else "replay: every deterministic field matches")
        return 1 if diffs else 0
    if args.cmd == "analyze":
        import analyze
        return analyze.main([str(args.file)] + ([str(args.summary)] if args.summary else []))
    if args.cmd == "serve":
        return serve(args.arm, args.world)
    if args.cmd == "plan":
        try:
            approval = json.loads(args.approval.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            print(f"no approval: {error}", file=sys.stderr)
            return 2
        if problems := check_approval(approval):
            print("the live phase is not approved: " + "; ".join(problems), file=sys.stderr)
            return 2
        doc = live_plan(approval, args.out)
        print(f"{len(doc['runs'])} runs planned -> {args.out / 'plan.json'} (no model was called)")
        return 0
    if args.cmd == "record":
        print(json.dumps(record(json.loads(args.run.read_text(encoding="utf-8"))), sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
