"""Verification feedback v1: what a receipt-v1 asks of whoever wrote the text, as data an agent may act on.

A receipt says what the checks established (receipts.py). Feedback reads one receipt-v1 and says, finding by
finding, what kind of problem each one is and, where the author of the text can correct it, one bounded corrective
action. It is derived from the receipt and from nothing else: it runs no check, reads no evidence, fetches nothing,
and the same receipt with the same iteration gives the same bytes (`dumps`).

Feedback is advice, never authority:
  - it changes no receipt and no verdict: `source_receipt` repeats the receipt's outcome and coverage as they are, so
    GAPS, EMPTY, FAIL or UNKNOWN stay what they are; only a new receipt, of a new text, can say PASS
  - it executes nothing and grants nothing: an agent that acts on it acts within its own permissions
  - every evidence reference in it is copied from the receipt (none is made up), with how far it is bound
  - its identity is the sha256 of its own canonical bytes, so a changed field is a different (unknown) feedback;
    it is not signed, like the receipt: `problems(fb, receipt)` checks that it is the receipt's feedback, not who
    made either

Each finding gets one condition, never folded into a generic failure:

  verified          the check supported the claim (fact supported)
  no_claim          checked, and the text claims nothing there (a title in quotation marks)
  missing_evidence  the claim cites nothing readable: no source, source unavailable, a work claim with no evidence
  invalid_evidence  the evidence named does not match: an anchor's digest or commit is not the bytes'; the words are
                    only in a copy, not in the cited page; text in an anchor's place that is no anchor
  failed            the evidence was read and contradicts the claim (a quote or number not in its source, a PR,
                    CI run, command or work claim that is otherwise than stated)
  inconclusive      read, but not decided: an uncertain miss, a number without its context, words only in hidden
                    markup
  unavailable       buddie could not check it here (no repo, offline, a fact= anchor it never computes) or does not
                    know the verdict: nothing the author can fix by editing; say it when passing the text on

Dispositions (the whole feedback's state; every one but repair_requested is terminal):

  repair_requested         actionable findings, and the repair budget is not spent
  verified                 the receipt's outcome is PASS: nothing to repair (PASS is about the checks that ran, not
                           about the text being true; see source_receipt.coverage)
  nothing_verified         the receipt's outcome is EMPTY or NOT_RUN: nothing was checked, so nothing passed
  not_actionable           not PASS, and no finding is one the author can correct by editing (only unavailable or
                           unknown checks)
  budget_exhausted         actionable findings remain and no repair is left (iteration == iteration_limit)
  reconciliation_required  an external action's outcome is unknown and the text still does not verify: observe the
                           state before anything is repeated (repair.py sets it)

The repair budget is finite: `iteration_limit` defaults to 1 (one corrected text, then a terminal disposition) and
can be at most MAX_LIMIT. Nothing here retries; repair.py takes one submission per feedback.
"""
from __future__ import annotations

import hashlib
import re

from buddie import core, receipts

V1 = "https://github.com/tsyyan/buddie#feedback-v1"
DEFAULT_LIMIT = 1
MAX_LIMIT = 3
CONDITIONS = ("verified", "no_claim", "missing_evidence", "invalid_evidence", "failed", "inconclusive", "unavailable")
DISPOSITIONS = ("repair_requested", "verified", "nothing_verified", "not_actionable", "budget_exhausted",
                "reconciliation_required")
TERMINAL = frozenset(DISPOSITIONS) - {"repair_requested"}
NOT_ACTIONABLE = ("verified", "no_claim", "verifier_unavailable", "unrecognized_verdict", "unlocated")
NUMBERS_RANK = {"off": 0, "gap": 1, "fail": 2}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^sha256:[0-9a-f]{64}$")
# checks whose claim is about an effect in the world (a PR, a CI run, a command): an agent "fixing" one may be tempted
# to act again (merge, re-run), which may not be idempotent
EXTERNAL = frozenset({core.Check.PR_ANCHOR.value, core.Check.CI_ANCHOR.value, core.Check.RUN_ANCHOR.value})
PARAGRAPH = frozenset({core.Check.QUOTE.value, core.Check.NUMBER.value})  # a quote's line is its paragraph's first

