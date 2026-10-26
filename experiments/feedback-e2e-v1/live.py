"""The live pilot (PROTOCOL.md, "Live phase gate"): one fixed Claude model as the agent, through the Messages API,
with the benchmark's isolated tools only. Nothing runs without a completed approval manifest whose final
authorization a person filled in, an explicit `--execute`, and an API key in ANTHROPIC_API_KEY.

  python live.py check   --approval approval.pilot.json             preflight only: no request is sent
  python live.py execute --approval approval.pilot.json --out DIR   the pilot (paid API calls)

Cost enforcement (approval `limits`):
  - before every request: its worst case = (request bytes + TOOL_OVERHEAD tokens) x input price + max_tokens x
    output price (a token is at least one byte, and thinking is output, bounded by max_tokens). The request is sent
    only if the run's and the pilot's spend plus that worst case stay within their ceilings; otherwise the run stops
    with a `budget_stop` deviation (the pilot stops when the pilot ceiling would be crossed)
  - after every response: the cost from the provider's reported usage (input, output, cache write, cache read) at the
    approval's prices, added to the ledger. Cost is computed from reported usage, never estimated; the billed cost is
    not visible here (`cost_usd` null, `cost_verifiable` false; the ledger can be reconciled with the Console)
  - the pilot aborts if a response's cost exceeds the worst case checked for it, if usage is missing, or if the
    model that answered is not the approved one (no fallback model may answer)

Isolation: a fresh world, state dir, chain memory and conversation per run (harness.isolated); the agent's tools take
text only (no path, repo, store, URL or option: the adapter fills those from the world, as the server would get them
from an orchestrator); a process audit hook refuses every DNS lookup but the API host's, so neither buddie nor
anything else reaches the network. ANTHROPIC_BASE_URL and OAuth tokens are ignored: only the first-party API with an
API key, never a subscription session.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import harness as H
import scenarios as S

API_HOST = "api.anthropic.com"
API_URL = f"https://{API_HOST}/v1/messages"
API_VERSION = "2026-10-21"
TOOL_OVERHEAD = 2000   # tokens the API may add for tool use beyond the request's bytes (generous)


class PilotAbort(RuntimeError):
    """Isolation, measurement or budget enforcement failed: the pilot stops at once."""


# --- the approval manifest ------------------------------------------------------------------------------------------

PRICE_KEYS = {"input_per_mtok", "output_per_mtok", "cache_write_5m_per_mtok", "cache_read_per_mtok", "source",
              "checked_at"}
LIMIT_KEYS = {"max_cost_usd", "max_cost_per_run_usd", "max_tokens_per_call", "max_calls_per_run", "iteration_limit"}


def problems(approval: dict, *, execute: bool) -> list[str]:
    """What keeps the manifest from authorizing the pilot ([] when nothing does)."""
    import bench
    out = bench.check_approval(approval)
    if out:
        return out
    if set(approval["pricing"]) != PRICE_KEYS or not all(
            isinstance(approval["pricing"][k], (int, float)) and approval["pricing"][k] >= 0
            for k in PRICE_KEYS - {"source", "checked_at"}):
        out.append(f"pricing names {sorted(PRICE_KEYS)} with numeric prices")
    lim = approval["limits"]
    if set(lim) != LIMIT_KEYS:
        out.append(f"limits name {sorted(LIMIT_KEYS)}")
    else:
        if lim["max_cost_usd"] != approval["max_cost_usd"]:
            out.append("limits.max_cost_usd is the approved max_cost_usd")
        if lim["iteration_limit"] != S.ITERATION_LIMIT:
            out.append(f"limits.iteration_limit is the benchmark's {S.ITERATION_LIMIT}")
        if lim["max_cost_per_run_usd"] * approval["repetitions"] * len(S.SCENARIOS) * 2 > lim["max_cost_usd"] + 1e-9:
            out.append("the per-run ceiling times the runs exceeds the pilot ceiling")
    if not set(approval["allowed_tools"]) == {"verify_report", "feedback_start", "feedback_resolve"}:
        out.append("allowed_tools are the benchmark's three tools")
    if execute:
        fin = approval.get("final_authorization") or {}
        if not str(fin.get("authorized_by", "")).strip() or not str(fin.get("authorized_at", "")).strip():
            out.append("final_authorization is not filled in: a person must authorize the spend")
        if not os.environ.get("ANTHROPIC_API_KEY"):
            out.append("ANTHROPIC_API_KEY is not set (an API key; subscription sessions and base URLs are not used)")
    return out


# --- the network guard ----------------------------------------------------------------------------------------------

_ALLOWED: set = set()


def guard_network(allowed=(API_HOST,)) -> None:
    """Refuse every DNS lookup but `allowed` for the rest of the process (an audit hook cannot be removed)."""
    if _ALLOWED:
        _ALLOWED.clear()
        _ALLOWED.update(allowed)
        return
    _ALLOWED.update(allowed)

    def hook(event, args):
        if event == "socket.getaddrinfo" and args and args[0] not in _ALLOWED:
            raise PermissionError(f"network blocked by the benchmark: {args[0]!r}")
    sys.addaudithook(hook)


# --- the transport --------------------------------------------------------------------------------------------------

class Transport:
    """POST /v1/messages with an API key, first-party host only."""

    def __init__(self, key: str):
        self.key = key

    def send(self, body: dict) -> dict:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(API_URL, data=data, method="POST", headers={
            "content-type": "application/json", "x-api-key": self.key, "anthropic-version": API_VERSION})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=600) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                if error.code in (429, 500, 502, 503, 529) and attempt < 2:
                    time.sleep(float(error.headers.get("retry-after") or 2 ** (attempt + 2)))
                    continue
                raise PilotAbort(f"API error {error.code}: {error.read()[:300]!r}") from None


# --- the agent's tools ----------------------------------------------------------------------------------------------

def _tool(name, description, properties, required):
    return {"name": name, "description": description, "strict": True,
            "input_schema": {"type": "object", "additionalProperties": False, "properties": properties,
                             "required": required}}


TEXT = {"type": "string", "description": "the full text"}
TOOLS = {
    "control": [_tool("verify_report", "Check a text's quotes and anchors; returns a receipt (outcome and findings).",
                      {"text": TEXT}, ["text"])],
    "treatment": [
        _tool("feedback_start", "Check the report and open a feedback chain; returns the feedback and the state.",
              {"text": TEXT}, ["text"]),
        _tool("feedback_resolve", "Hand in one corrected text for the chain's open feedback; returns the decision, "
              "the next feedback and the state.",
              {"corrected_text": TEXT,
               "execution": {"type": "string", "enum": ["none", "succeeded", "failed", "unknown"],
                             "description": "what happened to any action outside the text"}},
              ["corrected_text", "execution"]),
    ],
}


class Adapter:
    """One run's tools for the agent: text in, the benchmark's MCP tools behind, options from the world."""

    def __init__(self, arm: str, scenario, world):
        self.arm, self.scenario, self.world = arm, scenario, world
        self.tools = H.Tools(arm)
        self.steps, self.chain, self.feedback, self.accepted = [], None, None, scenario.report
        self.state, self.verifies, self.resolves, self.rejected, self.drafts = None, 0, 0, 0, []

    def call(self, name: str, args: dict) -> tuple[dict, bool]:
        from buddie import repair
        if name == "verify_report" and self.arm == "control":
            if self.verifies >= 1 + S.ITERATION_LIMIT:
                return {"error": "the verification budget is spent"}, True
            self.verifies += 1
            if self.verifies > 1:
                self.drafts.append(args["text"])
            got, err = self.tools.call("verify_report", dict(self.world.options(), receipt="v1", text=args["text"]))
            self.steps.append({"tool": name, "outcome": None if err else got["predicate"]["verification"]["outcome"]})
            return got, err
        if name == "feedback_start" and self.arm == "treatment":
            if self.chain:
                return {"error": "the chain is started already"}, True
            got, err = self.tools.call("feedback_start", dict(
                self.world.options(), text=args["text"], iteration_limit=S.ITERATION_LIMIT,
                requirements=list(self.scenario.requirements)))
            if not err:
                self.chain, self.feedback, self.state = got["chain"], got["feedback"], got["state"]
                self.accepted = args["text"]
            self.steps.append({"tool": name, "disposition": None if err else got["state"]["disposition"]})
            return got, err
        if name == "feedback_resolve" and self.arm == "treatment":
            if not self.chain:
                return {"error": "call feedback_start first"}, True
            text = args["corrected_text"]
            self.resolves += 1
            self.drafts.append(text)
            sub = repair.submission(self.feedback, self.accepted, text, execution=args["execution"])
            got, err = self.tools.call("feedback_resolve", {"chain": self.chain, "feedback": self.feedback,
                                                            "submission": sub, "original_text": self.accepted,
                                                            "corrected_text": text})
            if err:
                self.steps.append({"tool": name, "error": got.get("code")})
                return got, err
            d = got["decision"]
            self.rejected += d["status"] == "rejected"
            self.feedback, self.state = got["feedback"], got["state"]
            if d["status"] == "accepted":
                self.accepted = text
            self.steps.append({"tool": name, "status": d["status"], "rejection": d["rejection"],
                               "disposition": got["state"]["disposition"]})
            return got, err
        return {"error": f"{name} is not a tool of this run"}, True

    def final_signal(self):
        if self.arm == "control":
            return self.steps[-1]["outcome"] if self.steps else None
        return self.state["disposition"] if self.state else None


# --- one run --------------------------------------------------------------------------------------------------------

def prompt(arm: str, scenario, world) -> tuple[str, str]:
    here = Path(__file__).resolve().parent / "prompts"
    reqs = (", ".join(f"a supported {r['check']} claim starting “{r['subject_prefix']}”" for r in scenario.requirements)
            or "none stated")
    task = (here / "task.md").read_text(encoding="utf-8").replace("{requirements}", reqs).replace(
        "{report}", scenario.report)
    system = (here / f"{arm}.md").read_text(encoding="utf-8").replace("{iteration_limit}", str(S.ITERATION_LIMIT))
    return system, task


def cost(usage: dict, prices: dict) -> float:
    return (usage.get("input_tokens", 0) * prices["input_per_mtok"]
            + usage.get("output_tokens", 0) * prices["output_per_mtok"]
            + (usage.get("cache_creation_input_tokens") or 0) * prices["cache_write_5m_per_mtok"]
            + (usage.get("cache_read_input_tokens") or 0) * prices["cache_read_per_mtok"]) / 1e6


class Ledger:
    def __init__(self, approval: dict, path: Path | None):
        self.approval, self.path, self.total = approval, path, 0.0

    def entry(self, row: dict) -> None:
        if self.path:
            with self.path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(row, sort_keys=True) + "\n")


def run_one(item: dict, approval: dict, transport, ledger: Ledger) -> dict:
    """One planned run; returns its record (bench's schema) with the usage it spent."""
    import bench
    scenario, arm = S.BY_ID[item["scenario"]], item["condition"]
    lim, prices, model = approval["limits"], approval["pricing"], approval["model"]
    deviations, tokens, spent, calls = [], {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}, 0.0, 0
    began, final_text = time.perf_counter(), ""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="fb-live-") as tmp, H.isolated(Path(tmp)) as world:
        adapter = Adapter(arm, scenario, world)
        system, task = prompt(arm, scenario, world)
        messages = [{"role": "user", "content": task}]
        while True:
            if calls >= lim["max_calls_per_run"]:
                deviations.append("call_cap: the run reached max_calls_per_run")
                break
            body = {"model": model, "max_tokens": lim["max_tokens_per_call"], "system": system,
                    "tools": TOOLS[arm], "messages": messages,
                    "output_config": {"effort": approval["sampling"]["effort"]}}
            worst = ((len(json.dumps(body).encode("utf-8")) + TOOL_OVERHEAD) * prices["input_per_mtok"]
                     + lim["max_tokens_per_call"] * prices["output_per_mtok"]) / 1e6
            if ledger.total + worst > lim["max_cost_usd"]:
                raise PilotAbort(f"the pilot ceiling would be crossed: spent {ledger.total:.4f} + worst {worst:.4f}")
            if spent + worst > lim["max_cost_per_run_usd"]:
                deviations.append(f"budget_stop: run spent {spent:.4f} + worst {worst:.4f} > per-run ceiling")
                break
            resp = transport.send(body)
            calls += 1
            usage = resp.get("usage")
            if not isinstance(usage, dict) or "input_tokens" not in usage or "output_tokens" not in usage:
                raise PilotAbort("a response carried no usage: measurement failed")
            if resp.get("model") != model:
                raise PilotAbort(f"answered by {resp.get('model')!r}, not the approved {model!r}")
            c = cost(usage, prices)
            if c > worst + 1e-9:
                raise PilotAbort(f"a response cost {c:.6f} > its checked worst case {worst:.6f}")
            spent += c
            ledger.total += c
            tokens["input"] += usage["input_tokens"]
            tokens["output"] += usage["output_tokens"]
            tokens["cache_write"] += usage.get("cache_creation_input_tokens") or 0
            tokens["cache_read"] += usage.get("cache_read_input_tokens") or 0
            ledger.entry({"order": item["order"], "scenario": scenario.sid, "condition": arm, "call": calls,
                          "request_id": resp.get("id"), "usage": usage, "cost_usd": round(c, 6),
                          "worst_case_usd": round(worst, 6), "pilot_total_usd": round(ledger.total, 6)})
            content = resp.get("content") or []
            messages.append({"role": "assistant", "content": content})  # append-only: blocks passed back unchanged
            stop = resp.get("stop_reason")
            if stop == "tool_use":
                results = []
                for block in content:
                    if block.get("type") != "tool_use":
                        continue
                    got, err = adapter.call(block["name"], block.get("input") or {})
                    results.append({"type": "tool_result", "tool_use_id": block["id"], "is_error": bool(err),
                                    "content": json.dumps(got, ensure_ascii=False)})
                messages.append({"role": "user", "content": results})
                continue
            final_text = "".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
            if stop != "end_turn":
                deviations.append(f"stop_reason: {stop}")
            break
        final, said = bench.split_status(final_text)
        if not final:
            deviations.append("no_final_report: the run ended without one; the report is judged as handed over")
            final = scenario.report
        labels = H.label(scenario, scenario.report, final, said or "not_verified", world)
        if arm == "treatment" and adapter.chain and final != adapter.accepted:
            deviations.append("hand_in_differs_from_chain: the final report is not the chain's last accepted text")
        acceptance = None
        if arm == "treatment" and adapter.chain:  # amendment A1 (PROTOCOL.md): recorded, never the label
            from buddie import chains, repair
            read = chains.load(adapter.chain)
            got = repair.accept(read.records, final)
            acceptance = {"accepted": got["accepted"], "reason": got["reason"], "basis": read.basis}
    tools = [s["tool"] for s in adapter.steps]
    record = {"schema": H.RECORD_V1, "phase": "live", "condition": arm, "scenario": scenario.sid,
              "policy": f"agent:{model}", "repetition": item["repetition"], "order": item["order"], "seed": None,
              "iteration_limit": S.ITERATION_LIMIT, "requirements": list(scenario.requirements),
              "attempts": len(adapter.drafts), "rejected_attempts": adapter.rejected, "tool_calls": len(tools),
              "tools": tools, "elapsed_s": round(time.perf_counter() - began, 3),
              "protocol": {"source": "live", "steps": adapter.steps, "final_signal": adapter.final_signal(),
                           "acceptance": acceptance, "api_calls": calls, "usage_cost_usd": round(spent, 6)},
              "agent_claim": said or "not_verified", "final_changed": final != scenario.report, "labels": labels,
              "tokens": tokens, "cost_usd": None, "cost_verifiable": False, "deviations": deviations}
    if problems_ := H.check_record(record):
        raise PilotAbort(f"a record does not hold: {problems_}")
    return record


