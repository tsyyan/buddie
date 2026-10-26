"""The metrics of a set of run records (PROTOCOL.md, "Metrics"): exact numerators and denominators, per condition and
per scenario, paired comparisons, and how often the treatment's own signal agreed with the independent label.

Nothing here is a significance test: the smoke phase runs scripted candidates, not agents, and its counts describe
the harness, not an effect (PROTOCOL.md, "What the phases can and cannot show")."""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def ratio(k: int, n: int) -> dict:
    return {"k": k, "n": n, "rate": None if n == 0 else round(k / n, 4)}


def load(path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def condition_metrics(runs: list[dict]) -> dict:
    ok = [r for r in runs if r["labels"]["verified_task_success"]]
    costs = [r["cost_usd"] for r in runs]
    cost_known = all(c is not None and r["cost_verifiable"] for c, r in zip(costs, runs)) and runs
    rework = [r for r in runs if r["attempts"] > 1 or r["rejected_attempts"] > 0]
    times = [r["elapsed_s"] for r in ok]
    claims = defaultdict(lambda: defaultdict(int))
    for r in runs:
        for name, status in r["labels"]["claims"].items():
            claims[name][status] += 1
    return {
        "runs": len(runs),
        "verified_task_success": ratio(len(ok), len(runs)),
        "cost_per_verified_task_usd": (round(sum(costs) / len(ok), 6) if cost_known and ok else None),
        "cost_note": None if cost_known else "not verifiable: no provider billing for these runs",
        "time_to_verified_result_s": {"median": round(statistics.median(times), 6) if times else None,
                                      "n": len(times), "note": "harness wall clock, not a model's latency"},
        "rework": ratio(len(rework), len(runs)),
        "false_success_claims": ratio(sum(r["labels"]["false_success_claim"] for r in runs), len(runs)),
        "scope_violations": ratio(sum(bool(r["labels"]["scope_violations"]) for r in runs), len(runs)),
        "unnecessary_edits": ratio(sum(r["labels"]["unnecessary_edit"] for r in runs), len(runs)),
        "unsupported_final_assertions": sum(len(r["labels"]["independent"]["unsupported_assertions"]) for r in runs),
        "evidence_unavailable": sum(len(r["labels"]["independent"]["evidence_unavailable"]) for r in runs),
        "requirements": dict(sorted(_count(r["labels"]["requirements"] for r in runs).items())),
        "claims": {k: dict(sorted(v.items())) for k, v in sorted(claims.items())},
        "tool_calls": sum(r["tool_calls"] for r in runs),
        "attempts": sum(r["attempts"] for r in runs),
        "tokens": None if any(r["tokens"] is None for r in runs) else _tokens(runs),
    }


def _count(values) -> dict:
    out = defaultdict(int)
    for v in values:
        out[v] += 1
    return out


def _tokens(runs) -> dict:
    out = defaultdict(int)
    for r in runs:
        for k, v in r["tokens"].items():
            out[k] += v or 0
    return dict(out)


def paired(runs: list[dict]) -> dict:
    """Control vs treatment on the same (scenario, policy, repetition): concordant and discordant pairs."""
    by = defaultdict(dict)
    for r in runs:
        by[(r["scenario"], r["policy"], r["repetition"])][r["condition"]] = r["labels"]["verified_task_success"]
    cells = {"both": 0, "control_only": 0, "treatment_only": 0, "neither": 0, "unpaired": 0}
    for pair in by.values():
        if set(pair) != {"control", "treatment"}:
            cells["unpaired"] += 1
            continue
        c, t = pair["control"], pair["treatment"]
        cells["both" if c and t else "control_only" if c else "treatment_only" if t else "neither"] += 1
    return cells


SAYS_VERIFIED = {"control": "PASS", "treatment": "verified"}


def signal(runs: list[dict], condition: str) -> dict:
    """Did the condition's own last signal say verified (control: the last verify_report PASS; treatment: the
    chain's disposition `verified`) exactly when the independent label says success? The signal is what an
    orchestrator would act on; the label is what holds."""
    cells = {"verified_and_success": 0, "verified_but_not_success": 0, "not_verified_but_success": 0,
             "not_verified_and_not_success": 0}
    misses = []
    for r in runs:
        if r["condition"] != condition:
            continue
        said = r["protocol"].get("final_signal") == SAYS_VERIFIED[condition]
        ok = r["labels"]["verified_task_success"]
        key = ("verified_and_success" if said and ok else "verified_but_not_success" if said
               else "not_verified_but_success" if ok else "not_verified_and_not_success")
        cells[key] += 1
        if said != ok:
            misses.append({"scenario": r["scenario"], "policy": r["policy"], "signal": r["protocol"]["final_signal"],
                           "success": ok})
    return {"cells": cells, "disagreements": misses}


def summarize(runs: list[dict]) -> dict:
    by_condition = defaultdict(list)
    by_scenario = defaultdict(lambda: defaultdict(list))
    for r in runs:
        by_condition[r["condition"]].append(r)
        by_scenario[r["scenario"]][r["condition"]].append(r)
    return {
        "phases": sorted({r["phase"] for r in runs}),
        "conditions": {c: condition_metrics(rs) for c, rs in sorted(by_condition.items())},
        "scenarios": {s: {c: ratio(sum(r["labels"]["verified_task_success"] for r in rs), len(rs))
                          for c, rs in sorted(cs.items())} for s, cs in sorted(by_scenario.items())},
        "paired": paired(runs),
        "signal": {c: signal(runs, c) for c in SAYS_VERIFIED},
    }


def markdown(summary: dict) -> str:
    rows = ["| Metric | " + " | ".join(summary["conditions"]) + " |", "|---|" + "---|" * len(summary["conditions"])]

    def frac(m):
        return f"{m['k']}/{m['n']}"

    pick = [("Verified task success", lambda m: frac(m["verified_task_success"])),
            ("Cost per verified task (USD)", lambda m: m["cost_per_verified_task_usd"] or "not verifiable"),
            ("Time to verified result, median s (harness)", lambda m: m["time_to_verified_result_s"]["median"]),
            ("Rework", lambda m: frac(m["rework"])),
            ("False success claims", lambda m: frac(m["false_success_claims"])),
            ("Runs with scope violations", lambda m: frac(m["scope_violations"])),
            ("Unnecessary edits", lambda m: frac(m["unnecessary_edits"])),
            ("Unsupported final assertions (count)", lambda m: m["unsupported_final_assertions"]),
            ("Unavailable evidence (count)", lambda m: m["evidence_unavailable"]),
            ("Tool calls", lambda m: m["tool_calls"]),
            ("Tokens", lambda m: m["tokens"] or "none (no model)")]
    for name, f in pick:
        rows.append(f"| {name} | " + " | ".join(str(f(m)) for m in summary["conditions"].values()) + " |")
    for name, key in (("Signal says verified, label success", "verified_and_success"),
                      ("Signal says verified, label not success", "verified_but_not_success"),
                      ("Signal not verified, label success", "not_verified_but_success")):
        rows.append(f"| {name} | " + " | ".join(str(summary["signal"].get(c, {}).get("cells", {}).get(key, "-"))
                                               for c in summary["conditions"]) + " |")
    return "\n".join(rows) + "\n"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    summary = summarize(load(argv[0]))
    if len(argv) > 1:
        Path(argv[1]).write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    sys.stdout.write(markdown(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
