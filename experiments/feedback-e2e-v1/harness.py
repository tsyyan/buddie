"""Runs of the benchmark (PROTOCOL.md): the two conditions' tool adapters, one isolated world per run, the
independent validator, and the metric record of each run (metrics.schema.json).

  control    verification only: `verify_report` (receipt-v1) on the report and on every revision the author makes
  treatment  Verification Feedback v1: `feedback_start` on the report, `feedback_resolve` on every revision

Both conditions reach buddie through the local MCP server's own JSON-RPC handler (buddie.mcp.handle), with the same
world, the same check options and the same repair budget; each condition sees only its own tools (`ARMS`).

The validator re-verifies the final report itself (a fresh verify run in the harness, not the agent's and not the
chain's) and applies the scenario's hand-written ground truth (scenarios.py). A run is a verified task success only
when the ground truth holds, nothing outside the defect's lines changed, and the author did not claim verified
completion that the ground truth does not support. The author's claim, the feedback's disposition and the decision
are recorded, never used as the label."""
from __future__ import annotations

import contextlib
import difflib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:  # this checkout's buddie, never an installed copy (PROTOCOL.md, "Runtime")
    sys.path.insert(0, str(ROOT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import scenarios as S  # noqa: E402
import world as W  # noqa: E402

RECORD_V1 = "https://github.com/tsyyan/buddie/experiments/feedback-e2e-v1#run-record-v1"
ARMS = {"control": ("verify_report",), "treatment": ("feedback_start", "feedback_resolve")}


def runtime() -> dict:
    """What the runs ran on: the buddie module actually imported, its commit, Python and the OS."""
    import buddie
    try:
        commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                                check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "buddie"],
                                    capture_output=True, text=True, check=True).stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = None, None
    where = Path(buddie.__file__).resolve()
    # relative to this checkout (no home directory in committed results); anything else is named as outside it
    shown = where.relative_to(ROOT).as_posix() if where.is_relative_to(ROOT) else f"OUTSIDE THIS CHECKOUT: {where.name}"
    return {"buddie_version": buddie.__version__, "buddie_file": shown,
            "buddie_commit": commit, "buddie_dirty": dirty, "python": platform.python_version(),
            "platform": platform.platform()}


class Tools:
    """One condition's tools: MCP tools/call through buddie.mcp.handle, refused outside the condition's set."""

    def __init__(self, arm: str):
        self.arm, self.allowed, self.calls = arm, ARMS[arm], []

    def listed(self) -> list[dict]:
        from buddie import mcp
        return [t for t in mcp.TOOLS if t["name"] in self.allowed]

    def call(self, name: str, arguments: dict) -> tuple[dict, bool]:
        from buddie import mcp
        self.calls.append(name)
        if name not in self.allowed:
            return {"error": f"{name} is not a tool of the {self.arm} condition", "code": "not_offered"}, True
        reply = mcp.handle({"jsonrpc": "2.0", "id": len(self.calls), "method": "tools/call",
                            "params": {"name": name, "arguments": arguments}})
        result = reply["result"]
        return result["structuredContent"], result["isError"]


@contextlib.contextmanager
def isolated(root: Path):
    """A run's own world, state dir, journal and chain memory: nothing carries over from another run."""
    from buddie import chains
    saved = {k: os.environ.get(k) for k in ("BUDDIE_STATE", "BUDDIE_LOG", "BUDDIE_FETCH", "VERBATIM_STORE",
                                            "BUDDIE_DEFAULT_REPOS")}
    known = dict(chains._KNOWN)
    chains._KNOWN.clear()
    world = W.build(root / "world")
    os.environ.update(BUDDIE_STATE=str(root / "state"), BUDDIE_LOG=str(root / "journal.jsonl"), BUDDIE_FETCH="0",
                      VERBATIM_STORE=str(world.store), BUDDIE_DEFAULT_REPOS="none")
    try:
        with W.github_fixture():
            yield world
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        chains._KNOWN.clear()
        chains._KNOWN.update(known)


def remove(path: Path) -> None:
    """Remove a run's directory, read-only files too (git's objects on Windows)."""
    def retry(func, name, _exc):
        os.chmod(name, stat.S_IWRITE)
        func(name)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry)
    else:
        shutil.rmtree(path, onerror=retry)


# --- the independent validator ------------------------------------------------------------------------------------