# operation -> what the corrected text must do; the requirements are fixed per operation, never built from a message
OPERATIONS = {
    "correct_claim": ("Make the claim say what its cited source says, or remove the claim.",
                      "Do not change the source the claim cites to one that was not read."),
    "refresh_anchor": ("Replace the anchor with one that names the bytes or commit as they are now, or remove the "
                       "claim it supports.",),
    "cite_readable_source": ("Cite a source buddie can read (a link to the page, snapshotted with `snap`), or "
                             "remove the claim.",),
    "anchor_work_claim": ("Anchor the work claim (`pr:`, `ci:`, `run:`, a queue row), or remove the claim.",),
    "requote_from_source": ("Copy the words character for character from the visible text of the cited page "
                            "(buddie source_text), or remove the claim.",),
    "fix_anchor_form": ("Write the anchor in a form buddie checks (path#sha256, path@commit, pr:, ci:, run:), or "
                        "remove it.",),
    "reconcile_external_state": ("Observe the current state of the PR, CI run or command and state it as observed.",
                                 "Do not repeat the action (merge, re-run, push) before its current state is "
                                 "observed: it may not be idempotent."),
}


class InvalidReceipt(ValueError):
    """A receipt that is not a consistent receipt-v1: no feedback is made from it."""


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def receipt_id(receipt: dict) -> str:
    """The identity of a receipt: the sha256 of its canonical JSON (receipts.dumps)."""
    return digest(receipts.dumps(receipt).encode("utf-8"))


def text_digest(text: str) -> str:
    """The sha256 of a text as verify names it in a receipt's subject (UTF-8), hex only."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def finding_id(index: int, finding: dict) -> str:
    """A finding's identity: its position in the receipt and its canonical JSON, as the receipt holds it."""
    return digest(receipts.dumps({"index": index, "finding": finding}).encode("utf-8"))


def condition(finding: dict) -> str:
    """The condition of a receipt-v1 finding (the module's docstring), from its check, fact and reason only."""
    fact, reason, check = finding["fact"], finding["reason"], finding["check"]
    if fact == core.Fact.SUPPORTED.value:
        return "verified"
    if fact == core.Fact.NO_CLAIM.value:
        return "no_claim"
    if fact == core.Fact.CONTRADICTED.value:
        broken_ref = reason == core.ReasonCode.BROKEN.value and check in (core.Check.FILE_ANCHOR.value,
                                                                          core.Check.COMMIT_ANCHOR.value)
        return "invalid_evidence" if broken_ref else "failed"
    if fact == core.Fact.UNDETERMINED.value:
        if reason in (core.ReasonCode.SOURCE_UNAVAILABLE.value, core.ReasonCode.NO_SOURCE.value,
                      core.ReasonCode.UNSUPPORTED.value):
            return "missing_evidence"
        if reason in (core.ReasonCode.ONLY_IN_COPY.value, core.ReasonCode.NOT_AN_ANCHOR.value):
            return "invalid_evidence"
        if reason in (core.ReasonCode.AMBIGUOUS_MISS.value, core.ReasonCode.VALUE_WITHOUT_CONTEXT.value,
                      core.ReasonCode.ONLY_HIDDEN.value):
            return "inconclusive"
    return "unavailable"  # uncheckable, not computed, an unknown verdict or reason: never taken for anything else


def operation(finding: dict, cond: str) -> str | None:
    """The one corrective operation for a finding of condition `cond`, or None when the author cannot correct it."""
    check = finding["check"]
    if cond in ("verified", "no_claim", "unavailable"):
        return None
    if check in EXTERNAL and cond in ("failed", "invalid_evidence"):
        return "reconcile_external_state"
    if cond == "failed":
        return "correct_claim"
    if cond == "invalid_evidence":
        if finding["reason"] == core.ReasonCode.NOT_AN_ANCHOR.value:
            return "fix_anchor_form"
        if finding["reason"] == core.ReasonCode.ONLY_IN_COPY.value:
            return "requote_from_source"
        return "refresh_anchor"
    if cond == "missing_evidence":
        return "anchor_work_claim" if check == core.Check.WORK_CLAIM.value else "cite_readable_source"
    return "requote_from_source"  # inconclusive


