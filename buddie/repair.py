"""Bounded repair: one corrected text per feedback, kept within the feedback's scope, judged only by a new receipt.

An external agent reads a feedback-v1 (feedback.py), decides for itself whether and how to act, and hands back a
corrected text with a submission-v1:

  schema_version   SUBMISSION_V1
  feedback_id      the feedback it answers (the chain's newest, still repair_requested)
  iteration        that feedback's iteration
  artifact_before  sha256 (hex) of the text the feedback was made for, as the agent read it
  artifact_after   sha256 (hex) of the corrected text, as the agent sent it
  execution        what the agent says happened to any action outside the text: none, succeeded, failed, unknown
  action_ref       optional: the agent's own reference for what it did (a commit, a tool call id), at most 200
                   characters; recorded as its assertion, never resolved or trusted

No other field is accepted: a submission cannot set a disposition, an outcome, a finding or a budget.

`resolve` takes the trace, the feedback, the submission, the original and corrected texts, and the receipt-v1 of
the corrected text made by an independent run of verify (the caller's; `reverify` is one), and decides:

  - the agent's digests are compared with the texts' own (a false one is its assertion, recorded and rejected)
  - an unchanged text is no repair
  - every line the corrected text changes, deletes or inserts next to must be in the scope of an action: the line
    of the finding (its paragraph for quotes and numbers); a verified finding's claim must still be in the text
  - the receipt must be a consistent receipt-v1 (receipts.problems), of the corrected text (its subject), with at
    least the checks the source receipt ran and a numbers mode at least as strict: no weaker verifier is accepted
  - the outcome is the new receipt's, never the agent's. What became of each finding is recorded as proved (the
    same claim, checked again and supported), corrected (a claim of the same check on the same line, supported),
    removed (no claim of that check on that line any more) or still_open. None of these says the text is true

Every submission that reaches these checks spends one iteration, accepted or not, so the loop ends within
`iteration_limit` submissions whatever the agent sends. A submission that does not belong to the chain (malformed,
an unknown field, a changed or foreign feedback, a feedback already answered, a closed chain) raises SubmissionError
and is not recorded: it spends nothing and changes nothing. The same submission sent twice is refused the second
time with the decision already recorded.

execution = "unknown" with an action whose claim is an effect in the world (pr:, ci:, run:) means the agent does not
know whether it acted: if the new receipt is not PASS, the disposition is reconciliation_required and no action is
recommended, since repeating one (a merge, a re-run) may not be idempotent. "succeeded" and "failed" are recorded
as said and change nothing: only the receipt decides.

Nothing here calls a model, runs a check by itself, or acts outside the values it returns.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from buddie import feedback as fb
from buddie import receipts
from buddie import trace as tr

SUBMISSION_V1 = "https://github.com/tsyyan/buddie#repair-submission-v1"
EXECUTION = ("none", "succeeded", "failed", "unknown")
REQUIRED = frozenset({"schema_version", "feedback_id", "iteration", "artifact_before", "artifact_after", "execution"})
OPTIONAL = frozenset({"action_ref"})
ERRORS = ("malformed_submission", "unauthorized_field", "forged_feedback", "feedback_mismatch", "artifact_mismatch",
          "loop_closed", "duplicate_submission")
REJECTIONS = ("assertion_mismatch", "unchanged_artifact", "out_of_scope", "verified_content_changed",
              "reverification_missing", "receipt_invalid", "receipt_mismatch", "weaker_verification")
HEX = re.compile(r"^[0-9a-f]{64}$")


class SubmissionError(ValueError):
    """A submission refused before it touches the chain; `code` is one of ERRORS."""

    def __init__(self, code: str, message: str, decision: dict | None = None):
        super().__init__(f"{code}: {message}")
        self.code, self.decision = code, decision


@dataclass(frozen=True)
class Result:
    records: tuple       # the trace with this iteration appended
    feedback: dict       # the next feedback (terminal unless repair_requested)
    decision: dict       # the decision record's body


def submission(feedback: dict, original: str, corrected: str, *, execution: str = "none",
               action_ref: str | None = None) -> dict:
    """A submission-v1 for `corrected`, as an honest agent would make it (tests and simple callers)."""
    out = {"schema_version": SUBMISSION_V1, "feedback_id": feedback["feedback_id"],
           "iteration": feedback["iteration"], "artifact_before": fb.text_digest(original),
           "artifact_after": fb.text_digest(corrected), "execution": execution}
    return {**out, "action_ref": action_ref} if action_ref is not None else out


def check_submission(sub, feedback: dict) -> None:
    if not isinstance(sub, dict):
        raise SubmissionError("malformed_submission", "a submission is a JSON object")
    if extra := sorted(set(sub) - REQUIRED - OPTIONAL):
        raise SubmissionError("unauthorized_field", f"fields outside the submission contract: {extra}")
    if missing := sorted(REQUIRED - set(sub)):
        raise SubmissionError("malformed_submission", f"missing {missing}")
    if sub["schema_version"] != SUBMISSION_V1:
        raise SubmissionError("malformed_submission", f"schema_version is not {SUBMISSION_V1}")
    if sub["execution"] not in EXECUTION:
        raise SubmissionError("malformed_submission", f"execution is one of {EXECUTION}")
    if not all(isinstance(sub[k], str) and HEX.match(sub[k]) for k in ("artifact_before", "artifact_after")):
        raise SubmissionError("malformed_submission", "artifact digests are sha256 hex")
    ref = sub.get("action_ref")
    if ref is not None and (not isinstance(ref, str) or len(ref) > 200):
        raise SubmissionError("malformed_submission", "action_ref is a string of at most 200 characters")
    if sub["feedback_id"] != feedback["feedback_id"] or sub["iteration"] != feedback["iteration"]:
        raise SubmissionError("feedback_mismatch", "the submission answers another feedback or iteration")


def scope(feedback: dict, original: str) -> set[int]:
    """The lines of `original` (1-based) the feedback's actions allow a correction to touch."""
    lines, out = original.split("\n"), set()
    for a in feedback["recommended_actions"]:
        n = a["target"]["line"]
        if not 1 <= n <= len(lines):
            continue
        out.add(n)
        if a["target"]["extent"] == "paragraph":
            while n < len(lines) and lines[n].strip():  # lines[n] is line n + 1
                n += 1
                out.add(n)
    return out