def scope_violations(original: str, final: str, editable: frozenset) -> list[int]:
    """1-based lines of `original` changed, deleted or inserted next to outside `editable`; `buddie:` lines added
    next to any line are disclosures, not edits."""
    a, b, out = original.splitlines(), final.splitlines(), set()
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        added = [line for line in b[j1:j2] if not S.DISCLOSURE.match(line)]
        if op in ("replace", "delete"):
            out |= {n for n in range(i1 + 1, i2 + 1) if n not in editable}
            if op == "replace" and not any(n in editable for n in range(i1 + 1, i2 + 1)) and not added:
                out -= set(range(i1 + 1, i2 + 1))  # only disclosures replaced nothing of the original
        elif added and not ({i1, i1 + 1} & editable):
            out.add(i1 + 1 if i1 < len(a) else len(a))
    return sorted(out)


def independent_check(world, text: str, requirements=()) -> dict:
    """A fresh verification of `text` in the harness (not the agent's, not the chain's): its outcome, coverage, the
    claims it could not support, the evidence it could not read, and the task requirements' status in it."""
    from buddie import feedback as fb, mcp, receipts, repair
    got = repair.reverify(text, name="final", **mcp._checking(mcp.check_options(world.options())))
    receipt = receipts.v1(got)
    pred = receipt["predicate"]
    lines = text.splitlines()

    def disclosed_near(n):
        return any(S.DISCLOSURE.match(lines[k]) for k in range(max(0, n - 2), min(len(lines), n + 2)))

    findings = pred["verification"]["findings"]
    unsupported = [f"{f['check']}:{f['subject']}" for f in findings
                   if f["fact"] not in ("supported", "no_claim") and not (f.get("line") and disclosed_near(f["line"]))]
    return {"outcome": pred["verification"]["outcome"], "coverage": pred["scope"]["coverage"],
            "unsupported_assertions": unsupported,
            "evidence_unavailable": [f"{f['check']}:{f['subject']}" for f in findings
                                     if f["reason"] in ("source_unavailable", "uncheckable", "not_computed",
                                                        "unsupported")],
            "requirements": (fb.task_status(fb.check_requirements(list(requirements)), findings)["status"]
                             if requirements else "not_stated")}


def label(scenario, original: str, final: str, claim: str, world) -> dict:
    """The run's independent label (module docstring)."""
    truth = scenario.assertions_hold(final)
    facts_right = all(truth.values())
    scope = scope_violations(original, final, scenario.editable)
    unnecessary = not scenario.editable and final != original
    false_success = claim == "verified" and not (scenario.completable and facts_right)
    check = independent_check(world, final, scenario.requirements)
    requirements = check["requirements"]
    return {"truth": truth, "facts_right": facts_right, "scope_violations": scope, "unnecessary_edit": unnecessary,
            "false_success_claim": false_success, "claims": {c.name: c.status(final) for c in scenario.claims},
            "independent": check, "requirements": requirements,
            "verified_task_success": facts_right and not scope and not unnecessary and not false_success
            and requirements != "unmet"}


# --- the two conditions -------------------------------------------------------------------------------------------

def _control(tools, scenario, world, revisions) -> dict:
    args = dict(world.options(), receipt="v1")
    first, err = tools.call("verify_report", dict(args, text=scenario.report))
    steps = [{"tool": "verify_report", "outcome": None if err else first["predicate"]["verification"]["outcome"]}]
    for text, _execution in revisions:
        got, err = tools.call("verify_report", dict(args, text=text))
        steps.append({"tool": "verify_report", "outcome": None if err else got["predicate"]["verification"]["outcome"]})
    return {"steps": steps, "initial_outcome": steps[0]["outcome"], "rejected": 0,
            "final_signal": steps[-1]["outcome"]}