def _not_actionable(finding: dict, cond: str) -> str | None:
    if cond in ("verified", "no_claim"):
        return cond
    if cond == "unavailable":
        return "unrecognized_verdict" if finding["fact"] == core.Fact.UNRECOGNIZED.value else "verifier_unavailable"
    if finding.get("line") is None:
        return "unlocated"  # no line to scope a correction to: the patch scope could not be bounded
    return None


def _evidence(refs: list) -> list[dict]:
    out = []
    for e in refs:
        if e.get("digest") is not None and not SHA256.match(str(e["digest"])):
            raise InvalidReceipt(f"evidence digest {e['digest']!r} is not a sha256: a corrupted evidence reference")
        out.append({**e, "resolution": "digest_bound" if e.get("digest") else "locator_only"})
    return out


def check_receipt(receipt) -> None:
    """Raise InvalidReceipt unless `receipt` is a receipt-v1 that holds together (receipts.problems)."""
    if not isinstance(receipt, dict) or receipt.get("predicateType") != receipts.V1:
        got = receipt.get("predicateType") if isinstance(receipt, dict) else type(receipt).__name__
        raise InvalidReceipt(f"feedback is made from a receipt-v1 ({receipts.V1}), not {got!r}")
    if problems := receipts.problems(receipt):
        raise InvalidReceipt("receipt-v1 does not hold together: " + "; ".join(problems))


def check_limit(limit) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"iteration_limit is a whole number from 1 to {MAX_LIMIT}, not {limit!r}")
    return limit


def from_receipt(receipt: dict, *, iteration: int = 0, iteration_limit: int = DEFAULT_LIMIT,
                 parent: str | None = None, chain: str | None = None, reconcile: bool = False) -> dict:
    """The feedback-v1 of a receipt-v1. iteration: corrected texts already taken in this chain (0 for the first
    feedback); parent: the feedback this one follows; chain: the first source receipt's id (default: this one's);
    reconcile: an external action's outcome was reported unknown (repair.py), so a text that still does not verify
    asks for reconciliation, not another repair."""
    check_receipt(receipt)
    limit = check_limit(iteration_limit)
    if isinstance(iteration, bool) or not isinstance(iteration, int) or not 0 <= iteration <= limit:
        raise ValueError(f"iteration is a whole number from 0 to iteration_limit ({limit}), not {iteration!r}")
    pred = receipt["predicate"]
    verification, scope = pred["verification"], pred["scope"]
    source = receipt_id(receipt)
    findings, candidates = [], []
    for i, f in enumerate(verification["findings"]):
        cond = condition(f)
        why = _not_actionable(f, cond)
        op = operation(f, cond) if why is None else None
        entry = {"finding_id": finding_id(i, f), "index": i, "check": f["check"], "module": f["module"],
                 "line": f["line"], "subject": f["subject"], "verdict": f["verdict"], "fact": f["fact"],
                 "reason": f["reason"], "decision": f["decision"], "message": f["message"],
                 "evidence": _evidence(f["evidence"]), "evidence_state": "present" if f["evidence"] else "absent",
                 "condition": cond, "actionable": op is not None, "not_actionable_reason": why, "action_id": None}
        findings.append(entry)
        if op is not None:
            candidates.append((entry, op))
    outcome = verification["outcome"]
    if outcome == "PASS":
        disposition = "verified"
    elif outcome in ("EMPTY", "NOT_RUN"):
        disposition = "nothing_verified"
    elif not candidates:
        disposition = "not_actionable"
    elif reconcile:
        disposition = "reconciliation_required"
    elif iteration >= limit:
        disposition = "budget_exhausted"
    else:
        disposition = "repair_requested"
    actions = []
    if disposition == "repair_requested":  # a terminal feedback asks for nothing
        for entry, op in candidates:
            action = {"operation": op, "finding_ids": [entry["finding_id"]], "condition": entry["condition"],
                      "target": {"check": entry["check"], "line": entry["line"], "subject": entry["subject"],
                                 "extent": "paragraph" if entry["check"] in PARAGRAPH else "line"},
                      "requirements": list(OPERATIONS[op]), "idempotent": entry["check"] not in EXTERNAL,
                      "preserve_valid_content": True}
            action = {"action_id": digest(receipts.dumps(action).encode("utf-8")), **action}
            entry["action_id"] = action["action_id"]
            actions.append(action)
    body = {
        "schema_version": V1,
        "chain": chain or source,
        "parent": parent,
        "advisory": True,
        "source_receipt": {"id": source, "predicate_type": receipt["predicateType"],
                           "checked_at": pred["checked_at"], "outcome": outcome, "coverage": scope["coverage"],
                           "executed": list(scope["executed"]), "numbers": verification["numbers"]},
        "source_subject_digest": receipt["subject"][0]["digest"]["sha256"],
        "findings": findings,
        "recommended_actions": actions,
        "verification_requirements": {"receipt": receipts.V1, "subject_must_change": True,
                                      "executed_at_least": list(scope["executed"]),
                                      "numbers_at_least": verification["numbers"], "verified_outcome": "PASS"},
        "iteration": iteration,
        "iteration_limit": limit,
        "disposition": disposition,
    }
    return {"feedback_id": feedback_id(body), **body}