def changes(original: str, corrected: str) -> tuple[list[int], list[int]]:
    """(lines of `original` replaced or deleted, positions inserted after: 0 is before the first line)."""
    a, b = original.split("\n"), corrected.split("\n")
    changed, inserted = [], []
    for op, i1, i2, _, _ in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op in ("replace", "delete"):
            changed += range(i1 + 1, i2 + 1)
        elif op == "insert":
            inserted.append(i1)
    return changed, inserted


def outside(allowed: set[int], changed: list[int], inserted: list[int]) -> list[int]:
    """Lines a correction touched outside `allowed` (an insertion is allowed next to an allowed line)."""
    out = [n for n in changed if n not in allowed]
    out += [n for n in inserted if n not in allowed and n + 1 not in allowed]
    return sorted(set(out))


def lost_verified(feedback: dict, corrected: str) -> list[str]:
    """Verified findings whose claim (a quotation, a number, an anchor) is no longer in the corrected text."""
    hay = " ".join(corrected.split())
    return [f["finding_id"] for f in feedback["findings"]
            if f["condition"] == "verified" and f["check"] != "work_claim"  # a work claim's subject is its kind
            and " ".join(f["subject"].split()) not in hay]


def receipt_rejection(receipt, feedback: dict, after: str) -> str | None:
    if receipt is None:
        return "reverification_missing"
    try:
        fb.check_receipt(receipt)
    except fb.InvalidReceipt:
        return "receipt_invalid"
    if receipt["subject"][0]["digest"]["sha256"] != after:
        return "receipt_mismatch"
    want = feedback["verification_requirements"]
    pred = receipt["predicate"]
    if (not set(want["executed_at_least"]) <= set(pred["scope"]["executed"])
            or fb.NUMBERS_RANK[pred["verification"]["numbers"]] < fb.NUMBERS_RANK[want["numbers_at_least"]]):
        return "weaker_verification"
    return None


def follow(previous: dict, *, reconcile: bool = False) -> dict:
    """The next feedback when a submission was rejected: the same findings, one iteration later, so the budget is
    spent (equal to feedback.from_receipt of the same receipt at the next iteration)."""
    body = {k: v for k, v in previous.items() if k != "feedback_id"}
    iteration = previous["iteration"] + 1
    disposition = ("reconciliation_required" if reconcile else
                   "budget_exhausted" if iteration >= previous["iteration_limit"] else "repair_requested")
    findings = [dict(f) for f in previous["findings"]]
    actions = previous["recommended_actions"]
    if disposition != "repair_requested":
        actions = []
        for f in findings:
            f["action_id"] = None
    body.update(parent=previous["feedback_id"], iteration=iteration, disposition=disposition, findings=findings,
                recommended_actions=list(actions))
    return {"feedback_id": fb.feedback_id(body), **body}


