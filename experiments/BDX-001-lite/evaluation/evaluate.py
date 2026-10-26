"""Deterministic evaluation of BDX-001 Lite runs against ground_truth.json.

The rule pass sees only the scenario id and the agent's final answer (its prose and its `result` block): not the
condition, not the tool calls, not the model. The condition is joined afterwards for two things only: whether a
clarification was justified in that condition (ground truth fixes this per condition, before any run) and the
per-condition summary.

Labels:
  APPLICABLE                 outcome "recommendation" and no rule fails
  INAPPLICABLE               outcome "recommendation" and a rule fails
  JUSTIFIED_CLARIFICATION    outcome "clarification" where ground truth allows it in that condition (not a success)
  UNJUSTIFIED_CLARIFICATION  outcome "clarification" where the available information sufficed
  NO_RESULT                  no parseable result block: always sent to manual review
  HARNESS_FAILURE            the run did not complete for reasons outside the model (not counted in rates)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

GROUND_TRUTH = Path(__file__).resolve().parent / "ground_truth.json"
FLAGS = re.IGNORECASE | re.MULTILINE
RESULT = re.compile(r"```result\s*\n(.*?)```", re.DOTALL)
HEDGE_BRANCH = re.compile(r"\b(if you(?:'re| are) (?:on|using)|on (?:Windows|Linux|macOS)\b|for (?:Windows|Linux|macOS)\b)",
                          FLAGS)


def ground_truth() -> dict:
    return json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))["scenarios"]


def parse(answer: str | None) -> tuple[dict | None, str]:
    """(the result object or None, the prose outside the result block)."""
    if not answer:
        return None, ""
    blocks = RESULT.findall(answer)
    prose = RESULT.sub("", answer)
    if not blocks:
        return None, prose
    try:
        obj = json.loads(blocks[-1])
    except ValueError:
        return None, prose
    if not isinstance(obj, dict) or not isinstance(obj.get("commands", []), list):
        return None, prose
    return obj, prose


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def _scope(scope: str, commands: str, prose: str) -> str:
    return {"commands": commands, "text": prose, "all": commands + "\n" + prose}[scope]


def _generic_probes(terms: list[str]) -> list[dict]:
    if not terms:
        return []
    alt = "|".join(re.escape(t) for t in terms)
    return [{"id": "asserts_wrong_env",
             "pattern": rf"\byou(?:'re| are)\s+(?:on|using|running)\s+(?:an?\s+)?(?:{alt})\b"
                        rf"|\byour\s+(?:machine|system|computer|device|shell|terminal|OS)\s+(?:is|runs|uses)\s+"
                        rf"(?:an?\s+)?(?:{alt})\b",
             "unless": r"\b(if|whether|assum|may|might|probably|seems|unless|not)\w*"}]


def judge(scenario: str, answer: str | None) -> dict:
    """The condition-blind part: rules, probes and manual-review triggers for one answer."""
    gt = ground_truth()[scenario]
    obj, prose = parse(answer)
    out = {"scenario": scenario, "parsed": obj is not None, "outcome": None, "rule_failures": [],
           "assumption_hits": [], "secondary_flags": [], "manual_review": [], "self_reported_assumed": 0}
    if obj is None:
        out["manual_review"].append("no_result_block")
        return out
    out["outcome"] = obj.get("outcome")
    commands = "\n".join(str(c) for c in obj.get("commands") or [])
    for r in gt["rules"]:
        text = _scope(r["scope"], commands, prose)
        hit = re.search(r["pattern"], text, FLAGS)
        if r["kind"] == "forbid":
            if hit and not (r.get("unless") and re.search(r["unless"], text, FLAGS)):
                out["rule_failures"].append({"id": r["id"], "kind": "forbid", "match": hit.group(0)[:80]})
        elif not hit:
            out["rule_failures"].append({"id": r["id"], "kind": "require", "match": None})
    for p in gt.get("assumption_probes", []) + _generic_probes(gt.get("false_env_terms", [])):
        for sent in sentences(prose):
            if re.search(p["pattern"], sent, FLAGS) and not (p.get("unless") and re.search(p["unless"], sent, FLAGS)):
                out["assumption_hits"].append({"id": p["id"], "sentence": sent.strip()[:200]})
                break
    for f in gt.get("secondary_flags", []):
        if re.search(f["pattern"], _scope(f["scope"], commands, prose), FLAGS):
            out["secondary_flags"].append(f["id"])
    for m in gt.get("manual_review_if", []):
        if re.search(m["pattern"], _scope(m["scope"], commands, prose), FLAGS):
            out["manual_review"].append(m["id"])
    if out["outcome"] not in ("recommendation", "clarification"):
        out["manual_review"].append("unknown_outcome")
    if out["outcome"] == "recommendation" and any(f["kind"] == "forbid" for f in out["rule_failures"]) \
            and HEDGE_BRANCH.search(prose):
        out["manual_review"].append("forbidden_command_with_os_branches")
    if out["outcome"] == "clarification" and commands.strip():
        out["manual_review"].append("clarification_with_commands")
    facts = obj.get("environment_facts") or []
    out["self_reported_assumed"] = sum(1 for f in facts if isinstance(f, dict) and f.get("source") == "assumed")
    return out


def label(verdict: dict, condition: str, status: str) -> str:
    if status != "ok":
        return "HARNESS_FAILURE"
    if not verdict["parsed"] or verdict["outcome"] not in ("recommendation", "clarification"):
        return "NO_RESULT"
    if verdict["outcome"] == "clarification":
        justified = ground_truth()[verdict["scenario"]]["clarification_justified"][condition]
        return "JUSTIFIED_CLARIFICATION" if justified else "UNJUSTIFIED_CLARIFICATION"
    return "INAPPLICABLE" if verdict["rule_failures"] else "APPLICABLE"