def from_assessment(assessment, **kw) -> dict:
    """The feedback-v1 of a verify.Assessment, through its receipt-v1 (the Assessment is not changed)."""
    return from_receipt(receipts.v1(assessment), **kw)


def feedback_id(feedback: dict) -> str:
    """The identity of a feedback: the sha256 of its canonical JSON without the feedback_id itself."""
    return digest(receipts.dumps({k: v for k, v in feedback.items() if k != "feedback_id"}).encode("utf-8"))


def dumps(feedback: dict) -> str:
    """Canonical JSON, as receipts.dumps: the same bytes for the same feedback."""
    return receipts.dumps(feedback)


def problems(feedback, receipt: dict | None = None) -> list[str]:
    """What is wrong with a feedback-v1: not one, an identity that is not its bytes', a disposition or condition
    outside the vocabulary, actions that do not match its findings. With `receipt`: whether it is exactly the
    feedback of that receipt (same findings, evidence and actions; none added, none changed). [] when it holds."""
    if not isinstance(feedback, dict) or feedback.get("schema_version") != V1:
        return [f"not a feedback-v1 ({V1})"]
    out = []
    if feedback.get("feedback_id") != feedback_id(feedback):
        out.append("feedback_id is not the sha256 of the feedback: it was changed after it was made")
    if feedback.get("disposition") not in DISPOSITIONS:
        out.append(f"unknown disposition {feedback.get('disposition')!r}")
    if feedback.get("advisory") is not True:
        out.append("feedback is advisory, and says so")
    findings = feedback.get("findings") or []
    if any(f.get("condition") not in CONDITIONS for f in findings):
        out.append("a finding's condition is outside the vocabulary")
    by_id = {f.get("finding_id"): f for f in findings}
    for a in feedback.get("recommended_actions") or []:
        if a.get("operation") not in OPERATIONS:
            out.append(f"unknown operation {a.get('operation')!r}")
        if any(by_id.get(i, {}).get("action_id") != a.get("action_id") for i in a.get("finding_ids", [])):
            out.append(f"action {a.get('action_id')} is not the action of its findings")
    if (feedback.get("disposition") in TERMINAL) and feedback.get("recommended_actions"):
        out.append("a terminal feedback recommends actions")
    if receipt is not None:
        try:
            want = from_receipt(receipt, iteration=feedback.get("iteration"),
                                iteration_limit=feedback.get("iteration_limit"), parent=feedback.get("parent"),
                                chain=feedback.get("chain"),
                                reconcile=feedback.get("disposition") == "reconciliation_required")
        except (InvalidReceipt, ValueError) as error:
            return out + [f"the receipt: {error}"]
        if feedback.get("source_receipt", {}).get("id") != want["source_receipt"]["id"]:
            out.append("source_receipt is not this receipt")
        elif feedback != want:
            out.append("not this receipt's feedback: a finding, an evidence reference or an action differs")
    return out


# --- the schema ---------------------------------------------------------------------------------------------------