def pilot(approval: dict, out: Path, transport, *, require_clean: bool = True) -> dict:
    """Every planned run in order; stops at the first PilotAbort, keeping what ran and why it stopped.
    require_clean: refuse uncommitted changes under buddie/ (always on from the command line; tests of the runner
    itself turn it off so that they do not depend on the working tree)."""
    import bench
    out.mkdir(parents=True, exist_ok=True)
    runtime = H.runtime()
    if runtime["buddie_file"] != "buddie/__init__.py" or (require_clean and runtime["buddie_dirty"] is not False):
        raise PilotAbort(f"isolation: the buddie measured is not this checkout's clean code ({runtime})")
    plan = bench.live_plan(approval, out)
    ledger = Ledger(approval, out / "ledger.jsonl")
    records, status = [], "complete"
    try:
        for item in plan["runs"]:
            records.append(run_one(item, approval, transport, ledger))
            bench.write(records, out / "live.jsonl")
    except PilotAbort as error:
        status = f"aborted: {error}"
    summary = {"status": status, "runs_planned": len(plan["runs"]), "runs_recorded": len(records),
               "usage_cost_usd": round(ledger.total, 6), "runtime": runtime}
    (out / "status.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8", newline="\n")
    return summary


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="live.py")
    p.add_argument("cmd", choices=["check", "execute"])
    p.add_argument("--approval", type=Path, required=True)
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)
    approval = json.loads(args.approval.read_text(encoding="utf-8"))
    found = problems(approval, execute=args.cmd == "execute")
    if found:
        print("not authorized: " + "; ".join(found), file=sys.stderr)
        return 2
    if args.cmd == "check":
        print("the manifest is complete for planning; execution also needs final_authorization, --out and the key")
        return 0
    if not args.out:
        print("--out is required", file=sys.stderr)
        return 2
    guard_network()
    summary = pilot(approval, args.out, Transport(os.environ["ANTHROPIC_API_KEY"]))
    print(json.dumps(summary, indent=1))
    return 0 if summary["status"] == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())