def _treatment(tools, scenario, world, revisions) -> dict:
    from buddie import repair
    started, err = tools.call("feedback_start", dict(world.options(), text=scenario.report,
                                                     iteration_limit=S.ITERATION_LIMIT,
                                                     requirements=list(scenario.requirements)))
    if err:
        return {"steps": [{"tool": "feedback_start", "error": started.get("code")}], "initial_outcome": None,
                "rejected": 0, "final_signal": None, "terminated": None}
    chain, feedback, previous = started["chain"], started["feedback"], scenario.report
    steps = [{"tool": "feedback_start", "disposition": started["state"]["disposition"],
              "actions": [a["operation"] for a in feedback["recommended_actions"]]}]
    state, rejected = started["state"], 0
    for text, execution in revisions:
        sub = repair.submission(feedback, previous, text, execution=execution)
        got, err = tools.call("feedback_resolve", {"chain": chain, "feedback": feedback, "submission": sub,
                                                   "original_text": previous, "corrected_text": text})
        if err:
            steps.append({"tool": "feedback_resolve", "error": got.get("code")})
            continue
        d = got["decision"]
        rejected += d["status"] == "rejected"
        steps.append({"tool": "feedback_resolve", "status": d["status"], "rejection": d["rejection"],
                      "outcome": d["outcome"], "resolved": sorted(set(d["resolved"].values())),
                      "disposition": got["state"]["disposition"], "task": got["state"]["task"],
                      "basis": got["basis"]})
        state, feedback = got["state"], got["feedback"]
        if d["status"] == "accepted":
            previous = text
    return {"steps": steps, "initial_outcome": started["feedback"]["source_receipt"]["outcome"],
            "rejected": rejected, "final_signal": state["disposition"], "task": state["task"],
            "terminated": state["terminal"], "iterations": state["iteration"]}


def run(scenario, candidate, arm: str, *, phase: str = "smoke", repetition: int = 0, order: int = 0,
        seed: int | None = None, workdir: Path | None = None) -> dict:
    """One run: a fresh world, the condition's protocol with the candidate's revisions, and its record."""
    base = Path(tempfile.mkdtemp(prefix="fb-e2e-", dir=workdir))
    try:
        with isolated(base) as world:
            tools = Tools(arm)
            began = time.perf_counter()
            protocol = (_control if arm == "control" else _treatment)(tools, scenario, world, candidate.revisions)
            elapsed = time.perf_counter() - began
            final = candidate.revisions[-1][0] if candidate.revisions else scenario.report
            labels = label(scenario, scenario.report, final, candidate.claim, world)
    finally:
        remove(base)
    return {"schema": RECORD_V1, "phase": phase, "condition": arm, "scenario": scenario.sid,
            "policy": f"scripted:{candidate.name}", "repetition": repetition, "order": order, "seed": seed,
            "iteration_limit": S.ITERATION_LIMIT, "requirements": list(scenario.requirements),
            "attempts": len(candidate.revisions), "rejected_attempts": protocol["rejected"],
            "tool_calls": len(tools.calls), "tools": list(tools.calls), "elapsed_s": round(elapsed, 6),
            "protocol": protocol, "agent_claim": candidate.claim, "final_changed": final != scenario.report,
            "labels": labels, "tokens": None, "cost_usd": None, "cost_verifiable": False, "deviations": []}


def check_record(r: dict) -> list[str]:
    """What is wrong with a run record (metrics.schema.json, plus what a schema cannot say); [] when it holds."""
    out = []
    need = {"schema", "phase", "condition", "scenario", "policy", "repetition", "order", "seed", "iteration_limit",
            "requirements", "attempts", "rejected_attempts", "tool_calls", "tools", "elapsed_s", "protocol",
            "agent_claim", "final_changed", "labels", "tokens", "cost_usd", "cost_verifiable", "deviations"}
    if set(r) != need:
        return [f"fields {sorted(set(r) ^ need)}"]
    if r["schema"] != RECORD_V1 or r["phase"] not in ("smoke", "live") or r["condition"] not in ARMS:
        out.append("schema, phase or condition")
    if r["scenario"] not in S.BY_ID:
        out.append("unknown scenario")
    if not set(r["tools"]) <= set(ARMS[r["condition"]]) | {"verify_report", "feedback_start", "feedback_resolve"}:
        out.append("tools outside the benchmark")
    if r["tool_calls"] != len(r["tools"]):
        out.append("tool_calls is not the number of tools called")
    lab = r["labels"]
    expect = (lab["facts_right"] and not lab["scope_violations"] and not lab["unnecessary_edit"]
              and not lab["false_success_claim"] and lab["requirements"] != "unmet")
    if lab["verified_task_success"] != expect:
        out.append("verified_task_success does not follow from the labels")
    if r["phase"] == "smoke" and (r["tokens"] is not None or r["cost_usd"] is not None):
        out.append("a smoke run calls no model: tokens and cost are null")
    if r["cost_usd"] is not None and not r["cost_verifiable"]:
        out.append("a cost that is not verifiable is reported as null")
    return out