_STR, _NULL_STR, _ID = {"type": "string"}, {"type": ["string", "null"]}, {"type": "string", "pattern": ID.pattern}
_CHECKS = {"type": "array", "items": {"enum": list(receipts.CHECKS)}}
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": V1,
    "title": "buddie feedback-v1",
    "type": "object",
    "additionalProperties": False,
    "required": ["feedback_id", "schema_version", "chain", "parent", "advisory", "source_receipt",
                 "source_subject_digest", "findings", "recommended_actions", "verification_requirements",
                 "iteration", "iteration_limit", "disposition"],
    "properties": {
        "feedback_id": _ID,
        "schema_version": {"const": V1},
        "chain": _ID,
        "parent": {"type": ["string", "null"], "pattern": ID.pattern},
        "advisory": {"const": True},
        "source_receipt": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "predicate_type", "checked_at", "outcome", "coverage", "executed", "numbers"],
            "properties": {"id": _ID, "predicate_type": {"const": receipts.V1}, "checked_at": _STR,
                           "outcome": {"enum": list(receipts.OUTCOMES)}, "coverage": {"enum": list(receipts.COVERAGE)},
                           "executed": _CHECKS, "numbers": {"enum": list(NUMBERS_RANK)}}},
        "source_subject_digest": {"type": "string", "pattern": SHA256.pattern},
        "findings": {"type": "array", "items": {"$ref": "#/$defs/finding"}},
        "recommended_actions": {"type": "array", "items": {"$ref": "#/$defs/action"}},
        "verification_requirements": {
            "type": "object", "additionalProperties": False,
            "required": ["receipt", "subject_must_change", "executed_at_least", "numbers_at_least",
                         "verified_outcome"],
            "properties": {"receipt": {"const": receipts.V1}, "subject_must_change": {"const": True},
                           "executed_at_least": _CHECKS, "numbers_at_least": {"enum": list(NUMBERS_RANK)},
                           "verified_outcome": {"const": "PASS"}}},
        "iteration": {"type": "integer", "minimum": 0},
        "iteration_limit": {"type": "integer", "minimum": 1},
        "disposition": {"enum": list(DISPOSITIONS)},
    },
    "$defs": {
        "finding": {
            "type": "object", "additionalProperties": False,
            "required": ["finding_id", "index", "check", "module", "line", "subject", "verdict", "fact", "reason",
                         "decision", "message", "evidence", "evidence_state", "condition", "actionable",
                         "not_actionable_reason", "action_id"],
            "properties": {
                "finding_id": _ID, "index": {"type": "integer", "minimum": 0},
                "check": {"enum": list(receipts.CHECKS)}, "module": _STR, "line": {"type": ["integer", "null"]},
                "subject": _STR, "verdict": _STR, "fact": {"enum": [f.value for f in core.Fact]},
                "reason": {"enum": [r.value for r in core.ReasonCode]},
                "decision": {"enum": [d.value for d in core.Decision]}, "message": _NULL_STR,
                "evidence": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["kind", "locator", "provenance", "digest", "source", "observed_at", "resolution"],
                    "properties": {"kind": _STR, "locator": _STR,
                                   "provenance": {"enum": [p.value for p in core.Provenance]},
                                   "digest": {"type": ["string", "null"], "pattern": SHA256.pattern},
                                   "source": _NULL_STR, "observed_at": _NULL_STR,
                                   "resolution": {"enum": ["digest_bound", "locator_only"]}}}},
                "evidence_state": {"enum": ["present", "absent"]},
                "condition": {"enum": list(CONDITIONS)}, "actionable": {"type": "boolean"},
                "not_actionable_reason": {"enum": [*NOT_ACTIONABLE, None]},
                "action_id": {"type": ["string", "null"], "pattern": ID.pattern},
            }},
        "action": {
            "type": "object", "additionalProperties": False,
            "required": ["action_id", "operation", "finding_ids", "condition", "target", "requirements",
                         "idempotent", "preserve_valid_content"],
            "properties": {
                "action_id": _ID, "operation": {"enum": list(OPERATIONS)},
                "finding_ids": {"type": "array", "minItems": 1, "items": _ID},
                "condition": {"enum": list(CONDITIONS)},
                "target": {"type": "object", "additionalProperties": False,
                           "required": ["check", "line", "subject", "extent"],
                           "properties": {"check": {"enum": list(receipts.CHECKS)}, "line": {"type": "integer"},
                                          "subject": _STR, "extent": {"enum": ["line", "paragraph"]}}},
                "requirements": {"type": "array", "minItems": 1, "items": _STR},
                "idempotent": {"type": "boolean"}, "preserve_valid_content": {"const": True},
            }},
    },
}