def _resolved(feedback: dict, receipt: dict | None) -> dict:
    new = receipt["predicate"]["verification"]["findings"] if receipt else None
    out = {}
    for f in feedback["findings"]:
        if not f["action_id"]:
            continue
        if new is None:
            out[f["finding_id"]] = "still_open"
            continue
        same = [g for g in new if g["check"] == f["check"] and g["subject"] == f["subject"]]
        here = [g for g in new if g["check"] == f["check"] and g["line"] == f["line"]]
        if same:
            out[f["finding_id"]] = "proved" if all(g["fact"] == "supported" for g in same) else "still_open"
        elif here:
            out[f["finding_id"]] = "corrected" if all(g["fact"] == "supported" for g in here) else "still_open"
        else:
            out[f["finding_id"]] = "removed"
    return out


def resolve(records, feedback: dict, sub: dict, *, original: str, corrected: str, receipt: dict | None = None
            ) -> Result:
    """One iteration of the chain `records` (see the module's docstring). Returns the new records, the next
    feedback and the decision; raises SubmissionError for a submission that does not belong to the chain."""
    state = tr.replay(records)
    if fb.problems(feedback):
        raise SubmissionError("forged_feedback", "; ".join(fb.problems(feedback)))
    if feedback["chain"] != state.chain:
        raise SubmissionError("feedback_mismatch", "the feedback belongs to another chain")
    if feedback["feedback_id"] in state.answered:
        done = next((d for d in state.decisions if d["feedback_id"] == feedback["feedback_id"]), None)
        raise SubmissionError("duplicate_submission", "this feedback was already answered", done)
    if state.terminal:
        raise SubmissionError("loop_closed", f"the chain is {state.disposition}: no repair is taken")
    if feedback["feedback_id"] != state.feedback_id:
        raise SubmissionError("feedback_mismatch", "not the chain's open feedback")
    check_submission(sub, feedback)
    before = feedback["source_subject_digest"]
    if fb.text_digest(original) != before:
        raise SubmissionError("artifact_mismatch", "the original text is not the one the feedback was made for")

    after = fb.text_digest(corrected)
    changed, inserted = changes(original, corrected)
    stray = outside(scope(feedback, original), changed, inserted)
    rejection = None
    if sub["artifact_before"] != before or sub["artifact_after"] != after:
        rejection = "assertion_mismatch"
    elif after == before:
        rejection = "unchanged_artifact"
    elif stray:
        rejection = "out_of_scope"
    elif lost_verified(feedback, corrected):
        rejection = "verified_content_changed"
    else:
        rejection = receipt_rejection(receipt, feedback, after)
    accepted = rejection is None
    reconcile = sub["execution"] == "unknown" and any(not a["idempotent"] for a in feedback["recommended_actions"])

    iteration = feedback["iteration"]
    records = tr.append(tuple(records), "submission", iteration, {
        "feedback_id": feedback["feedback_id"],
        "submission": fb.digest(receipts.dumps(sub).encode("utf-8")),
        "asserted": {"artifact_before": sub["artifact_before"], "artifact_after": sub["artifact_after"],
                     "execution": sub["execution"], "action_ref": sub.get("action_ref")},
        "observed": {"artifact_before": before, "artifact_after": after, "changed_lines": changed,
                     "inserted_after": inserted, "out_of_scope": stray,
                     "receipt": fb.receipt_id(receipt) if isinstance(receipt, dict) else None,
                     "status": "accepted" if accepted else "rejected", "rejection": rejection}})
    if accepted:
        records = tr.append(records, "reverification", iteration, tr.receipt_body(receipt))
        following = fb.from_receipt(receipt, iteration=iteration + 1, iteration_limit=feedback["iteration_limit"],
                                    parent=feedback["feedback_id"], chain=feedback["chain"], reconcile=reconcile)
    else:
        following = follow(feedback, reconcile=reconcile)
    decision = {"feedback_id": feedback["feedback_id"], "status": "accepted" if accepted else "rejected",
                "rejection": rejection, "receipt": fb.receipt_id(receipt) if accepted else None,
                "outcome": receipt["predicate"]["verification"]["outcome"] if accepted else None,
                "resolved": _resolved(feedback, receipt if accepted else None),
                "disposition": following["disposition"], "terminal": following["disposition"] in fb.TERMINAL,
                "next_feedback": following["feedback_id"]}
    records = tr.append(records, "decision", iteration, decision)
    records = tr.append(records, "feedback", iteration + 1, tr.feedback_body(following))
    return Result(records, following, decision)


def reverify(corrected: str, **kw) -> dict:
    """The receipt-v1 of a fresh verify run on `corrected` (verify.assessment's arguments): the independent check
    `resolve` takes. Give it the options the source receipt was made with, or a stricter set."""
    from buddie import verify
    return receipts.v1(verify.assessment(corrected, **kw))
